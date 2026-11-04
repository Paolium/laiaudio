"""Main window: saved meetings on the left, the header, the workspace and the footer."""
import subprocess
import time

from gi.repository import Adw, Gdk, GLib, GObject, Gtk, Pango

from .. import APP_NAME, LOGO, PAOLIUM_URL
from ..config import config
from .meeting_view import meeting_title
from .model_card import ModelCard
from .widgets import StateToggle
from .workspace import Workspace


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME, default_width=1000, default_height=700)
        self.app = app

        # --- sidebar: search and saved meetings ---
        self.meetings = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.meetings.connect("row-activated", self.on_meeting_selected)
        self.meetings.set_filter_func(self.matches_search)
        self.search = Gtk.SearchEntry(placeholder_text="Search by title or content",
                                      margin_start=8, margin_end=8, margin_bottom=6)
        self.search.connect("search-changed", lambda *_: self.meetings.invalidate_filter())
        # Brand: logo on top, the app name right below; dragging it moves the window like a header bar
        # (fixed-size Gtk.Image: a Gtk.Picture would grow to fill the space)
        logo = Gtk.Image.new_from_paintable(Gdk.Texture.new_from_filename(str(LOGO)))
        logo.set_pixel_size(64)
        brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["sidebar-brand"])
        brand.append(logo)
        brand.append(Gtk.Label(label=APP_NAME, css_classes=["app-name"]))
        sidebar = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=self.meetings, vexpand=True))
        sidebar.add_top_bar(Gtk.WindowHandle(child=brand))
        sidebar.add_top_bar(self.search)
        settings_btn = Gtk.Button(child=Adw.ButtonContent(icon_name="emblem-system-symbolic", label="Settings"),
                                  css_classes=["flat", "sidebar-settings"])
        settings_btn.connect("clicked", lambda *_: app.show_settings())
        sidebar.add_bottom_bar(settings_btn)

        # --- content: live / saved meeting ---
        self.record_btn = Gtk.Button(label="Start", css_classes=["suggested-action"], sensitive=False)
        self.record_btn.connect("clicked", lambda *_: app.toggle_recording())
        self.mic_btn = StateToggle("toggle-mic", "Also transcribe your microphone", config["use_mic"],
                                   icon="audio-input-microphone-symbolic")
        self.mic_btn.connect("toggled", lambda b: config.set("use_mic", b.get_active()))
        self.overlay_btn = StateToggle("toggle-overlay", "Floating captions", config["overlay_enabled"],
                                       icon="media-view-subtitles-symbolic")
        self.overlay_btn.connect("toggled", lambda b: app.set_overlay_enabled(b.get_active()))
        self.es_btn = StateToggle("toggle-es", "Translate into Spanish (right column)", False, label="ES")
        self.es_btn.connect("toggled", lambda b: app.set_translation_active(b.get_active()))
        self.header_title = Gtk.Label(css_classes=["timer"], ellipsize=Pango.EllipsizeMode.END)

        self.sidebar_btn = Gtk.ToggleButton(icon_name="sidebar-show-symbolic", active=config["sidebar_visible"],
                                            tooltip_text="Show or hide the meetings")

        header = Adw.HeaderBar(title_widget=self.header_title, css_classes=["main-header"])
        header.pack_start(self.sidebar_btn)
        header.pack_start(self.record_btn)

        # Live-only toggles, grouped like the saved meeting actions; hidden on the other pages
        live_tools = Gtk.Box(css_classes=["pill-bar"])
        for widget in (self.mic_btn, self.overlay_btn, self.es_btn):
            live_tools.append(widget)
        self.live_bar = Gtk.CenterBox(css_classes=["file-toolbar"], end_widget=live_tools)

        self.workspace = Workspace(self)
        self.workspace.connect("notify::visible-child", lambda *_: self.on_page_changed())
        self.view, self.meeting_view = self.workspace.live, self.workspace.meeting

        content = Adw.ToolbarView(content=self.workspace)
        content.add_top_bar(header)
        content.add_top_bar(self.live_bar)
        content.add_bottom_bar(self.build_footer())
        self.toasts = Adw.ToastOverlay(child=content)

        # Collapsible meetings panel (button at the top left)
        split = Adw.OverlaySplitView(sidebar=sidebar, content=self.toasts, show_sidebar=config["sidebar_visible"],
                                     min_sidebar_width=260, max_sidebar_width=340)
        self.sidebar_btn.bind_property("active", split, "show-sidebar",
                                       GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        split.connect("notify::show-sidebar", lambda s, _p: config.set("sidebar_visible", s.get_show_sidebar()))
        self.set_content(split)
        self.connect("close-request", self.on_close)
        self.refresh_meetings()

    @staticmethod
    def build_footer():
        text = Gtk.Label(use_markup=True, css_classes=["footer-brand"],
                         label=f"<span size='small'>Designed by</span>  <a href='{PAOLIUM_URL}'>"
                               "<span weight='600'>Paolium</span></a><span foreground='#D69D00'>.</span>")
        return Gtk.CenterBox(center_widget=text, css_classes=["app-footer"])

    def update_title(self):
        """The header title follows the page: translator, settings, the open meeting, the timer while recording or
        "New meeting"."""
        page = self.workspace.get_visible_child_name()
        if page in ("translator", "settings"):
            self.header_title.set_text(page.capitalize())
        elif page == "file":
            self.header_title.set_text(meeting_title(self.meeting_view.path))
        elif self.app.recording:
            secs = int(time.time() - self.app.started)
            self.header_title.set_markup(f"<span foreground='#FA4F67'>●</span> "
                                         f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}")
        else:
            self.header_title.set_text("New meeting")

    # --- workspace pages ---
    def show_status(self, title, description="", child=None):
        self.workspace.show_status(title, description, child)

    def on_page_changed(self):
        """Title, the live bar and the translator row follow the page."""
        page = self.workspace.get_visible_child_name()
        self.update_title()
        self.live_bar.set_visible(page in ("status", "live"))
        if page != "live" and not (self.app.recording or self.app.streams) and not self.view.is_empty():
            self.reset_live()
        self.update_translator_row()

    def update_translator_row(self):
        """The translator dot turns sapphire while the translator is open; closing it selects the row behind."""
        if self.workspace.translator_open():
            self.translator_dot.add_css_class("inside")
            self.meetings.select_row(self.translator_row)
        else:
            self.translator_dot.remove_css_class("inside")
            if self.meetings.get_selected_row() is self.translator_row:
                self.select_meeting(self.meeting_view.path if self.workspace.behind == "file" else None)

    def reset_live(self):
        """Leaving a finished recording: it is already saved, so "Live" starts again from "Ready"."""
        self.view.clear()
        if self.workspace.cover_open():
            self.show_live()  # updates the page behind the translator or settings

    def show_loading(self, model):
        self.record_btn.set_sensitive(False)
        self.show_status("Loading model…", GLib.markup_escape_text(f"{model.name} is getting ready"))

    def show_missing_model(self, model):
        """First run (or deleted model): offer the download."""
        self.record_btn.set_sensitive(False)
        card = ModelCard(on_change=lambda m: self.app.models_changed("asr"))
        card.set_model(model)
        cards = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        cards.append(card)
        other = Gtk.Button(label="Choose another model", halign=Gtk.Align.CENTER, css_classes=["flat"])
        other.connect("clicked", lambda *_: self.app.show_settings("transcription"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(Adw.Clamp(maximum_size=640, child=cards))
        box.append(other)
        self.show_status("The transcription model is missing",
                         "Download it once; after that everything works offline.", box)

    def show_error(self, title, error):
        self.record_btn.set_sensitive(False)
        self.show_status(title, GLib.markup_escape_text(str(error)))

    def show_live(self):
        empty = self.view.is_empty() and not self.app.recording
        if empty and self.app.engine:
            self.record_btn.set_sensitive(True)
            self.show_status("Ready", "Press <b>Start</b> when the meeting begins")
        elif not empty:
            self.workspace.show("live")

    # --- saved meetings ---
    def refresh_meetings(self):
        self.meetings.remove_all()
        self.translator_row = Adw.ActionRow(title="Translator", activatable=True, css_classes=["translator-row"],
                                            tooltip_text="Spanish → clear English, English → Spanish")
        self.translator_dot = Gtk.Image(icon_name="media-record-symbolic", css_classes=["translator-dot"])
        self.translator_row.add_prefix(self.translator_dot)
        self.translator_row.path = None
        self.meetings.append(self.translator_row)
        live = Adw.ActionRow(title="Live", activatable=True, css_classes=["live-row"])
        self.live_dot = Gtk.Image(icon_name="media-record-symbolic", css_classes=["live-dot"])
        self.set_recording(self.app.recording)
        live.add_prefix(self.live_dot)
        live.path = None
        self.live_row = live
        self.meetings.append(live)
        folder = config.meetings_dir
        for path in sorted(folder.glob("*.md"), reverse=True) if folder.exists() else []:
            text = path.read_text(encoding="utf-8")
            title = meeting_title(path)
            row = Adw.ActionRow(title=GLib.markup_escape_text(title), activatable=True, css_classes=["meeting-row"],
                                subtitle=self.preview(text), subtitle_lines=1)
            row.path = path
            row.search_text = f"{title}\n{text}".lower()
            self.meetings.append(row)
        self.meetings.invalidate_filter()
        self.update_translator_row()  # the rows are new: restore the dot and the selection

    @staticmethod
    def preview(text):
        for line in text.splitlines():
            if line.startswith("**["):
                return GLib.markup_escape_text(line.split(":**", 1)[-1].strip()[:80])
        return ""

    def set_recording(self, recording):
        """The "Live" dot turns red and pulses softly while recording."""
        if recording:
            self.live_dot.add_css_class("recording")
        else:
            self.live_dot.remove_css_class("recording")

    def matches_search(self, row):
        query = self.search.get_text().strip().lower()
        return not query or row.path is None or all(word in row.search_text for word in query.split())

    def on_meeting_selected(self, _box, row):
        if row is self.translator_row:
            self.workspace.open_translator()
            return
        self.workspace.close_cover()  # picking a meeting leaves the translator or settings
        if row.path is None:
            self.show_live()
        else:
            self.meeting_view.load(row.path)
            self.workspace.show("file")

    def select_meeting(self, path):
        """Select a saved meeting's row; None selects "Live"."""
        if path is None:
            self.meetings.select_row(self.live_row)
            return
        for i in range(2, 10_000):
            row = self.meetings.get_row_at_index(i)
            if row is None:
                return
            if row.path == path:
                self.meetings.select_row(row)
                return

    def meeting_changed(self, path):
        """Renamed: refresh the list and the view without losing the selection."""
        self.refresh_meetings()
        self.select_meeting(path)
        if self.meeting_view.path == path:
            self.meeting_view.load(path)
            self.update_title()
        self.toast("Title updated")

    def meeting_deleted(self, path):
        if self.meeting_view.path == path:
            # Leave the deleted meeting first: its page and the header title read the file
            self.meeting_view.path = None
            self.show_live()
            if self.workspace.get_visible_child_name() == "file":
                self.workspace.show("status")  # the model is still loading: show its status instead
        self.refresh_meetings()
        if self.meeting_view.path is None:
            self.meetings.select_row(self.live_row)
        self.toast("Meeting moved to the trash")

    def toast(self, text, button=None, action=None):
        toast = Adw.Toast(title=GLib.markup_escape_text(text), timeout=6)
        if button:
            toast.set_button_label(button)
            toast.connect("button-clicked", lambda *_: action())
        self.toasts.add_toast(toast)
        return False

    @staticmethod
    def open_path(path):
        if path.suffix != ".md":
            path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(path)])

    def on_close(self, *_):
        if self.app.recording:
            self.app.stop_recording(quit_after=True)
            return True  # closes once saving finishes
        self.app.quit()  # the floating bar would keep the app alive
        return False
