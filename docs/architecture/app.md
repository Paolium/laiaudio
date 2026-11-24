# Application architecture

## Module map

On Windows the interface is the native app in `winui/` and the engine runs as `service.py`: see
[windows.md](windows.md). Everything below `ui/` and `app.py` is the Linux interface.

```
laiaudio/
  __init__.py        app name, id, version and brand links
  __main__.py        entry point (python -m laiaudio)
  app.py             Adw.Application (Linux): wiring, recording lifecycle, CSS
  service.py         Windows: the same engine without a UI, driven by the WinUI app (JSON lines on stdin/stdout)
  mainloop.py        idle_add: GLib in the GTK app, a plain queue in the service
  paths.py           XDG paths, or AppData on Windows (LAIAUDIO_MODELS overrides the models folder for testing)
  desktop.py         WINDOWS and NO_CONSOLE; picks the overlay backend (layer-shell or X11) before GTK starts
  windows.py         Windows only: the Documents folder and the job object that ties llama-server to the engine
  wasapi.py          Windows only: audio devices and capture through WASAPI (COM with ctypes)
  config.py          settings in config.json, first-run recommendation, hardware fix-ups
  audio.py           audio sources and Capture (PipeWire on Linux, WASAPI on Windows)
  asr.py             Engine and Stream (speech recognition)
  translate.py       Translator and its backends (llama-server, Marian)
  transcript.py      Markdown writer
  models.py          model catalog and downloader
  hardware.py        GPU detection, VRAM budget, recommendations
  ui/
    main_window.py   window, sidebar, header and footer
    workspace.py     content stack: status, live transcript, saved meeting and translator pages
    live_view.py     live transcript (one block per turn, optional Spanish column)
    meeting_view.py  saved meeting viewer (preview / Markdown) and its actions
    overlay.py       floating caption bar: shared text logic + LayerShellOverlay and X11Overlay
    settings.py      settings page with its tabs in a centered pill bar
    translator_view.py text translator page (Spanish → B2 English, English → Spanish)
    model_card.py    model card with download, progress and delete
    widgets.py       StateToggle (colored icon on, slashed icon off) and icon_button
  data/
    paolium-logo.svg app icon and sidebar logo
    laiaudio.ico     Windows app icon
winui/               the Windows app (WinUI 3, C#): see windows.md
```

## UI structure

- **Sidebar** (collapsible `Adw.OverlaySplitView`): the Paolium logo with the app name right below it, search, the "Translator" row with a dot that is sapphire while
  the translator is open, the "Live" row with the recording dot, saved meetings (deleted from the meeting's
  own action bar), and a sticky Settings button.
- **Header**: sidebar toggle, Start/Stop and the only page title ("Translator", "Settings", the open meeting's
  title, the timer while recording on the live page, or "New meeting").
- **Live bar**: shown only on the live page (status or transcript): a pill group with three `StateToggle`s:
  microphone (ruby), floating captions and ES (sapphire). Leaving a finished, saved recording clears the live
  transcript, so "Live" starts again from "Ready".
- **Workspace** (`Workspace`, a `Gtk.Stack`): a status page (loading, missing model, ready), the live
  `TranscriptView`, the `MeetingView`, the `TranslatorView` and the `SettingsView` (tabs, rebuilt on every open).
  The translator and settings cover the other pages: background changes update the page behind them, and closing
  them (Start or a sidebar row) returns there.
  It frees the shared LLM when it closes.
- **Footer**: "Designed by Paolium." (no logo; the logo lives in the sidebar).

## Rules

- `app.py` (and `service.py` on Windows) owns the recording lifecycle and is the only place that starts or stops
  streams.
- Stream events (`partial`, `committed`) arrive on worker threads and must hop to the main thread with
  `GLib.idle_add` before touching widgets.
- Never change a widget's model or selection inside its own `notify` handler: GTK notifies again and creates an
  endless loop. Defer it with `GLib.idle_add` (see `SettingsView.on_pick`).
- Never move a layer-shell surface to another monitor while a pointer grab is active: the compositor recreates the
  surface and GTK spins. The overlay moves within its screen while dragging and jumps on drop.

## Floating captions per desktop

`desktop.overlay_backend()` decides once, before GTK starts (`LAIAUDIO_OVERLAY=layer-shell|x11` overrides it on
Linux). `X11Overlay` is a `WindowOverlay`: a normal undecorated window that the window manager moves, whose position
is read back and saved as `{"x", "y"}`. On Windows the WinUI app draws the captions (`CaptionsWindow.cs`).

| Session | Backend | How it is placed and moved |
| --- | --- | --- |
| Hyprland, Sway, KDE Plasma, other wlroots compositors | `LayerShellOverlay` | Layer-shell margins; drag follows the Hyprland cursor and jumps to another screen on drop. |
| GNOME, Cinnamon and any X11 session | `X11Overlay` | The whole app runs on the X11 backend (XWayland on GNOME). Undecorated utility window marked above, sticky and out of the taskbar; positioned with `USPosition` and `_NET_MOVERESIZE_WINDOW`, dragged by the window manager (`begin_move`) and its position read back and saved. |

Both share the text logic. The click-through comes from the input region: only the drag handle receives clicks.
Verified under Mutter 46 (GNOME): starts centered at the bottom, drags with the mouse and remembers the position.
- The floating bar uses fixed-width lines and never shrinks mid-sentence; it accepts corrections of equal or
  greater length only.
- Models are selected only through `SettingsView`, which consults `hardware.problem()`; `config.fit_to_hardware()`
  fixes saved combinations at startup.
