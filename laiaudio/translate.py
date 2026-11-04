"""English → Spanish translation on your PC: local AI (llama.cpp) or literal (Marian)."""
import atexit
import ctypes
import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
import urllib.request

from gi.repository import GLib

from .config import config
from .models import BY_ID
from .paths import DATA_DIR

PR_SET_PDEATHSIG = 1

PROMPT = """You are an interpreter in work meetings of a software development team. \
You receive fragments of an automatic English transcript and turn them into natural, fluent Mexican Spanish.

- Interpret the intent; do not translate word by word. Say it the way a Spanish speaker in the same meeting would.
- The transcript is automatic and may contain misheard words or cut sentences: fix them from the context.
- Use the terminology Spanish-speaking software teams use: "grid" is "tabla"; terms such as ticket, sprint, \
backlog, story points, deploy or pull request stay as they are commonly used.
- Reduce filler words and repetitions ("yeah, yeah, okay") to what matters.
- <context> holds the previous sentences, only to understand; translate only what is inside <translate>.
- Reply with the Spanish translation only, without quotes or comments."""


def _user_message(text, context):
    return f"<context>{context}</context>\n<translate>{text}</translate>"


class Marian:
    """Literal translation on the CPU with CTranslate2."""

    def __init__(self, model):
        import ctranslate2
        import sentencepiece

        self.model = ctranslate2.Translator(str(model.path / "model"), device="cpu", compute_type="int8",
                                            inter_threads=1, intra_threads=2)
        self.sp = sentencepiece.SentencePieceProcessor(model_file=str(model.path / "sentencepiece.model"))

    def translate(self, text, _context):
        result = self.model.translate_batch([self.sp.encode(text, out_type=str)], beam_size=2)[0]
        return self.sp.decode(result.hypotheses[0])

    def close(self):
        pass


def _die_with_parent():
    """In the child process: get SIGTERM when the app dies (even abruptly) so no VRAM is left in use."""
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


def llama_server_binary():
    """The system llama-server (Arch package) or the official build install.sh downloads (Ubuntu)."""
    bundled = DATA_DIR / "llama.cpp" / "llama-server"
    return shutil.which("llama-server") or (str(bundled) if bundled.exists() else None)


def stop_leftover_servers():
    """Stop servers left alive by a previous app session."""
    subprocess.run(["pkill", "-f", f"llama-server .*--port {LlamaServer.PORT}"], check=False)


class LlamaServer:
    """Local LLM served by llama-server (llama.cpp with Vulkan: NVIDIA, AMD or Intel)."""

    PORT = 8791
    # GPU memory left free for the browser, videos, etc. With 2 GB, on an 8 GB GPU with Parakeet loaded,
    # part of the model ended up on the CPU and each sentence took ~1.7 s; with 1 GB it fits entirely
    # and takes ~0.6 s
    FREE_VRAM_MB = 1024

    def __init__(self, model):
        server = llama_server_binary()
        if not server:
            raise RuntimeError("llama.cpp is missing (run install.sh again)")
        gguf = model.file(model.files[0][1])
        self.proc = subprocess.Popen(
            [server, "-m", str(gguf), "--host", "127.0.0.1", "--port", str(self.PORT),
             # No -ngl: llama.cpp puts on the GPU the layers that fit while leaving FREE_VRAM_MB free;
             # the rest goes to the CPU
             "--fit-target", str(self.FREE_VRAM_MB), "--fit-ctx", "2048",
             "-c", "2048", "--parallel", "1", "--no-ui"],
            # No "host-visible" video memory: on GPUs without Resizable BAR that window is only 256 MB and,
            # if the AI fills it, the browser cannot play video and crashes
            env={**os.environ, "GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM": "1"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=_die_with_parent)
        atexit.register(self.close)
        for _ in range(240):  # wait for the model to load
            if self.proc.poll() is not None:
                raise RuntimeError("llama-server exited while starting")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.PORT}/health", timeout=1) as r:
                    if r.status == 200:
                        return
            except OSError:
                pass
            time.sleep(0.5)
        self.close()
        raise RuntimeError("llama-server did not respond")

    def translate(self, text, context):
        return self.chat(PROMPT, _user_message(text, context))

    def chat(self, system, user, max_tokens=300, timeout=30):
        body = json.dumps({
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "cache_prompt": True,  # reuse the already processed instructions
        }).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.PORT}/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"].strip()

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


