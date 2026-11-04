#!/usr/bin/env bash
# Install Laiaudio on Arch / Omarchy: system dependencies, the app and its launcher.
# AI models are downloaded from inside the app the first time you open it.
# Run it again to update (for example after `git pull`).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA="$SHARE/laiaudio"
VENV="$DATA/venv"
MODELS="$DATA/models"
BIN="$HOME/.local/bin"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

if ! command -v pacman >/dev/null; then
  echo "This installer is for Arch / Omarchy (it uses pacman)." >&2
  exit 1
fi

say "System dependencies (asks for your password)"
# UI (GTK4 + libadwaita + floating bar), audio (parec) and local translation AI (llama.cpp with Vulkan)
sudo pacman -S --needed python python-gobject python-cairo gtk4 libadwaita gtk4-layer-shell \
  libpulse pipewire-pulse llama-cpp ggml-vulkan vulkan-icd-loader

say "Data from earlier versions (Live Captions)"
OLD_DATA="$SHARE/live-captions"
if [ -d "$OLD_DATA/models" ] && [ ! -d "$MODELS" ]; then
  mkdir -p "$DATA"
  mv "$OLD_DATA/models" "$MODELS"
  echo "  models reused (no need to download them again)"
fi
if [ -d "$CONFIG_HOME/live-captions" ] && [ ! -d "$CONFIG_HOME/laiaudio" ]; then
  mv "$CONFIG_HOME/live-captions" "$CONFIG_HOME/laiaudio"
  echo "  settings migrated"
fi
rm -rf "$OLD_DATA" "$HOME/.cache/live-captions"
rm -f "$BIN/live-captions" "$SHARE/applications/live-captions.desktop" \
  "$SHARE/icons/hicolor/scalable/apps/"{apolingo,junote}.svg

say "Python environment"
python -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
  echo "NVIDIA GPU detected: transcription will use CUDA"
  "$VENV/bin/pip" uninstall -q -y onnxruntime 2>/dev/null || true
  extra=nvidia
else
  echo "No NVIDIA GPU: transcription will use the CPU (Parakeet v2 Lite)"
  "$VENV/bin/pip" uninstall -q -y onnxruntime-gpu 2>/dev/null || true
  extra=cpu
fi
"$VENV/bin/pip" install -q --upgrade "$REPO[$extra]"

say "Launcher and app menu"
mkdir -p "$BIN" "$SHARE/applications"
cat > "$BIN/laiaudio" <<LAUNCHER
#!/bin/bash
# Open Laiaudio. Log in ~/.cache/laiaudio/app.log
mkdir -p "\$HOME/.cache/laiaudio"
exec env LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so "$VENV/bin/python" -m laiaudio "\$@" \\
  >> "\$HOME/.cache/laiaudio/app.log" 2>&1
LAUNCHER
chmod +x "$BIN/laiaudio"
sed "s|@BIN@|$BIN|" "$REPO/data/laiaudio.desktop" > "$SHARE/applications/laiaudio.desktop"
install -Dm644 "$REPO/laiaudio/data/paolium-logo.svg" "$SHARE/icons/hicolor/scalable/apps/laiaudio.svg"
update-desktop-database "$SHARE/applications" 2>/dev/null || true

say "Done"
echo "Open «Laiaudio» from the app menu (or run: laiaudio)."
echo "The first time, it offers to download the transcription model."
