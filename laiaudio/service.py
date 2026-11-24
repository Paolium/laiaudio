"""Laiaudio's engine without a UI, for the native Windows app (winui/): one JSON message per line. Windows only.

The WinUI app starts `python -m laiaudio.service` and talks to it through stdin (commands) and stdout (events).
It owns the same rules as the GTK app (`app.py`): the recording lifecycle, the transcription engine, the
translators, the model downloads and what fits this machine. Everything the user sees is drawn by the WinUI app.

Commands: {"cmd": name, ...}; events: {"event": name, ...}. See docs/architecture/windows.md.
"""
import json
import os
import sys
import threading
import time

from . import audio, mainloop
from .asr import Engine, Stream
from .config import DEFAULTS, config
from .hardware import detect, problem, recommend
from .models import BY_ID, CATALOG, Download
from .paths import LOG_FILE
from .transcript import ME, MEETING, Transcript
from .translate import TextAssistant, Translator, assistant_model

SETTING = {"asr": "asr_model", "translation": "translation"}


class Service:
    def __init__(self, events):
        self.events = events          # protocol output (the real stdout)
        self.queue = mainloop.use_queue()
        self.running = True
        self.engine = None
        self.engine_state = {"status": "loading", "model": ""}
        self.engine_pending = False   # the model changed while recording
        self.recording = False
        self.saving = False
        self.streams = []
        self.transcript = None
        self.started = 0.0
        self._translator = None
        self.assistant = TextAssistant()
        self.turn_callbacks = {}      # live turn id -> callback (the translator merges fragments of one turn)
        self.listened = set()         # downloads whose progress is already forwarded
        self.progress_sent = {}

    # --- protocol ---
    def send(self, event, **data):
        self.events.write(json.dumps({"event": event, **data}, ensure_ascii=False) + "\n")
        self.events.flush()

    def toast(self, text, button=None, action=None):
        self.send("toast", text=text, button=button, action=action)

    def read_commands(self):
        """Stdin reader thread: every command runs on the main thread. EOF means the window is gone."""
        for line in sys.stdin:
            line = line.strip()
            if line:
                try:
                    mainloop.idle_add(self.handle, json.loads(line))
                except ValueError:
                    print(f"Bad command: {line[:200]}", flush=True)
        mainloop.idle_add(self.handle, {"cmd": "quit"})

    def run(self):
        threading.Thread(target=self.read_commands, daemon=True).start()
        if note := config.fit_to_hardware():
            self.toast(note)
        self.send_state()
        if config["translation_active"]:
            self.set_translation_active(True)
        self.load_engine()
        while self.running:
            callback, args = self.queue.get()
            try:
                callback(*args)
            except Exception as e:  # noqa: BLE001 - one bad command must not stop the engine
                print(f"{getattr(callback, '__name__', callback)} failed: {e!r}", flush=True)
                self.toast(f"Something went wrong: {e}")
        if self._translator:
            self._translator.close()  # stops llama-server
        self.assistant.close()

    def handle(self, msg):
        name = msg.get("cmd")
        handler = getattr(self, f"cmd_{name}", None)
        if handler is None:
            print(f"Unknown command: {name}", flush=True)
            return
        handler(**{k: v for k, v in msg.items() if k != "cmd"})

    # --- state ---
    def model_problem(self, model):
        """Transcription is judged alone (translation adapts if it no longer fits); translation, together with it."""
        return problem(model, BY_ID.get(config["asr_model"]) if model.kind == "translation" else None)

    def model_info(self, model, recommended):
        download = Download.active.get(model.id)
        return {"id": model.id, "kind": model.kind, "name": model.name, "short": model.short,
                "gains": model.gains, "loses": model.loses, "hardware": model.hardware,
                "size_label": model.size_label, "downloadable": model.downloadable,
                "installed": model.installed(), "problem": self.model_problem(model),
                "recommended": model in recommended, "engine": model.engine,
                "downloading": download is not None, "progress": download.progress if download else 0.0}

    def send_state(self):
        hw = detect()
        recommended = recommend()
        assistant = assistant_model()
        self.send("state", config=dict(config), recording=self.recording, started=self.started,
                  hardware={"summary": hw.summary, "cuda": hw.cuda},
                  recommended=[m.id for m in recommended], recommended_label=" + ".join(m.short for m in recommended),
                  models=[self.model_info(m, recommended) for m in CATALOG],
                  engine=self.engine_state, engine_description=self.engine_description(),
                  assistant_model=assistant.short if assistant else None)

    def engine_description(self):
        if not self.engine:
            return "The model is not loaded yet"
        return f"Now: {'CPU (slower)' if self.engine.slow else 'GPU'}"

    def set_engine_state(self, status, model, detail=""):
        self.engine_state = {"status": status, "model": model.name, "model_id": model.id, "detail": detail}
        self.send("engine", **self.engine_state)

    # --- transcription engine ---
    def load_engine(self):
        model = BY_ID.get(config["asr_model"]) or BY_ID["parakeet-v2"]
        self.engine = None
        if not model.installed():
            self.set_engine_state("missing", model)
            return
        self.set_engine_state("loading", model)

        def load():
            try:
                engine = Engine(model, config["asr_device"])
            except Exception as e:  # noqa: BLE001
                mainloop.idle_add(self.set_engine_state, "error", model, str(e))
                return
            mainloop.idle_add(self.engine_ready, engine, model)

        threading.Thread(target=load, daemon=True).start()

    def engine_ready(self, engine, model):
        self.engine = engine
        self.set_engine_state("ready", model, "slow" if engine.slow else "")
        self.send_state()  # "Run on" shows where it runs now
        if engine.slow:
            self.toast("Transcribing on the CPU: captions will lag slightly more")

    def models_changed(self, kind):
        """A model was chosen, downloaded or deleted."""
        if kind == "asr":
            if self.recording or self.saving:
                self.engine_pending = True
                self.toast("The new model will load when recording stops")
            else:
                self.load_engine()
        elif self._translator:
            self._translator.reload()
        self.send_state()

    # --- translation ---
    def translator(self):
        """The translator is created the first time ES is turned on."""
        if self._translator is None:
            self._translator = Translator(lambda msg: mainloop.idle_add(self.toast, msg))
            self._translator.start()
        return self._translator

    def set_translation_active(self, active):
        config.set("translation_active", active)
        if active:
            model = BY_ID.get(config["translation"])
            if model is None or model.engine == "none":
                self.toast("Choose a translation engine", "Settings", {"ui": "settings", "tab": "translation"})
                active = False
            elif not model.installed():
                self.toast(f"{model.name} is not downloaded yet ({model.size_label})", "Download",
                           {"cmd": "download_translation", "id": model.id})
                active = False
            else:
                translator = self.translator()
                translator.reload()
        if not active:
            config.set("translation_active", False)
            if self._translator:
                self._translator.release()  # frees the GPU while ES is off
        self.send("translation", active=active)

    def cmd_translation(self, active):
        self.set_translation_active(bool(active))

    def cmd_translate_turn(self, id, text):  # noqa: A002 - the protocol's field name
        if not (self._translator and config["translation_active"] and text):
            return
        callback = self.turn_callbacks.get(id)
        if callback is None:
            callback = self.turn_callbacks[id] = lambda translation: self.send("turn_translation", id=id,
                                                                               text=translation)
        self._translator.translate(text, callback)

    def cmd_download_translation(self, id):  # noqa: A002
        model = BY_ID[id]

        def done(_download, finished, error):
            if finished:
                self.toast(f"Download failed: {error}" if error else
                           f"{model.name} is ready: turn on ES to translate")
        self.start_download(model).listen(done)
        self.toast(f"Downloading {model.name}… (progress in Settings → Translation)")

    # --- text translator ---
    def cmd_assist(self, text):
        self.assistant.run(text, lambda result, error: self.send("assist_done", result=result, error=error),
                           lambda status: self.send("assist_status", text=status))

    def cmd_assist_close(self):
        """The translator page closed: free the GPU when nobody else uses the AI (a request may still run)."""
        threading.Thread(target=self.assistant.close, daemon=True).start()

    # --- models ---
    def start_download(self, model):
        download = Download.start_for(model)
        if download not in self.listened:
            self.listened.add(download)
            download.listen(self.on_download)
        self.send_state()
        return download

    def on_download(self, download, done, error):
        model = download.model
        step = round(download.progress * 200)  # forward every 0.5 %
        if not done and self.progress_sent.get(model.id) == step:
            return
        self.progress_sent[model.id] = step
        self.send("download", id=model.id, progress=download.progress, done=done, error=error)
        if done:
            self.listened.discard(download)
            self.models_changed(model.kind)

    def cmd_download(self, id):  # noqa: A002
        self.start_download(BY_ID[id])

    def cmd_cancel_download(self, id):  # noqa: A002
        if download := Download.active.get(id):
            download.cancel()

    def cmd_delete_model(self, id):  # noqa: A002
        model = BY_ID[id]
        model.delete()
        self.models_changed(model.kind)

    def cmd_pick_model(self, kind, id):  # noqa: A002
        model = BY_ID[id]
        if reason := self.model_problem(model):
            self.toast(reason)
            self.send_state()  # the picker goes back to the current model
            return
        config.set(SETTING[kind], model.id)
        if kind == "asr":  # a heavier Parakeet can leave no room for the translation AI
            translation = BY_ID.get(config["translation"])
            if translation and problem(translation, model):
                config.set("translation", "marian")
                self.toast(f"With {model.short}, {translation.short} no longer fits: "
                           "translation switched to Marian (literal)")
                self.models_changed("translation")
        self.models_changed(kind)

    def cmd_use_recommended(self):
        asr, translation = recommend()
        config.set("asr_model", asr.id)
        config.set("translation", translation.id)
        self.models_changed("asr")
        self.models_changed("translation")
        self.toast(f"Using {asr.short} + {translation.short}")

    # --- settings ---
    def cmd_hello(self):
        self.send_state()

    def cmd_set(self, key, value):
        if key not in DEFAULTS:
            print(f"Unknown setting: {key}", flush=True)
            return
        config.set(key, value)
        if key == "asr_device":
            self.models_changed("asr")

    def cmd_devices(self):
        self.send("devices", outputs=audio.outputs(), inputs=audio.inputs())

    # --- recording ---
    def cmd_start(self):
        if self.recording or self.saving or not self.engine:
            return
        meeting = audio.meeting_source(config["system_source"])
        if not meeting:
            self.toast(audio.NO_OUTPUT)
            return
        self.recording = True
        self.started = time.time()
        self.transcript = Transcript(config.meetings_dir)
        self.turn_callbacks.clear()
        self.send("recording", state="started", started=self.started)
        system = Stream(MEETING, meeting, 0.004, self.engine, self)
        self.streams = [system]
        if config["use_mic"]:
            self.streams.append(Stream(ME, audio.mic_source(config["mic_source"]), 0.015, self.engine, self,
                                       gate=system))
        for s in self.streams:
            s.start()

    def cmd_stop(self, quit_after=False):
        if not self.recording:
            if quit_after and not self.saving:
                self.running = False
            return
        self.recording = False
        self.saving = True
        self.send("recording", state="saving")

        def finish():
            for s in self.streams:
                s.stop()
            for s in self.streams:
                s.join(timeout=10)
            path = self.transcript.close()
            mainloop.idle_add(self.recording_saved, path, quit_after)

        threading.Thread(target=finish, daemon=True).start()

    def recording_saved(self, path, quit_after):
        self.streams = []
        self.saving = False
        self.send("recording", state="saved", path=str(path) if path else None)
        if path:
            self.toast(f"Saved to {path.name}", "Open", {"ui": "open", "path": str(path)})
        else:
            self.toast("No speech detected; nothing was saved")
        if quit_after:
            self.running = False
        elif self.engine_pending:
            self.engine_pending = False
            self.load_engine()

    def cmd_quit(self):
        """The window closed: save the meeting first."""
        self.cmd_stop(quit_after=True)

    # --- stream events (they arrive from other threads) ---
    def partial(self, speaker, _text, stable):
        # Only stable words are shown: the rest still changes and is distracting
        mainloop.idle_add(lambda: self.send("partial", speaker=speaker, text=stable))

    def committed(self, speaker, start, text, end_of_turn):
        self.transcript.add(speaker, start, text, end_of_turn)
        mainloop.idle_add(lambda: self.send("committed", speaker=speaker, start=start, text=text, end_of_turn=end_of_turn))


def main():
    # stdout carries the protocol; everything printed (by this package or by libraries) goes to the log
    events = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "a", buffering=1, encoding="utf-8", errors="replace")  # noqa: SIM115 - process lifetime
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)
    sys.stdout = sys.stderr = log
    sys.stdin.reconfigure(encoding="utf-8")
    print(f"--- Laiaudio service started {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    Service(events).run()
    print("--- Laiaudio service stopped", flush=True)


if __name__ == "__main__":
    main()