_server = None         # the one llama-server process, shared by the live translator and the text translator
_server_users = 0
_server_lock = threading.Lock()


class _Spawner(threading.Thread):
    """The only thread that starts llama-server.

    PR_SET_PDEATHSIG fires when the *thread* that forked the child exits, not only the process: a server started
    from a short-lived worker thread would die with it. This thread lives as long as the app.
    """

    def __init__(self):
        super().__init__(daemon=True, name="llama-spawner")
        self.jobs = queue.Queue()

    def run(self):
        while True:
            factory, reply = self.jobs.get()
            try:
                reply.put((factory(), None))
            except Exception as e:  # noqa: BLE001
                reply.put((None, e))

    def start_server(self, model):
        reply = queue.Queue()
        self.jobs.put((lambda: LlamaServer(model), reply))
        server, error = reply.get()
        if error:
            raise error
        return server


_spawner = _Spawner()
_spawner.start()


def acquire_llama(model):
    """Start llama-server (blocking) or reuse the running one: only one copy of the model ever sits in VRAM."""
    global _server, _server_users
    with _server_lock:
        if _server is None or _server.proc.poll() is not None:
            _server = _spawner.start_server(model)
        _server_users += 1
        return _server


def release_llama():
    """Stop llama-server once nobody uses it, freeing its video memory."""
    global _server, _server_users
    with _server_lock:
        _server_users = max(0, _server_users - 1)
        if _server_users == 0 and _server is not None:
            _server.close()
            _server = None


class SharedLlama:
    """Live-translation backend on top of the shared llama-server."""

    def __init__(self, model):
        self.server = acquire_llama(model)

    def translate(self, text, context):
        return self.server.translate(text, context)

    def close(self):
        if self.server:
            self.server = None
            release_llama()


BACKENDS = {"marian": Marian, "llama": SharedLlama}

ASSIST_PROMPT = """You are a writing assistant for a software developer whose first language is Spanish.

- If the text is in Spanish (even partly), rewrite it in clear, natural English at a B2 level: simple sentence \
structure, common professional vocabulary, the same meaning and tone. Fix any grammar mistakes.
- If the text is in English, translate it into natural Mexican Spanish.
- Keep technical terms such as ticket, sprint, backlog, pull request or deploy as developers use them.
- Keep the original formatting (line breaks, lists).
- Reply with the result only, without explanations or quotes."""

_SPANISH_WORDS = {"el", "la", "los", "las", "de", "que", "y", "en", "un", "una", "es", "por", "para", "con", "no",
                  "se", "lo", "del", "al", "como", "pero", "más", "este", "esta", "hay", "tengo", "quiero"}
_ENGLISH_WORDS = {"the", "and", "is", "to", "of", "a", "in", "that", "it", "for", "you", "with", "on", "this",
                  "are", "be", "we", "have", "not", "can", "will", "do", "i", "my", "what"}


def looks_spanish(text):
    """Quick guess used to label the direction in the UI (the model decides for itself)."""
    if any(ch in text for ch in "áéíóúñ¿¡"):
        return True
    words = [w.strip(".,;:!?\"'()").lower() for w in text.split()]
    return sum(w in _SPANISH_WORDS for w in words) > sum(w in _ENGLISH_WORDS for w in words)


def assistant_model():
    """The local LLM for the text translator: the live-translation one when it is an LLM, else the first downloaded."""
    current = BY_ID.get(config["translation"])
    if current and current.engine == "llama" and current.installed():
        return current
    return next((m for m in BY_ID.values() if m.engine == "llama" and m.installed()), None)


