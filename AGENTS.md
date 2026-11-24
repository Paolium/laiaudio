# Laiaudio engineering rules

Repository-wide contract for any AI assistant or contributor. Read it before touching code. A more specific
`AGENTS.md` in a subdirectory overrides this file for that scope.

## Quick context

- Product: live meeting captions for Linux desktops and Windows 11, with optional Spanish translation and Markdown
  transcripts.
- Promise: everything runs locally; no account, no cloud, no telemetry.
- Platform: Arch Linux / Omarchy with PipeWire audio, and Windows 11 (x64) with
  WASAPI audio. Floating captions use layer-shell where the compositor supports it (Hyprland, Sway, KDE), an
  always-on-top X11 window on GNOME and X11 desktops (`desktop.py`), and a topmost window of the native app on
  Windows.
- One engine, two interfaces: the Python engine (audio, recognition, translation, models, settings and hardware
  rules) is shared. Linux uses the GTK app (`app.py`, `ui/`); Windows uses a native WinUI 3 app (`winui/`, C#) that
  drives the engine through `service.py` (see `docs/architecture/windows.md`). Windows-only Python lives in
  `windows.py` (Win32) and `wasapi.py` (audio) and is reached through `desktop.WINDOWS` checks.
- App: Python 3.11+, GTK 4.16+ and libadwaita 1.6+ (PyGObject); gtk4-layer-shell or python-xlib for the overlay.
  On Windows: Python 3.14 (private to the app) and WinUI 3 (Windows App SDK 1.8, .NET 10), self-contained.
- Speech recognition: NVIDIA Parakeet TDT 0.6B v2 through onnx-asr and ONNX Runtime (CUDA or CPU).
- Translation: Qwen3 4B / Gemma 3 4B through llama.cpp (`llama-server`, Vulkan) or Marian through CTranslate2.
- Distribution: `install.sh` on Arch (pacman + a Python venv) and `install.ps1` / `install.cmd` on Windows (no admin
  rights; private Python and venv, and the app built with a temporary .NET SDK); models are downloaded from inside
  the app.
- Repository: `github.com/Paolium/laiaudio`, MIT license, branch `main`.

## Required reading

Read only the documents relevant to the change, starting with `README.md`:

- `README.md`: public entry point: what the app does, install, usage and hardware table.
- `docs/product.md`: product scope, users, principles and non-goals.
- `docs/architecture/system.md`: components, threads and data flow from audio to captions.
- `docs/architecture/app.md`: module map, UI structure, state and the rules each module follows.
- `docs/architecture/windows.md`: the native Windows app, its engine process and the protocol between them.
- `docs/models.md`: model catalog, hardware detection, VRAM budget and the measurements behind them.
- `docs/design.md`: visual design system: palette, typography, components and states.
- `docs/branding.md`: Paolium brand assets and how Laiaudio uses them.
- `docs/development/workflow.md`: how to run, test and verify changes.
- `docs/deployment/install.md`: installer, update path, migrations and file locations.

The source code is the final authority on current behavior. Do not invent product rules, external configuration
or behavior that is not there. If a requirement does not fit an existing pattern, ask for a decision before
implementing it.

## General rules

- Code, comments, UI copy and documentation in clear B2 English. The Spanish translation column is the only
  Spanish in the product.
- Every class and function has a single responsibility.
- Prefer the smallest change that solves the requirement.
- Follow a nearby working feature before creating a new abstraction.
- Do not add abstractions without a concrete reuse or maintenance benefit.
- Never send audio or text off the machine. A feature that needs the network (other than downloading models)
  needs an explicit product decision first.
- Never block the GTK main thread: audio capture, inference, downloads and translation run on worker threads and
  report back with `GLib.idle_add`.
- Never change a widget's own model or selection inside its own change notification; defer it with
  `GLib.idle_add` (see `docs/architecture/app.md`).
- Every model change must respect `hardware.py`: a combination that does not fit the machine must not be
  selectable.
- Every change must keep working on Linux and Windows. Put Win32 or WASAPI code in `windows.py` or `wasapi.py`, never
  in UI modules; console programs started on Windows use `desktop.NO_CONSOLE`.
- A rule of the interface (what a page shows, when a button is enabled, how the captions wrap) exists twice: in
  `ui/` and in its C# port in `winui/`. Change both. Rules of the engine live only in Python, and the Windows app
  never decides them (it asks `service.py`).
- On Windows use native WinUI controls with the Paolium palette; do not draw controls that Windows already provides.
- Do not put secrets in source code, documentation or committed files.
- Do not use emojis in code, comments, documentation headings or commit messages.
- An AI assistant never runs `git commit`, `git push` or any other git operation that changes history or the
  remote, unless the human operator explicitly asks for it in the current conversation.

## Release facts

- Repository: `https://github.com/Paolium/laiaudio` (public, branch `main`).
- App id: `com.paolium.Laiaudio`.
- Launcher: `~/.local/bin/laiaudio`; desktop entry `laiaudio.desktop`; icon `laiaudio.svg`.
- Data: `~/.local/share/laiaudio/` (venv and models), `~/.config/laiaudio/config.json`, `~/.cache/laiaudio/app.log`.
- Default transcript folder: `~/Documents/Laiaudio/`.
- Windows: `%LOCALAPPDATA%\Laiaudio\` (`app\Laiaudio.exe`, Python, venv, llama.cpp, models and `app.log`),
  `%APPDATA%\Laiaudio\config.json`, Start menu and desktop shortcuts, and an entry in Settings > Apps.
- Brand site: `https://paolium.web.app/`.

## AI workflow and verification

1. Read `README.md`, this file and the relevant architecture document.
2. Inspect the current implementation and a nearby working feature.
3. Review the worktree before editing.
4. Implement the smallest change that follows the established pattern.
5. Byte-compile the package and run the app (see `docs/development/workflow.md`); measure latency when touching
   `asr.py` or `translate.py`.
6. Confirm that no secret, generated artifact or unrelated file changed.
7. Update the relevant documentation when stable behavior or configuration changes.
8. Report limitations and missing automated coverage.

If a requirement cannot be implemented with these rules, stop and ask for a decision instead of creating a new
pattern.
