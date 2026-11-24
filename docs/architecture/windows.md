# The Windows app

On Windows 11 the interface is a native WinUI 3 app (`winui/`, C#). The engine is the same Python code as on Linux,
run without any UI by `laiaudio/service.py`. The Linux app (`app.py`, `ui/`, GTK 4 and libadwaita) is not used on
Windows.

Why: GTK 4 on Windows draws its own window and controls, so it never feels like a Windows app. In GTK 4.22 it also
renders on the CPU (its GPU renderers need DirectComposition, which is off by default), and its text has no
ClearType. With WinUI, Windows draws the window, the title bar buttons and every control.

## Processes

```
Laiaudio.exe (WinUI 3)  ── stdin: commands ─▶  python -m laiaudio.service  ──▶ llama-server (translation AI)
   window, captions,     ◀─ stdout: events ──   audio, Parakeet, translators,
   meetings (.md files)                         downloads, config.json, hardware rules
```

- `Engine.cs` starts `%LOCALAPPDATA%\Laiaudio\venv\Scripts\python.exe -m laiaudio.service` with no console window
  and puts it in a job object (`KILL_ON_JOB_CLOSE`), so it dies with the app even if the app crashes. llama-server is
  in the service's own job and in the app's.
- One JSON object per line, UTF-8. Events reach the UI thread through the `DispatcherQueue`.
- The service writes everything it prints (and what its libraries print) to `app.log`; stdout carries only the
  protocol.
- Closing the window sends `quit`: the service saves the meeting that is being recorded, stops llama-server and
  exits, and then the window closes (after 30 s it closes anyway).

## Protocol

Commands (`{"cmd": ...}`, UI → service):

| Command | Fields | What the service does |
| --- | --- | --- |
| `hello` | | Sends `state`. |
| `start`, `stop` | | Starts or stops recording (same rules as `App.start_recording` / `stop_recording`). |
| `translation` | `active` | Turns ES on or off (`App.set_translation_active`). |
| `translate_turn` | `id`, `text` | Translates part of a live turn; the answer is a `turn_translation` event. |
| `assist`, `assist_close` | `text` | Text translator: run a request, or free the AI when the page closes. |
| `pick_model` | `kind`, `id` | Chooses a model; refuses one that does not fit (`hardware.problem`). |
| `use_recommended` | | Chooses the recommended combination. |
| `download`, `cancel_download`, `delete_model`, `download_translation` | `id` | Model files. |
| `set` | `key`, `value` | Saves a setting from `config.DEFAULTS`. |
| `devices` | | Sends the audio outputs and inputs. |
| `quit` | | Saves a recording in progress, then exits. |

Events (`{"event": ...}`, service → UI): `state` (settings, hardware, models with what fits, the engine, the text
translator's model), `engine` (`loading`, `ready`, `missing`, `error`), `recording` (`started`, `saving`, `saved`),
`partial`, `committed`, `turn_translation`, `translation`, `download`, `assist_status`, `assist_done`, `devices` and
`toast` (a message, with an optional button whose `action` is a command for the service or `{"ui": "settings"}` /
`{"ui": "open"}` for the window).

## Where each rule lives

| Rule | Where |
| --- | --- |
| Recording lifecycle, engine, translators, downloads, what fits the hardware, settings | Python (`service.py` and the modules it shares with Linux). The UI never decides these. |
| Live transcript blocks, sentence splitting for translation, page stack and covers, header title, sidebar | `MainWindow.cs`, `LiveView.cs` (ports of `main_window.py`, `workspace.py` and `live_view.py`). |
| Saved meetings: list, title, rename, preview, Recycle Bin | `Meetings.cs`, `MeetingView.cs` (ports of `meeting_view.py`). |
| Floating captions: fixed lines, never shrinking mid-sentence, placement, click-through | `CaptionsWindow.cs` (port of `ui/overlay.py`). |
| Text translator direction label | `TranslatorView.cs` (port of `translate.looks_spanish`). |

When a rule changes in a Python UI module, change its C# port too.

## Native look

- The header lives in Windows' title bar (`ExtendsContentIntoTitleBar`): minimize, maximize and close are Windows'
  own, with Snap Layouts. The empty parts of the header and the sidebar brand move the window
  (`InputNonClientPointerSource`).
- Native controls with the Paolium palette (`App.xaml`, `Palette.cs`): `SplitView` sidebar, `ListView`,
  `AutoSuggestBox`, `SelectorBar` tabs, settings cards like Windows Settings, `ToggleSwitch`, `ComboBox`, `NumberBox`,
  `ContentDialog`, `InfoBar` notices, `ProgressBar` and `ProgressRing`. Primary buttons use Sapphire with white text
  (`Ui.Primary`), as on Linux; Windows' accent in dark mode would be the lighter blue with dark text.
- The floating captions are a WinUI window with Win32 styles: topmost, tool window (out of the taskbar and Alt+Tab),
  never activated, layered (~90 % opaque) and click-through (`WS_EX_TRANSPARENT`) except over the drag handle. A press
  there is read with `GetAsyncKeyState`, because Windows swallows clicks on a window that never takes the focus, and
  hands the drag to Windows (`WM_NCLBUTTONDOWN` on the caption).
- Screens are named after the monitor (`DisplayConfigGetDeviceInfo`, for example "M27Q"), as the GTK app did, so
  saved settings keep working.

## Building

`install.ps1` downloads the .NET SDK into its temporary folder, runs `dotnet publish` (self-contained, Windows App
SDK included) into `%LOCALAPPDATA%\Laiaudio\app` and deletes the SDK. The project needs `EnableMsixTooling` even
though it is unpackaged: without it, publish leaves out `resources.pri` and the app closes on start.

Verified on Windows 11 (RTX 2060 SUPER, 2560×1440 at 100 %): updating a GTK install (the .NET SDK downloaded from
scratch, the GTK runtime removed), all pages, recording with the live transcript, the Spanish column and the floating
captions, the text translator, rename and delete, search, closing while recording (the meeting is saved) and no
process left behind after closing. Not verified yet: a machine without Laiaudio, other display scales, dragging the
floating captions.
