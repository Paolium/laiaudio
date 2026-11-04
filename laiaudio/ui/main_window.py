"""Main window: saved meetings on the left and the live transcript on the right."""
import re
import subprocess
from datetime import datetime

from gi.repository import Adw, Gdk, GLib, GObject, Gtk

from .. import APP_NAME, LOGO, PAOLIUM_URL
from ..config import config
from ..transcript import MAX_PARAGRAPH
from .meeting_view import MeetingView, confirm_delete, meeting_title
from .model_card import ModelCard
from .widgets import StateToggle

MEETING, ME = "Meeting", "Me"
SENTENCE_END = re.compile(r"[.?!](?=\s|$)")


class Turn:
    """One speaker turn: English on the left and, when enabled, Spanish on the right."""

    def __init__(self, speaker, start):
        css = "speaker-meeting" if speaker == MEETING else "speaker-me"
        self.widget = Gtk.Grid(column_spacing=32, row_spacing=4, column_homogeneous=True)
        self.widget.attach(Gtk.Label(label=f"{datetime.fromtimestamp(start):%H:%M:%S}  ·  {speaker}",
                                     xalign=0, css_classes=["turn-header", css]), 0, 0, 1, 1)
        self.en = Gtk.Label(xalign=0, yalign=0, wrap=True, selectable=True, css_classes=["turn-text"])
        self.es = Gtk.Label(xalign=0, yalign=0, wrap=True, selectable=True, css_classes=["turn-es"])
        self.widget.attach(self.en, 0, 1, 1, 1)
        self.widget.attach(self.es, 1, 1, 1, 1)
        self.text = ""
        self.sent = 0  # characters of self.text already sent for translation

    def append(self, text):
        self.text = f"{self.text} {text}".strip()
        self.en.set_text(self.text)

    def untranslated(self, final):
        """Return the complete sentences not translated yet (or everything left when the turn closed)."""
        rest = self.text[self.sent:]
        cut = len(rest) if final else max((m.end() for m in SENTENCE_END.finditer(rest)), default=0)
        self.sent += cut
        return rest[:cut].strip()

    def add_translation(self, text):
        self.es.set_text(f"{self.es.get_text()} {text}".strip())
        return False


