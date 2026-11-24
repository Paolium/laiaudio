# Installation and updates

## install.sh

Arch Linux and Omarchy only: it stops on a system without `pacman`.

1. Installs the system dependencies with `pacman --needed`: Python, PyGObject, PyCairo, GTK4, libadwaita,
   gtk4-layer-shell, libpulse, pipewire-pulse, llama.cpp and ggml-vulkan.
2. Migrates data from earlier versions ("Live Captions"): models and settings are moved, old launchers removed.
3. Creates `~/.local/share/laiaudio/venv` with `--system-site-packages` (for PyGObject) and installs the package with
   the `nvidia` extra (`onnxruntime-gpu` with CUDA libraries) or the `cpu` extra (`onnxruntime`).
4. Writes the launcher `~/.local/bin/laiaudio` (it preloads gtk4-layer-shell), the desktop entry and the icon.

It is idempotent: run it again after `git pull` to update.

## install.ps1 (Windows 11)

`install.cmd` runs it with `-ExecutionPolicy Bypass`, so a double-click is enough. It needs no administrator rights,
targets Windows PowerShell 5.1 (what Windows 11 ships) and uses the `curl.exe` and `tar.exe` that come with Windows.
Every download is pinned to a version and skipped when that version is already installed (a `.laiaudio-version`
file in each folder), so running it again only updates what changed.

1. Installs the Microsoft Visual C++ runtime only when it is missing (the one step that asks for permission).
2. Unpacks the official CPython (`$PythonVersion`, the NuGet package: no installer, no registry, no PATH changes)
   into `%LOCALAPPDATA%\Laiaudio\python`. It is the newest Python that `onnxruntime-gpu` supports.
3. Removes `gtk\`, the GTK runtime of the earlier Windows builds (the native app does not need it).
4. Unpacks the official llama.cpp Vulkan build (`$LlamaCppRelease`, the same release as `install.sh`) into
   `llama.cpp\`.
5. Creates `venv\` from that Python and installs the package with the `nvidia` extra (`onnxruntime-gpu` with the
   CUDA libraries from pip; no CUDA toolkit needed) or the `cpu` extra; PyGObject from the GTK version is removed.
   The package is built from a local copy, so it also works from a network path such as `\\wsl.localhost`.
6. Builds the Windows app: downloads the .NET SDK (`$DotnetSdkVersion`, with Microsoft's `dotnet-install.ps1`; on
   every run, since it is not kept) into the temporary `downloads\` folder and runs
   `dotnet publish winui\Laiaudio.csproj` into `app\` (self-contained, with the Windows App SDK). .NET telemetry is off, and the SDK, the NuGet packages and its build servers stay in
   `downloads\`, which is deleted at the end (~2 GB unpacked; the app itself is ~215 MB).
7. Creates the Start menu and desktop shortcuts (`app\Laiaudio.exe`) and the uninstall entry in Settings > Apps,
   which runs the copy of `uninstall.ps1` kept in the data folder.

The app starts `venv\Scripts\python.exe -m laiaudio.service` itself (see `docs/architecture/windows.md`); the
service writes its output to `app.log`.

Tested on Windows 11 Pro (build 26300) with an RTX 2060 SUPER: updating an install of the GTK version (68 s with
the SDK download), an update run, the app from the Start menu shortcut, recording, translation and the floating
captions. Running it again while the app is open closes the app first.

## Files

| What | Where |
| --- | --- |
| Transcripts | `~/Documents/Laiaudio/` (configurable) |
| Settings | `~/.config/laiaudio/config.json` |
| Models | `~/.local/share/laiaudio/models/` |
| Python environment | `~/.local/share/laiaudio/venv/` |
| Log | `~/.cache/laiaudio/app.log` |

On Windows:

| What | Where |
| --- | --- |
| Transcripts | `Documents\Laiaudio\` (configurable; follows a Documents folder moved to OneDrive) |
| Settings | `%APPDATA%\Laiaudio\config.json` |
| The app, Python, llama.cpp, venv | `%LOCALAPPDATA%\Laiaudio\` (`app`, `python`, `llama.cpp`, `venv`) |
| Models | `%LOCALAPPDATA%\Laiaudio\models\` |
| Log | `%LOCALAPPDATA%\Laiaudio\app.log` |
| Shortcuts | Start menu and desktop (`Laiaudio.lnk`) |

## uninstall.sh

Removes the venv, launcher, desktop entry and icon, and asks before deleting models and settings. Transcripts are
never deleted.

## uninstall.ps1

Settings > Apps runs it. It stops the app, removes the app, Python, llama.cpp and venv folders (and `gtk` from the
GTK version), the shortcuts and the Apps entry, and asks before deleting models and settings. Transcripts are never
deleted.
