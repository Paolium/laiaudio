"""Workspace: the area next to the sidebar, showing one page at a time."""
from gi.repository import Adw, Gtk

from .live_view import TranscriptView
from .meeting_view import MeetingView
from .settings import SettingsView
from .translator_view import TranslatorView

TRANSLATOR, SETTINGS = "translator", "settings"
COVERS = (TRANSLATOR, SETTINGS)  # pages that sit on top of the others


class Workspace(Gtk.Stack):
    """Pages: status (loading, missing model, ready), live transcript, saved meeting, translator and settings.

    The translator and settings cover the others: while one is open, background changes (a model finished
    loading, a meeting was deleted) update the page behind it, and closing it returns there.
    """

    def __init__(self, window):
        super().__init__(vexpand=True)
        self.status = Adw.StatusPage(icon_name="audio-input-microphone-symbolic")
        self.live = TranscriptView()
        self.meeting = MeetingView(window)
        self.translator = TranslatorView()
        self.settings = SettingsView(window.app)
        for name, page in (("status", self.status), ("live", self.live), ("file", self.meeting),
                           (TRANSLATOR, self.translator), (SETTINGS, self.settings)):
            self.add_named(page, name)
        self.behind = self.current = "status"  # behind: the page a cover hides
        self.connect("notify::visible-child", self.on_page_changed)

    def translator_open(self):
        return self.get_visible_child_name() == TRANSLATOR

    def cover_open(self):
        return self.get_visible_child_name() in COVERS

    def show(self, name):
        """Switch page, or queue it behind the translator or settings while one is open."""
        if self.cover_open():
            self.behind = name
        else:
            self.set_visible_child_name(name)

    def show_status(self, title, description="", child=None):
        self.status.set_title(title)
        self.status.set_description(description)
        self.status.set_child(child)
        self.show("status")

    def open_translator(self):
        self.set_visible_child_name(TRANSLATOR)

    def open_settings(self, tab=None):
        self.settings.load(tab)
        self.set_visible_child_name(SETTINGS)

    def close_cover(self):
        if self.cover_open():
            self.set_visible_child_name(self.behind)

    def on_page_changed(self, *_):
        name = self.get_visible_child_name()
        if name == TRANSLATOR:
            self.translator.opened()
        elif self.current == TRANSLATOR:
            self.translator.closed()
        if name not in COVERS:
            self.behind = name
        self.current = name