class TextAssistant:
    """Spanish → clear B2 English, or English → Spanish, for text the user pastes. Runs on worker threads."""

    def __init__(self):
        self.server = None
        self.lock = threading.Lock()

    def run(self, text, on_done, on_status):
        """on_done(result, error) and on_status(message) are called on the GTK thread."""
        def work():
            try:
                with self.lock:
                    if self.server is None:
                        model = assistant_model()
                        if model is None:
                            raise RuntimeError("Download Qwen3 4B or Gemma 3 4B in Settings → Translation")
                        GLib.idle_add(on_status, f"Loading {model.short}…")
                        self.server = acquire_llama(model)
                    GLib.idle_add(on_status, "Working…")
                    result = self.server.chat(ASSIST_PROMPT, text, max_tokens=1500, timeout=120)
                GLib.idle_add(on_done, result, None)
            except Exception as e:  # noqa: BLE001 - server down, out of memory, timeout…
                GLib.idle_add(on_done, None, str(e))

        threading.Thread(target=work, daemon=True).start()

    def close(self):
        with self.lock:
            if self.server:
                self.server = None
                release_llama()


class Translator(threading.Thread):
    """Translate in order on its own thread; the engine comes from Settings → Translation."""

    CONTEXT_CHUNKS = 6  # previous fragments sent as context
    MAX_WAIT = 3.0      # a sentence waiting longer than this goes literal so we never fall behind

    def __init__(self, on_status):
        super().__init__(daemon=True)
        self.queue = queue.Queue()
        self.on_status = on_status  # status messages for the UI (called from this thread)
        self.backend = None
        self.backend_id = None
        self.fallback = None        # Marian, when downloaded and the chosen engine fails
        self.context = []
        self.reload_requested = True
        self.release_requested = False

    def release(self):
        """ES was turned off: unload the AI to free the GPU (it loads again when ES is turned on)."""
        self.release_requested = True
        self.queue.put(None)

    def reload(self):
        """The engine changed in Settings (or ES was turned on): reconnect before the next translation."""
        self.reload_requested = True
        self.release_requested = False
        self.queue.put(None)  # wake the thread even when there is nothing to translate

    def connect(self):
        self.reload_requested = False
        wanted = config["translation"]
        if self.backend and self.backend_id == wanted:
            return
        if self.backend:
            self.backend.close()
        self.backend, self.backend_id = None, wanted
        model = BY_ID.get(wanted)
        if model is None or model.engine == "none":
            self.on_status("No translation: choose an engine in Settings → Translation")
            return
        if not model.installed():
            self.on_status(f"{model.name} is not downloaded yet (Settings → Translation)")
            return
        if model.engine == "llama":
            self.on_status(f"Loading {model.name}…")
        try:
            self.backend = BACKENDS[model.engine](model)
            self.on_status(f"Translating with {model.name}")
        except Exception as e:  # noqa: BLE001
            print(f"Could not start {model.name}: {e}", flush=True)
            self.on_status(f"Could not start {model.name}: {e}")

    def close(self):
        if self.backend:
            self.backend.close()
        self.backend = self.backend_id = None

    def run(self):
        while True:
            batch = [self.queue.get()]
            while not self.queue.empty():
                batch.append(self.queue.get_nowait())
            if self.release_requested:
                self.release_requested = False
                self.close()
                self.reload_requested = True  # loads again when ES is turned back on
                continue
            if self.reload_requested:
                self.connect()
            # Merge consecutive fragments of the same turn into one request
            merged = []
            for item in filter(None, batch):
                text, callback, queued = item
                if merged and merged[-1][1] is callback:
                    merged[-1][0] += " " + text
                else:
                    merged.append([text, callback, queued])
            for text, callback, queued in merged:
                # Catch-up mode: with continuous speech, sentences can arrive faster than the AI translates;
                # the ones that already waited too long go literal (Marian, ~0.1 s) to stay current
                late = time.time() - queued > self.MAX_WAIT
                if translation := self.translate_one(text, literal=late):
                    GLib.idle_add(callback, translation)

    def translate_one(self, text, literal=False):
        context = " ".join(self.context[-self.CONTEXT_CHUNKS:])
        self.context.append(text)
        if self.backend and not (literal and self.literal()):
            try:
                return self.backend.translate(text, context)
            except Exception as e:  # noqa: BLE001 - server down, out of memory…
                print(f"Translation error, falling back to literal: {e}", flush=True)
        fallback = self.literal()
        return fallback.translate(text, context) if fallback else ""

    def literal(self):
        """Marian as the fallback (when downloaded); it loads the first time it is needed."""
        marian = BY_ID["marian"]
        if self.fallback is None and marian.installed():
            self.fallback = Marian(marian)
        return self.fallback

    def translate(self, text, callback):
        self.queue.put((text, callback, time.time()))
