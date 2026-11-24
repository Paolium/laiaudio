"""Streaming transcription with Parakeet (onnx-asr)."""
import queue
import re
import threading
import time

import numpy as np
import onnxruntime as ort

from .audio import Capture

RATE = 16000
CHUNK = 0.1             # seconds read per iteration
SILENCE_COMMIT = 0.6    # pause that closes a sentence
STABLE_MARGIN = 1.5     # never commit words from the last 1.5 s
HARD_CAP = 15.0         # commit everything when the buffer reaches this


class Engine:
    """Loaded model + read cadence based on how fast the machine is."""

    def __init__(self, model, device):
        ort.set_default_logger_severity(3)
        if hasattr(ort, "preload_dlls"):  # onnxruntime-gpu only: loads the pip CUDA libraries
            ort.preload_dlls()
        import onnx_asr

        providers = ["CPUExecutionProvider"]
        on_gpu = device != "cpu" and model.needs_cuda  # Lite (int8) always runs on the CPU
        if on_gpu and "CUDAExecutionProvider" in ort.get_available_providers():
            # kSameAsRequested: reserve only what is used, leaving memory for the translation AI
            providers.insert(0, ("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC",
                                                           "arena_extend_strategy": "kSameAsRequested"}))
        quantization = "int8" if "int8" in model.id else None
        name = "nemo-parakeet-tdt-0.6b-v2"
        self.model = onnx_asr.load_model(name, str(model.path), quantization=quantization,
                                         providers=providers).with_timestamps()
        self.lock = threading.Lock()

        # Warm-up and measurement: on a slow machine read less often so captions never fall behind
        self.recognize(np.zeros(RATE, np.float32))
        t = time.time()
        self.recognize(np.zeros(RATE * 8, np.float32))
        self.slow = time.time() - t > 0.25
        self.decode_every = 6 if self.slow else 2      # every 0.6 s or every 0.2 s
        self.long_buffer = 5.0 if self.slow else 8.0   # from here on, stable words get committed
        self.backend = "CPU" if self.slow else "GPU"

    def recognize(self, audio):
        with self.lock:
            return self.model.recognize(audio, sample_rate=RATE)


_PUNCT = re.compile(r"[^\w']+")


def norm(word):
    """The word without case or punctuation: the model changes commas and capitals as it hears more context."""
    return _PUNCT.sub("", word.lower())


def same(a, b):
    return norm(a) == norm(b)


def to_words(result):
    """Group Parakeet tokens into words: [(text, start_s)]."""
    words = []
    for tok, ts in zip(result.tokens, result.timestamps):
        if tok.startswith(" ") or not words:
            words.append([tok, ts])
        else:
            words[-1][0] += tok
    return [(w.strip(), ts) for w, ts in words if w.strip()]


