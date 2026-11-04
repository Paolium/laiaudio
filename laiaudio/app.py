"""Laiaudio: live (English) meeting transcription with optional Spanish translation."""
import signal
import sys
import threading
import time

from . import desktop

desktop.prepare()  # before GTK starts: GNOME and X11 sessions run the app on the X11 backend

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from . import APP_ID, audio  # noqa: E402
from .asr import Engine, Stream
from .config import config
from .models import BY_ID, Download
from .transcript import Transcript
from .translate import Translator, stop_leftover_servers
from .ui.live_view import ME, MEETING
from .ui.main_window import MainWindow
from .ui.overlay import create_overlay

CSS = """
/* Paolium dark palette (Depth, Base, Surface, Border, Text) with the Sapphire accent.
   Named colors for libadwaita 1.5 (Ubuntu 24.04) and CSS variables for libadwaita 1.6+. */
@define-color accent_bg_color #0D71FD;
@define-color accent_color #5C9DFE;
@define-color accent_fg_color #FFFFFF;
@define-color window_bg_color #141414;
@define-color window_fg_color #D6DAE0;
@define-color view_bg_color #141414;
@define-color view_fg_color #D6DAE0;
@define-color headerbar_bg_color #000000;
@define-color headerbar_fg_color #D6DAE0;
@define-color headerbar_backdrop_color #000000;
@define-color sidebar_bg_color #000000;
@define-color sidebar_fg_color #D6DAE0;
@define-color sidebar_backdrop_color #000000;
@define-color card_bg_color #2C2C2E;
@define-color card_fg_color #D6DAE0;
@define-color dialog_bg_color #141414;
@define-color dialog_fg_color #D6DAE0;
@define-color popover_bg_color #2C2C2E;
@define-color popover_fg_color #D6DAE0;
@define-color destructive_bg_color #FA4F67;
@define-color destructive_color #FA4F67;
@define-color error_color #FA4F67;
@define-color success_color #95D700;
@define-color warning_color #D69D00;
:root {
    --accent-bg-color: #0D71FD; --accent-color: #5C9DFE; --accent-fg-color: #FFFFFF;
    --window-bg-color: #141414; --window-fg-color: #D6DAE0;
    --view-bg-color: #141414; --view-fg-color: #D6DAE0;
    --headerbar-bg-color: #000000; --headerbar-fg-color: #D6DAE0; --headerbar-backdrop-color: #000000;
    --sidebar-bg-color: #000000; --sidebar-fg-color: #D6DAE0; --sidebar-backdrop-color: #000000;
    --card-bg-color: #2C2C2E; --card-fg-color: #D6DAE0;
    --dialog-bg-color: #141414; --dialog-fg-color: #D6DAE0;
    --popover-bg-color: #2C2C2E; --popover-fg-color: #D6DAE0;
    --border-color: #3A3A3C;
    --destructive-bg-color: #FA4F67; --destructive-color: #FA4F67; --error-color: #FA4F67;
    --success-color: #95D700; --warning-color: #D69D00;
}
.overlay-window { background: transparent; }
.captions {
    background: rgba(20, 20, 20, 0.88);
    border: 1px solid #3A3A3C;
    border-radius: 10px;
    padding: 10px 18px;
}
.captions label { font-family: monospace; color: #D6DAE0; }
.drag-handle { color: #4D4D52; min-width: 22px; margin-right: 12px; }
.drag-handle:hover { color: #D6DAE0; }
.turn-header { font-size: 0.85em; font-weight: bold; }
.speaker-meeting { color: #5C9DFE; }
.speaker-me { color: #95D700; }
.turn-es { font-size: 1.15em; color: alpha(#D6DAE0, 0.72); }
.turn-text { font-size: 1.15em; }
.live-text { font-size: 1.15em; opacity: 0.55; }
.timer { font-feature-settings: "tnum"; font-weight: bold; }
/* Depth frames the window (header, sidebar, footer); the page bars below the header sit on Base */
.main-header { background: #000000; box-shadow: none; }
.file-toolbar { padding: 8px 16px; background: #141414; }
.pill-bar {
    background: #141414;
    border: 1px solid #3A3A3C;
    border-radius: 999px;
    padding: 3px;
}
.pill-bar button { border-radius: 999px; min-height: 30px; padding: 0 12px; }
.pill-bar button:checked:not(.state-toggle) { background: alpha(#0D71FD, 0.22); color: #5C9DFE; font-weight: bold; }
.pill-actions button:hover { color: #5C9DFE; }
.pill-actions button.danger:hover { color: #FA4F67; }
/* On/off: only the icon or text changes color; off gets a diagonal slash */
.state-toggle, .state-toggle:checked, .state-toggle:hover, .state-toggle:checked:hover {
    background: none;
    box-shadow: none;
}
.state-toggle { color: alpha(currentColor, 0.55); }
.state-toggle:hover { color: currentColor; }
.state-label { font-weight: bold; }
.toggle-mic:checked { color: #FA4F67; }
.toggle-overlay:checked { color: #5C9DFE; }
.toggle-es:checked { color: #5C9DFE; }
.toggle-overlay:hover, .toggle-es:hover { color: #5C9DFE; }
/* when on: hovering makes them lighter and slightly bigger */
.state-toggle:checked:hover image { -gtk-icon-transform: scale(1.12); }
.toggle-mic:checked:hover { color: #FC8798; }
.toggle-overlay:checked:hover { color: #93BEFE; }
.toggle-es:checked:hover { color: #93BEFE; }

/* Meeting list */
.live-row:hover .live-dot { color: #FA4F67; }
.live-dot.recording { color: #FA4F67; animation: live-pulse 1.6s ease-in-out infinite; }
.translator-dot { color: alpha(currentColor, 0.45); }
.translator-row:hover .translator-dot { color: #5C9DFE; }
.translator-dot.inside, .translator-row:hover .translator-dot.inside { color: #5C9DFE; }
@keyframes live-pulse { 0% { opacity: 1; } 50% { opacity: 0.35; } 100% { opacity: 1; } }
.sidebar-settings { margin: 6px; }
/* Text translator */
.assistant-box { background: #000000; border: 1px solid #3A3A3C; border-radius: 10px; }
.assistant-box textview, .assistant-box text { background: transparent; color: #D6DAE0; }
.assistant-text { font-size: 1.05em; }
.assistant-direction { color: #5C9DFE; font-weight: bold; }
/* "Designed by Paolium" footer (like the one on paolium.web.app) */
.footer-brand link { color: #D6DAE0; text-decoration: none; }
.app-footer { padding: 6px 16px; border-top: 1px solid #3A3A3C; background: #000000; }
.footer-small { font-size: 0.8em; color: alpha(#D6DAE0, 0.6); }
.footer-brand { font-weight: 600; letter-spacing: -0.02em; color: #D6DAE0; }
.app-name { font-weight: 600; letter-spacing: -0.02em; }
.sidebar-brand { padding: 12px 0 10px; }
"""


