"""Live transcript: one block per speaker turn, English on the left and Spanish on the right."""
import re
from datetime import datetime

from gi.repository import Adw, GLib, Gtk

from ..transcript import MAX_PARAGRAPH

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
