"""Catalog of downloadable models and their downloader (with progress)."""
import shutil
import threading
import urllib.request
import zipfile
from dataclasses import dataclass, field

from gi.repository import GLib

from .paths import MODELS_DIR

HF = "https://huggingface.co"


@dataclass
class Model:
    id: str
    kind: str            # "asr" | "translation"
    name: str
    gains: str           # its strength
    loses: str           # the trade-off: accuracy, quality or speed
    hardware: str        # what it needs to run
    files: list = field(default_factory=list)   # [(url, local_name, bytes)]
    unzip: str = ""      # folder inside the zip that is kept (Marian)
    engine: str = ""     # how it runs: parakeet | marian | llama | none
    short: str = ""      # short name for the dropdown
    gpu_mb: int = 0      # video memory it uses (0 = runs on the CPU)
    needs_cuda: bool = False  # NVIDIA GPU only

    @property
    def path(self):
        return MODELS_DIR / self.id

    @property
    def size(self):
        return sum(f[2] for f in self.files)

    @property
    def size_label(self):
        gb = self.size / 1e9
        return f"{gb:.1f} GB" if gb >= 1 else f"{self.size / 1e6:.0f} MB"

    @property
    def downloadable(self):
        return bool(self.files)

    def installed(self):
        if not self.files:
            return True
        if self.unzip:
            return (self.path / "model" / "model.bin").exists()
        return all((self.path / name).exists() for _, name, _ in self.files)

    def file(self, name):
        return self.path / name

    def delete(self):
        shutil.rmtree(self.path, ignore_errors=True)


def _hf(repo, *files):
    return [(f"{HF}/{repo}/resolve/main/{name}", name, size) for name, size in files]


CATALOG = [
    # --- transcription (English) ---
    # Measured on an i7-9700 with 120 s of speech: Lite differs from the full model in 0.7 % of the words
    Model("parakeet-v2", "asr", "Parakeet TDT 0.6B v2", short="Parakeet v2",
          gains="The most accurate English transcription; updates every 0.2 s on the GPU",
          loses="Uses ~3 GB of video memory while the app is open",
          hardware="NVIDIA GPU with ~3 GB free (otherwise use Lite)", engine="parakeet",
          gpu_mb=2900, needs_cuda=True,
          files=_hf("istupakov/parakeet-tdt-0.6b-v2-onnx",
                    ("config.json", 97), ("vocab.txt", 9384), ("nemo128.onnx", 139764),
                    ("decoder_joint-model.onnx", 35792059), ("encoder-model.onnx", 41770866),
                    ("encoder-model.onnx.data", 2435420160))),
    Model("parakeet-v2-int8", "asr", "Parakeet TDT 0.6B v2 (Lite)", short="Parakeet v2 Lite",
          gains="Almost the same accuracy as the full model, in real time on the CPU alone",
          loses="Updates every 0.6 s (text arrives in slightly bigger chunks) and uses more CPU",
          hardware="Any PC: AMD, Intel, Apple Silicon (Asahi Linux) or NVIDIA without enough VRAM",
          engine="parakeet",
          files=_hf("istupakov/parakeet-tdt-0.6b-v2-onnx",
                    ("config.json", 97), ("vocab.txt", 9384), ("nemo128.onnx", 139764),
                    ("decoder_joint-model.int8.onnx", 8998286), ("encoder-model.int8.onnx", 652184014))),

    # --- translation into Spanish ---
    Model("none", "translation", "No translation", short="No translation", gains="Uses no resources",
          loses="You only get English", hardware="", engine="none"),
    Model("qwen3-4b", "translation", "Local AI · Qwen3 4B", short="Qwen3 4B",
          gains="Interprets with context instead of word by word",
          loses="Each sentence takes ~1 s to translate",
          hardware="GPU with ~2.5 GB free (NVIDIA, AMD or Intel)", engine="llama", gpu_mb=2600,
          files=_hf("unsloth/Qwen3-4B-Instruct-2507-GGUF", ("Qwen3-4B-Instruct-2507-Q4_K_M.gguf", 2497281120))),
    Model("gemma3-4b", "translation", "Local AI · Gemma 3 4B", short="Gemma 3 4B",
          gains="Very good at translation; an alternative to compare with Qwen",
          loses="Each sentence takes ~1 s to translate",
          hardware="GPU with ~2.5 GB free (NVIDIA, AMD or Intel)", engine="llama", gpu_mb=2600,
          files=_hf("ggml-org/gemma-3-4b-it-GGUF", ("gemma-3-4b-it-Q4_K_M.gguf", 2489757856))),
    Model("marian", "translation", "Literal · Marian (OPUS)", short="Marian (literal)",
          gains="Instant and very light",
          loses="Lower quality: translates word by word",
          hardware="Any PC (CPU)", engine="marian", unzip="en_es",
          files=[("https://argos-net.com/v1/translate-en_es-1_0.argosmodel", "en_es.zip", 87503191)]),
]

BY_ID = {m.id: m for m in CATALOG}


def of_kind(kind):
    return [m for m in CATALOG if m.kind == kind]


class Download(threading.Thread):
    """Download a model's files to .part and rename them when finished.

    Notifications (progress 0–1 and completion) arrive on the GTK thread.
    """

    active = {}  # model id -> running Download

    def __init__(self, model):
        super().__init__(daemon=True)
        self.model = model
        self.progress = 0.0
        self.cancelled = False
        self.listeners = []  # callbacks (download, finished, error)

    @classmethod
    def start_for(cls, model):
        if model.id not in cls.active:
            cls.active[model.id] = d = cls(model)
            d.start()
        return cls.active[model.id]

    def listen(self, callback):
        self.listeners.append(callback)

    def _notify(self, done, error=None):
        for cb in list(self.listeners):
            GLib.idle_add(cb, self, done, error)

    def run(self):
        error = None
        try:
            self._download()
        except Exception as e:  # noqa: BLE001 - network, disk, corrupt file
            error = "Download cancelled" if self.cancelled else str(e)
        Download.active.pop(self.model.id, None)
        self._notify(True, error)

    def _download(self):
        path = self.model.path
        path.mkdir(parents=True, exist_ok=True)
        done_bytes, total = 0, self.model.size or 1
        for url, name, size in self.model.files:
            target = path / name
            if target.exists() or (self.model.unzip and self.model.installed()):
                done_bytes += size
                continue
            part = target.with_name(name + ".part")
            req = urllib.request.Request(url, headers={"User-Agent": "laiaudio"})
            with urllib.request.urlopen(req, timeout=30) as r, part.open("wb") as f:
                while chunk := r.read(1 << 20):
                    if self.cancelled:
                        raise RuntimeError("cancelled")
                    f.write(chunk)
                    done_bytes += len(chunk)
                    self.progress = min(done_bytes / total, 0.999)
                    self._notify(False)
            part.replace(target)
            if self.model.unzip:
                self._extract(target)

    def _extract(self, archive):
        """Keep only the model folder (e.g. en_es/model and sentencepiece.model)."""
        prefix = self.model.unzip.rstrip("/") + "/"
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if not info.filename.startswith(prefix) or info.is_dir():
                    continue
                rel = info.filename[len(prefix):]
                if ".." in rel.split("/") or rel.startswith("/"):
                    continue  # suspicious paths inside the zip
                dest = self.model.path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
        archive.unlink()

    def cancel(self):
        self.cancelled = True
