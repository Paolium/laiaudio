"""What this machine can run: GPU, video memory and which model combination fits."""
import glob
import subprocess
from dataclasses import dataclass
from functools import cache

DESKTOP_MB = 1536  # desktop, browser and open apps (measured ~1.5 GB on an Omarchy PC)
FREE_MB = 1024     # kept free on top of that for videos and the rest (like LlamaServer.FREE_VRAM_MB)


@dataclass(frozen=True)
class Hardware:
    gpu: str       # dedicated GPU name ("" when there is none)
    vram_mb: int   # dedicated video memory
    cuda: bool     # NVIDIA: required by Parakeet v2

    @property
    def budget_mb(self):
        """Video memory the models can use without starving the rest of the system."""
        return max(0, self.vram_mb - DESKTOP_MB - FREE_MB)

    @property
    def summary(self):
        return f"{self.gpu} · {self.vram_mb / 1024:.0f} GB VRAM" if self.gpu else "No dedicated GPU (CPU only)"


@cache
def detect():
    try:  # NVIDIA
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
        if out:
            name, mb = out[0].rsplit(",", 1)
            return Hardware(name.strip(), int(mb), True)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    for path in glob.glob("/sys/class/drm/card*/device/mem_info_vram_total"):  # AMD (amdgpu)
        try:
            mb = int(open(path).read()) // 2**20
        except (OSError, ValueError):
            continue
        if mb >= 1024:  # integrated GPUs report a few hundred MB
            return Hardware("AMD GPU", mb, False)
    return Hardware("", 0, False)  # no dedicated GPU (e.g. Intel integrated graphics)


def problem(model, other, hw=None):
    """Why `model` does not fit this machine together with `other` (the model of the other kind), or None."""
    hw = hw or detect()
    if model.needs_cuda and not hw.cuda:
        return "Needs an NVIDIA GPU (use Parakeet v2 Lite on this machine)"
    if not model.gpu_mb:
        return None
    if not hw.vram_mb:
        return "Needs a dedicated GPU (use Marian on this machine)"
    needed = model.gpu_mb + (other.gpu_mb if other else 0)
    if needed > hw.budget_mb:
        together = f" together with {other.short}" if other and other.gpu_mb else ""
        hint = " (use Parakeet v2 Lite)" if model.kind == "asr" else ""
        return (f"Not enough video memory: needs ~{needed / 1024:.1f} GB{together} "
                f"and your GPU fits ~{hw.budget_mb / 1024:.1f} GB{hint}")
    return None


def recommend(hw=None):
    """The best combination that fits: transcription first (it is the core), then translation."""
    from .models import BY_ID

    hw = hw or detect()
    asr = BY_ID["parakeet-v2"] if not problem(BY_ID["parakeet-v2"], None, hw) else BY_ID["parakeet-v2-int8"]
    translation = BY_ID["qwen3-4b"] if not problem(BY_ID["qwen3-4b"], asr, hw) else BY_ID["marian"]
    return asr, translation
