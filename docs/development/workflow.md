# Development workflow

## Before coding

1. Read `AGENTS.md` and the relevant document in `docs/`.
2. Check the worktree with `git status`.

## Running from the repository

The installed app lives in `~/.local/share/laiaudio/venv`. To try local changes, reinstall the package into it:

```bash
~/.local/share/laiaudio/venv/bin/pip install --no-deps --force-reinstall .
laiaudio
```

Or run straight from the source tree with the same interpreter:

```bash
LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so ~/.local/share/laiaudio/venv/bin/python -m laiaudio
```

`LD_PRELOAD` is required by gtk4-layer-shell. Set `LAIAUDIO_MODELS=<empty folder>` to see the first-run flow.

### On Windows

Run `install.cmd` once. To try a change, run it again: it rebuilds the app and reinstalls the package (about a
minute). For quicker rounds, keep a .NET 10 SDK and build the app yourself, pointing it at the repository's Python:

```powershell
dotnet build winui\Laiaudio.csproj -c Release -p:Platform=x64
$env:LAIAUDIO_SOURCE = (Get-Location).Path   # the service imports laiaudio from here instead of the venv
& "winui\bin\x64\Release\net10.0-windows10.0.22621.0\win-x64\Laiaudio.exe"
```

`LAIAUDIO_PYTHON` points the app at another interpreter (the default is the installed venv). Build from a local
folder: from `\\wsl.localhost\...` the build is slow; copy `winui\` and `laiaudio\data\` to a Windows folder first.
Close the app before building, or the build cannot replace `Laiaudio.exe`. The service's output goes to `app.log`.

The app's pages and buttons expose their names to UI Automation (`AutomationProperties.Name`), so they can be driven
from PowerShell (`System.Windows.Automation`) for end-to-end checks.

## Verification

- Byte-compile everything: `~/.local/share/laiaudio/venv/bin/python -m py_compile laiaudio/*.py laiaudio/ui/*.py`.
- Check the log: `~/.cache/laiaudio/app.log` (Windows: `%LOCALAPPDATA%\Laiaudio\app.log`).
- When touching `desktop.py`, `windows.py`, `wasapi.py`, `audio.py`, `service.py`, `overlay.py` or the installers, try
  both systems: Windows code must never run on Linux (check `desktop.WINDOWS`) and the reverse.
- When touching `ui/`, check whether its C# port in `winui/` needs the same change (and the reverse).
- Windows app: the build must finish without warnings.
- When touching `asr.py` or `translate.py`, measure latency with continuous speech (median word latency and audio
  staleness) and compare with `docs/models.md`.
- When touching the GPU path, check `nvidia-smi` (VRAM and BAR1) while a video plays in the browser.
- There is no automated test suite yet; report what was verified by hand.
