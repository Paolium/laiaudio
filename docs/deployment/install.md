# Installation and updates

## install.sh

1. Installs the system dependencies with `pacman --needed`: Python, PyGObject, PyCairo, GTK4, libadwaita,
   gtk4-layer-shell, libpulse, pipewire-pulse, llama.cpp and ggml-vulkan.
2. Migrates data from earlier versions ("Live Captions"): models and settings are moved, old launchers removed.
3. Creates `~/.local/share/laiaudio/venv` with `--system-site-packages` (for PyGObject) and installs the package with
   the `nvidia` extra (`onnxruntime-gpu` with CUDA libraries) or the `cpu` extra (`onnxruntime`).
4. Writes the launcher `~/.local/bin/laiaudio`, the desktop entry and the icon.

It is idempotent: run it again after `git pull` to update.

## Files

| What | Where |
| --- | --- |
| Transcripts | `~/Documents/Laiaudio/` (configurable) |
| Settings | `~/.config/laiaudio/config.json` |
| Models | `~/.local/share/laiaudio/models/` |
| Python environment | `~/.local/share/laiaudio/venv/` |
| Log | `~/.cache/laiaudio/app.log` |

## uninstall.sh

Removes the venv, launcher, desktop entry and icon, and asks before deleting models and settings. Transcripts are
never deleted.
