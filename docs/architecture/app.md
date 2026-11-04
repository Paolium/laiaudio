# Application architecture

## Module map

```
laiaudio/
  __init__.py        app name, id, version and brand links
  __main__.py        entry point (python -m laiaudio)
  app.py             Adw.Application: wiring, recording lifecycle, CSS
  paths.py           XDG paths (LAIAUDIO_MODELS overrides the models folder for testing)
  config.py          settings in config.json, first-run recommendation, hardware fix-ups
  audio.py           PipeWire sources
  asr.py             Engine and Stream (speech recognition)
  translate.py       Translator and its backends (llama-server, Marian)
  transcript.py      Markdown writer
  models.py          model catalog and downloader
  hardware.py        GPU detection, VRAM budget, recommendations
  ui/
    main_window.py   window, sidebar, live transcript view, footer
    meeting_view.py  saved meeting viewer (preview / Markdown) and its actions
    overlay.py       floating caption bar (layer-shell)
    settings.py      tabbed settings dialog
    model_card.py    model card with download, progress and delete
    widgets.py       StateToggle (colored icon on, slashed icon off)
  data/
    paolium-logo.svg app icon and footer logo
```

## UI structure

- **Sidebar** (collapsible `Adw.OverlaySplitView`): search, the "Live" row with the recording dot, saved meetings
  with a delete button shown on hover, and a sticky Settings button.
- **Header**: sidebar toggle, Start/Stop, timer as the title, and three `StateToggle`s: ES (sapphire), floating
  captions (gold) and microphone (ruby).
- **Content stack**: a status page (loading, missing model, ready), the live `TranscriptView` and the
  `MeetingView`.
- **Footer**: the Paolium logo plus "Designed by Paolium." with the sidebar open; only the small logo with it closed.

## Rules

- `app.py` owns the recording lifecycle and is the only place that starts or stops streams.
- Stream events (`partial`, `committed`) arrive on worker threads and must hop to the main thread with
  `GLib.idle_add` before touching widgets.
- Never change a widget's model or selection inside its own `notify` handler: GTK notifies again and creates an
  endless loop. Defer it with `GLib.idle_add` (see `SettingsDialog.on_pick`).
- Never move a layer-shell surface to another monitor while a pointer grab is active: the compositor recreates the
  surface and GTK spins. The overlay moves within its screen while dragging and jumps on drop.
- The floating bar uses fixed-width lines and never shrinks mid-sentence; it accepts corrections of equal or
  greater length only.
- Models are selected only through `SettingsDialog`, which consults `hardware.problem()`; `config.fit_to_hardware()`
  fixes saved combinations at startup.
