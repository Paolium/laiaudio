"""User settings in ~/.config/laiaudio/config.json."""
import json
from pathlib import Path

from .paths import CONFIG_DIR, CONFIG_FILE, DEFAULT_MEETINGS_DIR

DEFAULTS = {
    "meetings_dir": str(DEFAULT_MEETINGS_DIR),
    "asr_model": "parakeet-v2",
    "asr_device": "auto",          # auto (NVIDIA GPU when available) | cpu
    "translation": "qwen3-4b",     # id of a translation model from the catalog, or "none"
    "system_source": "auto",       # auto = whatever plays on the default output
    "mic_source": "auto",          # auto = default microphone
    "use_mic": True,
    "translation_active": False,   # the ES toggle, restored at startup
    "sidebar_visible": True,
    "overlay_enabled": True,
    "overlay_lines": 2,
    "overlay_font_size": 22,
    "overlay_monitor": "",         # screen for the caption bar the first time ("" = primary)
    "overlay_position": None,      # {"monitor", "left", "bottom"} once it has been moved
}


class Config(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        try:
            self.update(json.loads(CONFIG_FILE.read_text()))
        except (OSError, ValueError):
            self._first_run()

    def _first_run(self):
        """Pick the recommended models for this machine."""
        from .hardware import recommend

        asr, translation = recommend()
        self["asr_model"], self["translation"] = asr.id, translation.id
        self.save()

    def fit_to_hardware(self):
        """Fix a saved combination that does not fit this machine; return what changed, or None."""
        from .hardware import problem, recommend
        from .models import BY_ID

        best_asr, best_translation = recommend()
        asr = BY_ID.get(self["asr_model"])
        changes = []
        if asr is None or problem(asr, None):
            asr = best_asr
            self["asr_model"] = asr.id
            changes.append(f"transcription: {asr.short}")
        translation = BY_ID.get(self["translation"])
        if translation is None:
            self["translation"] = best_translation.id
            changes.append(f"translation: {best_translation.short}")
        elif problem(translation, asr):
            self["translation"] = "marian"
            changes.append("translation: Marian (literal)")
        if changes:
            self.save()
            return "Adjusted to what fits this machine — " + ", ".join(changes)
        return None

    def set(self, key, value):
        self[key] = value
        self.save()

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self, indent=2, ensure_ascii=False))
        tmp.replace(CONFIG_FILE)

    @property
    def meetings_dir(self):
        return Path(self["meetings_dir"]).expanduser()


config = Config()