def css_for_this_libadwaita(css):
    """libadwaita 1.6+ reads the palette from CSS variables; older GTK (Ubuntu 24.04) cannot parse :root."""
    if (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 6):
        return css
    start = css.index(":root {")
    return css[:start] + css[css.index("}", start) + 1:]


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.engine = None
        self.engine_pending = False  # the model changed while recording
        self.recording = False
        self.streams = []
        self.transcript = None
        self.started = 0.0
        self.win = self.overlay = None
        self._translator = None

    def do_activate(self):
        if self.win:
            self.win.present()
            return
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)  # Paolium dark palette
        css = Gtk.CssProvider()
        css.load_from_string(css_for_this_libadwaita(CSS))
        # Above the user theme (e.g. Omarchy) so the app colors are respected
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        self.win = MainWindow(self)
        self.overlay = create_overlay(self)
        self.win.present()
        stop_leftover_servers()  # from a previous session that did not close cleanly
        if config["translation_active"]:
            self.win.es_btn.set_active(True)  # after stop_leftover_servers, which would stop its llama-server
        if note := config.fit_to_hardware():
            GLib.timeout_add(800, lambda: self.win.toast(note))
        GLib.timeout_add(1000, self.tick)
        self.load_engine()

    def do_shutdown(self):
        if self._translator:
            self._translator.close()  # detiene llama-server
        Adw.Application.do_shutdown(self)

    # --- transcription engine ---
    def load_engine(self):
        model = BY_ID.get(config["asr_model"]) or BY_ID["parakeet-v2"]
        self.engine = None
        if not model.installed():
            self.win.show_missing_model(model)
            return
        self.win.show_loading(model)

        def load():
            try:
                engine = Engine(model, config["asr_device"])
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self.win.show_error, "No se pudo cargar el modelo", e)
                return
            GLib.idle_add(self.engine_ready, engine)

        threading.Thread(target=load, daemon=True).start()

    def engine_ready(self, engine):
        self.engine = engine
        self.win.show_live()
        if engine.slow:
            self.win.toast("Transcribing on the CPU: captions will lag slightly more")
        return False

    def engine_description(self):
        if not self.engine:
            return "The model is not loaded yet"
        return f"Now: {'CPU (slower)' if self.engine.slow else 'GPU'}"

    def models_changed(self, kind):
        """A model was chosen, downloaded or deleted in Settings (or on the welcome screen)."""
        if kind == "asr":
            if self.recording:
                self.engine_pending = True
                self.win.toast("The new model will load when recording stops")
            else:
                self.load_engine()
        elif self._translator:
            self._translator.reload()

    # --- translation ---
    def translator(self):
        """The translator is created the first time ES is turned on."""
        if self._translator is None:
            self._translator = Translator(lambda msg: GLib.idle_add(self.win.toast, msg))
            self._translator.start()
        return self._translator

    def set_translation_active(self, active):
        config.set("translation_active", active)  # turned off again below when it cannot start
        if not active:
            self.win.view.set_translator(None)
            if self._translator:
                self._translator.release()  # frees the GPU while ES is off
            return
        model = BY_ID.get(config["translation"])
        if model is None or model.engine == "none":
            self.win.toast("Choose a translation engine", "Settings", lambda: self.show_settings("translation"))
            self.win.es_btn.set_active(False)
        elif not model.installed():
            self.win.toast(f"{model.name} is not downloaded yet ({model.size_label})", "Download",
                           lambda: self.download_translation(model))
            self.win.es_btn.set_active(False)
        else:
            translator = self.translator()
            translator.reload()
            self.win.view.set_translator(translator)

    def download_translation(self, model):
        def done(_download, finished, error):
            if finished:
                self.win.toast(f"Download failed: {error}" if error else
                               f"{model.name} is ready: turn on ES to translate")
                self.models_changed("translation")
            return False

        Download.start_for(model).listen(done)
        self.win.toast(f"Downloading {model.name}… (progress in Settings → Translation)")

    # --- settings ---
    def show_settings(self, tab=None):
        self.win.workspace.open_settings(tab)

    def set_overlay_enabled(self, enabled):
        config.set("overlay_enabled", enabled)
        if self.win.overlay_btn.get_active() != enabled:
            self.win.overlay_btn.set_active(enabled)
        self.update_overlay()

    def set_use_mic(self, enabled):
        config.set("use_mic", enabled)
        if self.win.mic_btn.get_active() != enabled:
            self.win.mic_btn.set_active(enabled)

    # --- recording ---
    def toggle_recording(self):
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        meeting = audio.meeting_source(config["system_source"])
        if not meeting:
            self.win.toast("No audio output found (is PipeWire running?)")
            return
        self.recording = True
        self.started = time.time()
        self.transcript = Transcript(config.meetings_dir)
        self.win.view.clear()
        self.win.workspace.close_cover()
        self.win.meetings.select_row(self.win.live_row)
        self.win.workspace.show("live")
        self.win.record_btn.set_label("Stop")
        self.win.record_btn.set_css_classes(["destructive-action"])
        self.win.mic_btn.set_sensitive(False)
        self.win.set_recording(True)
        self.overlay.reset()
        self.update_overlay()

        system = Stream(MEETING, meeting, 0.004, self.engine, self)
        self.streams = [system]
        if config["use_mic"]:
            self.streams.append(Stream(ME, audio.mic_source(config["mic_source"]), 0.015, self.engine, self,
                                       gate=system))
        for s in self.streams:
            s.start()

    def stop_recording(self, quit_after=False):
        if not self.recording:
            return
        self.recording = False
        self.win.record_btn.set_sensitive(False)
        self.win.record_btn.set_label("Saving…")

        def finish():
            for s in self.streams:
                s.stop()
            for s in self.streams:
                s.join(timeout=10)
            path = self.transcript.close()
            GLib.idle_add(self.recording_saved, path, quit_after)

        threading.Thread(target=finish, daemon=True).start()

    def recording_saved(self, path, quit_after):
        self.streams = []
        self.win.record_btn.set_label("Start")
        self.win.record_btn.set_css_classes(["suggested-action"])
        self.win.record_btn.set_sensitive(True)
        self.win.mic_btn.set_sensitive(True)
        self.win.set_recording(False)
        self.win.update_title()
        self.update_overlay()
        self.win.refresh_meetings()
        self.win.meetings.select_row(self.win.live_row)
        if path:
            self.win.toast(f"Saved to {path.name}", "Open", lambda: self.win.open_path(path))
        else:
            self.win.toast("No speech detected; nothing was saved")
        if quit_after:
            self.quit()
        elif self.engine_pending:
            self.engine_pending = False
            self.load_engine()
        return False

    def tick(self):
        if self.recording:
            self.win.update_title()
        return True

    def update_overlay(self):
        self.overlay.wanted = self.recording and config["overlay_enabled"]
        self.overlay.render()

    # --- stream events (they arrive from other threads) ---
    def partial(self, speaker, text, stable):
        # Only stable words are shown: the rest still changes and is distracting
        GLib.idle_add(self._partial, speaker, stable)

    def _partial(self, speaker, stable):
        self.win.view.set_partial(speaker, stable)
        if speaker == MEETING:
            self.overlay.set_live(stable)
        return False

    def committed(self, speaker, start, text, end_of_turn):
        self.transcript.add(speaker, start, text, end_of_turn)
        GLib.idle_add(self._committed, speaker, start, text, end_of_turn)

    def _committed(self, speaker, start, text, end_of_turn):
        self.win.view.add_committed(speaker, start, text, end_of_turn)
        if speaker == MEETING and text:
            self.overlay.add_committed(text)
        return False

    def on_signal(self):
        if self.recording:
            self.stop_recording(quit_after=True)
        else:
            self.quit()
        return GLib.SOURCE_REMOVE


def add_signal_handler(sig, handler):
    """GLibUnix.signal_add on recent GLib; GLib.unix_signal_add on older ones (e.g. Ubuntu 24.04)."""
    try:
        from gi.repository import GLibUnix

        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, sig, handler)
    except (ImportError, AttributeError):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, handler)


def main():
    app = App()
    for sig in (signal.SIGINT, signal.SIGTERM):
        add_signal_handler(sig, app.on_signal)
    app.run(sys.argv[:1])
