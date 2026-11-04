"""Application paths (they follow the XDG variables)."""
import os
from pathlib import Path


def _xdg(var, default):
    return Path(os.environ.get(var) or Path.home() / default)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "laiaudio"
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "laiaudio"
# LAIAUDIO_MODELS lets you try the app as on a fresh machine (no models downloaded)
MODELS_DIR = Path(os.environ.get("LAIAUDIO_MODELS") or DATA_DIR / "models")
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_MEETINGS_DIR = Path.home() / "Documents" / "Laiaudio"