class Stream(threading.Thread):
    """Capture an audio source and transcribe it as a stream.

    `sink` receives partial(speaker, text, stable) and committed(speaker, start, text, end_of_turn).
    """

    def __init__(self, speaker, device, threshold, engine, sink, gate=None):
        super().__init__(daemon=True)
        self.speaker, self.device, self.threshold = speaker, device, threshold
        self.engine, self.sink, self.gate = engine, sink, gate
        self.last_voice = 0.0
        self.lag = 0.0  # how old the newest audio was when the last read finished
        self.proc = None

    def run(self):
        self.proc = Capture(self.device, f"Laiaudio ({self.speaker})", RATE)
        chunk_bytes = int(RATE * CHUNK) * 4
        interval, long_buffer = self.engine.decode_every * CHUNK, self.engine.long_buffer

        # One thread only reads audio; this thread takes EVERYTHING that arrived on each iteration. If a
        # read takes longer than the interval (e.g. while translation uses the GPU), the next one processes
        # more audio at once instead of building a queue that falls further and further behind.
        pending = queue.SimpleQueue()

        def reader():
            while data := self.proc.read(chunk_bytes):
                pending.put((time.time(), np.frombuffer(data, np.float32)))
            pending.put(None)

        threading.Thread(target=reader, daemon=True).start()

        buf = np.zeros(0, np.float32)
        buf_start = time.time()  # wall-clock time of buf[0]
        has_voice = False
        prev = []  # previous hypothesis (to see which words are stable)
        ended = False

        while not ended:
            deadline = time.time() + interval
            arrived = False
            while True:
                try:
                    item = pending.get(timeout=max(0.0, deadline - time.time()))
                except queue.Empty:
                    break
                if item is None:
                    ended = True
                    break
                now, x = item
                if self.gate and now - self.gate.last_voice < 0.4:
                    x = np.zeros_like(x)  # the meeting is speaking: this is echo
                if np.sqrt(np.mean(x * x)) > self.threshold:
                    self.last_voice = now
                    has_voice = True
                if not len(buf):
                    buf_start = now - len(x) / RATE
                buf = np.concatenate([buf, x])
                arrived, newest = True, now
            if ended or not arrived:
                continue
            now = time.time()
            dur = len(buf) / RATE

            if not has_voice:
                if dur > 2:
                    buf, buf_start = buf[-RATE:], buf_start + dur - 1
                continue

            try:
                words = to_words(self.engine.recognize(buf))
            except Exception as e:  # noqa: BLE001 - e.g. out of GPU memory: never kill the captions
                print(f"[{self.speaker}] read failed ({len(buf) / RATE:.1f} s of audio): {e}", flush=True)
                if dur > long_buffer:  # keep the recent part so the next read is lighter
                    keep = int(long_buffer / 2 * RATE)
                    buf, buf_start = buf[-keep:], buf_start + dur - keep / RATE
                    prev = []
                continue
            self.lag = time.time() - newest
            silent_for = now - self.last_voice

            if silent_for >= SILENCE_COMMIT or dur >= HARD_CAP:
                self.commit(words, buf_start, end_of_turn=silent_for >= SILENCE_COMMIT)
                buf, has_voice, prev, words = np.zeros(0, np.float32), False, [], []
            elif dur >= long_buffer:
                stable = 0
                while (stable < min(len(words), len(prev)) - 1
                       and same(words[stable][0], prev[stable][0])
                       and words[stable + 1][1] < dur - STABLE_MARGIN):
                    stable += 1
                if not stable and dur >= long_buffer + 2:
                    # Nobody pauses and the reads disagree: commit what is already old so the buffer does
                    # not keep growing (each read would get slower and heavier on the GPU)
                    stable = sum(1 for _, t in words[1:] if t < dur - STABLE_MARGIN)
                if stable:
                    self.commit(words[:stable], buf_start, end_of_turn=False)
                    cut = max(0.0, words[stable][1] - 0.05)
                    buf, buf_start = buf[int(cut * RATE):], buf_start + cut
                    words = [(w, t - cut) for w, t in words[stable:]]
                    prev = prev[stable:]
            # Words both of the last two reads agree on: they will not change anymore
            agree = 0
            while agree < min(len(words), len(prev)) and same(words[agree][0], prev[agree][0]):
                agree += 1
            prev = words
            self.sink.partial(self.speaker, " ".join(w for w, _ in words), " ".join(w for w, _ in words[:agree]))

        # Stopped: commit whatever was pending
        if has_voice and len(buf):
            try:
                self.commit(to_words(self.engine.recognize(buf)), buf_start, end_of_turn=True)
            except Exception as e:  # noqa: BLE001
                print(f"[{self.speaker}] could not read the tail: {e}", flush=True)
        self.sink.partial(self.speaker, "", "")

    def commit(self, words, buf_start, end_of_turn):
        text = " ".join(w for w, _ in words)
        start = buf_start + words[0][1] if words else buf_start
        if text or end_of_turn:
            self.sink.committed(self.speaker, start, text, end_of_turn)

    def stop(self):
        if self.proc:
            self.proc.close()
