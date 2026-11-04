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
        if not shutil.which("llama-server"):
            raise RuntimeError("llama.cpp is missing (run install.sh again)")
        gguf = model.file(model.files[0][1])
        self.proc = subprocess.Popen(
            ["llama-server", "-m", str(gguf), "--host", "127.0.0.1", "--port", str(self.PORT),
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
        body = json.dumps({
            "messages": [{"role": "system", "content": PROMPT},
                         {"role": "user", "content": _user_message(text, context)}],
            "temperature": 0.2,
            "max_tokens": 300,
            "cache_prompt": True,  # reuse the already processed instructions
        }).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.PORT}/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["choices"][0]["message"]["content"].strip()

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


BACKENDS = {"marian": Marian, "llama": LlamaServer}


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