class TranscriptView(Gtk.ScrolledWindow):
    """Live transcript: one block per turn and, at the bottom, what is being said right now."""

    def __init__(self):
        super().__init__(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.done_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.live_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                         margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        column.append(self.done_box)
        column.append(self.live_box)
        self.clamp = Adw.Clamp(maximum_size=900, child=column)
        self.set_child(self.clamp)
        self.turns = []
        self.open_turns = {}  # speaker -> open Turn
        self.live_labels = {}
        self.translator = None  # Translator while translation is on

    def clear(self):
        for box in (self.done_box, self.live_box):
            while child := box.get_first_child():
                box.remove(child)
        self.turns.clear()
        self.open_turns.clear()
        self.live_labels.clear()

    def is_empty(self):
        return self.done_box.get_first_child() is None

    def set_translator(self, translator):
        self.translator = translator
        self.clamp.set_maximum_size(1600 if translator else 900)
        for turn in self.turns:
            turn.es.set_visible(bool(translator))
            self.translate(turn, final=turn not in self.open_turns.values())

    def translate(self, turn, final):
        if self.translator and (text := turn.untranslated(final)):
            self.translator.translate(text, turn.add_translation)

    def add_committed(self, speaker, start, text, end_of_turn):
        turn = self.open_turns.get(speaker)
        if turn is None and text:
            turn = self.new_turn(speaker, start)
            self.open_turns[speaker] = turn
        if text:
            turn.append(text)
        if turn and (end_of_turn or len(turn.text) > MAX_PARAGRAPH):
            self.open_turns.pop(speaker, None)
            self.translate(turn, final=True)
        elif turn:
            self.translate(turn, final=False)
        self.scroll_to_end()

    def new_turn(self, speaker, start):
        turn = Turn(speaker, start)
        turn.es.set_visible(bool(self.translator))
        self.turns.append(turn)
        self.done_box.append(turn.widget)
        return turn

    def set_partial(self, speaker, text):
        label = self.live_labels.get(speaker)
        if label is None:
            label = Gtk.Label(xalign=0, wrap=True, css_classes=["live-text"])
            self.live_labels[speaker] = label
            self.live_box.append(label)
        label.set_text(f"{speaker}: {text}" if text else "")
        label.set_visible(bool(text))
        self.scroll_to_end()

    def scroll_to_end(self):
        def scroll():
            adj = self.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            return False
        GLib.idle_add(scroll)


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
        side_header = Adw.HeaderBar(title_widget=Adw.WindowTitle(title="Meetings"), show_end_title_buttons=False)
        sidebar = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=self.meetings, vexpand=True))
        sidebar.add_top_bar(side_header)
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
                                       icon="view-dual-symbolic")
        self.overlay_btn.connect("toggled", lambda b: app.set_overlay_enabled(b.get_active()))
        self.es_btn = StateToggle("toggle-es", "Translate into Spanish (right column)", False, label="ES")
        self.es_btn.connect("toggled", lambda b: app.set_translation_active(b.get_active()))
        self.timer = Gtk.Label(label=APP_NAME, css_classes=["timer"], use_markup=True)

        self.sidebar_btn = Gtk.ToggleButton(icon_name="sidebar-show-symbolic", active=config["sidebar_visible"],
                                            tooltip_text="Show or hide the meetings")

        header = Adw.HeaderBar(title_widget=self.timer)
        header.pack_start(self.sidebar_btn)
        header.pack_start(self.record_btn)
        for widget in (self.es_btn, self.overlay_btn, self.mic_btn):
            header.pack_end(widget)

        self.view = TranscriptView()
        self.status = Adw.StatusPage(icon_name="audio-input-microphone-symbolic")
        self.meeting_view = MeetingView(self)
        self.stack = Gtk.Stack()
        self.stack.add_named(self.status, "status")
        self.stack.add_named(self.view, "live")
        self.stack.add_named(self.meeting_view, "file")

        content = Adw.ToolbarView(content=self.stack)
        content.add_top_bar(header)
        content.add_bottom_bar(self.build_footer())
        self.toasts = Adw.ToastOverlay(child=content)

        # Collapsible meetings panel (button at the top left)
        split = Adw.OverlaySplitView(sidebar=sidebar, content=self.toasts, show_sidebar=config["sidebar_visible"],
                                     min_sidebar_width=260, max_sidebar_width=340)
        self.sidebar_btn.bind_property("active", split, "show-sidebar",
                                       GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        split.connect("notify::show-sidebar", lambda s, _p: config.set("sidebar_visible", s.get_show_sidebar()))
        split.connect("notify::show-sidebar", lambda s, _p: self.update_footer(s.get_show_sidebar()))
        self.update_footer(config["sidebar_visible"])
        self.set_content(split)
        self.connect("close-request", self.on_close)
        self.refresh_meetings()

    def build_footer(self):
        # Fixed-size Gtk.Image (a Gtk.Picture would grow to fill the space)
        self.footer_logo = Gtk.Image.new_from_paintable(Gdk.Texture.new_from_filename(str(LOGO)))
        self.footer_text = Gtk.Label(use_markup=True, css_classes=["footer-brand"],
                                     label=f"<span size='small'>Designed by</span>  <a href='{PAOLIUM_URL}'>"
                                           "<span weight='600'>Paolium</span></a><span foreground='#D69D00'>.</span>")
        box = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        box.append(self.footer_logo)
        box.append(self.footer_text)
        return Gtk.CenterBox(center_widget=box, css_classes=["app-footer"])

    def update_footer(self, expanded):
        """Panel open: logo + "Designed by Paolium."; panel closed: just the small logo."""
        self.footer_logo.set_pixel_size(20 if expanded else 14)
        self.footer_text.set_visible(expanded)

    # --- main page states ---
    def show_status(self, title, description="", child=None):
        self.status.set_title(title)
        self.status.set_description(description)
        self.status.set_child(child)
        self.stack.set_visible_child_name("status")

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
            self.stack.set_visible_child_name("live")

    # --- saved meetings ---
    def refresh_meetings(self):
        self.meetings.remove_all()
        live = Adw.ActionRow(title="Live", activatable=True, css_classes=["live-row"])
        self.live_dot = Gtk.Image(icon_name="media-record-symbolic", css_classes=["live-dot"])
        self.set_recording(self.app.recording)
        live.add_prefix(self.live_dot)
        live.path = None
        self.meetings.append(live)
        folder = config.meetings_dir
        for path in sorted(folder.glob("*.md"), reverse=True) if folder.exists() else []:
            text = path.read_text(encoding="utf-8")
            title = meeting_title(path)
            row = Adw.ActionRow(title=GLib.markup_escape_text(title), activatable=True, css_classes=["meeting-row"],
                                subtitle=self.preview(text), subtitle_lines=1)
            delete = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Delete",
                                valign=Gtk.Align.CENTER, css_classes=["flat", "row-delete"])
            delete.connect("clicked", lambda _b, p=path: confirm_delete(self, p, self.meeting_deleted))
            row.add_suffix(delete)
            row.path = path
            row.search_text = f"{title}\n{text}".lower()
            self.meetings.append(row)
        self.meetings.invalidate_filter()

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
        if row.path is None:
            self.show_live()
        else:
            self.meeting_view.load(row.path)
            self.stack.set_visible_child_name("file")

    def select_meeting(self, path):
        for i in range(1, 10_000):
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
        self.toast("Title updated")

    def meeting_deleted(self, path):
        self.refresh_meetings()
        if self.meeting_view.path == path:
            self.meetings.select_row(self.meetings.get_row_at_index(0))
            self.show_live()
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
