"""Application paths: they follow the XDG variables on Linux and the user's AppData folders on Windows."""
import os
from pathlib import Path

from .desktop import WINDOWS


def _xdg(var, default):
    return Path(os.environ.get(var) or Path.home() / default)


if WINDOWS:
    from .windows import documents_folder

    CONFIG_DIR = Path(os.environ["APPDATA"]) / "Laiaudio"
    DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "Laiaudio"   # install.ps1 puts the runtime and venv here
    LOG_FILE = DATA_DIR / "app.log"                            # on Linux the launcher writes ~/.cache/laiaudio/app.log
    DEFAULT_MEETINGS_DIR = documents_folder() / "Laiaudio"
else:
    CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "laiaudio"
    DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "laiaudio"
    DEFAULT_MEETINGS_DIR = Path.home() / "Documents" / "Laiaudio"
# LAIAUDIO_MODELS lets you try the app as on a fresh machine (no models downloaded)
MODELS_DIR = Path(os.environ.get("LAIAUDIO_MODELS") or DATA_DIR / "models")
CONFIG_FILE = CONFIG_DIR / "config.json"
