#!/usr/bin/env bash
# Uninstall Laiaudio. Your meetings (.md) are never deleted.
set -euo pipefail

SHARE="${XDG_DATA_HOME:-$HOME/.local/share}"
DATA="$SHARE/laiaudio"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/laiaudio"

rm -rf "$DATA/venv"
rm -f "$HOME/.local/bin/laiaudio" "$SHARE/applications/laiaudio.desktop" \
  "$SHARE/icons/hicolor/scalable/apps/laiaudio.svg"
echo "App uninstalled."

if [ -d "$DATA/models" ]; then
  read -r -p "Also delete the downloaded models ($(du -sh "$DATA/models" | cut -f1))? [y/N] " answer
  if [[ "$answer" =~ ^[yY]$ ]]; then rm -rf "$DATA"; echo "Models deleted."; fi
fi
if [ -d "$CONFIG" ]; then
  read -r -p "Also delete your settings? [y/N] " answer
  if [[ "$answer" =~ ^[yY]$ ]]; then rm -rf "$CONFIG"; echo "Settings deleted."; fi
fi
echo "System dependencies (GTK, llama.cpp…) stay installed; remove them with pacman if you no longer need them."
