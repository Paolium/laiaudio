"""Saved meeting: a sticky bar with the title and actions, and the .md as a preview or as Markdown."""
import re
import subprocess
from datetime import datetime

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

# Automatic headings (the Spanish ones come from transcripts made before the English UI)
DEFAULT_HEADING = re.compile(r"^(?:Meeting|Reunión) — (\d{4}-\d{2}-\d{2} \d{2}:\d{2})$")
TURN = re.compile(r"^\*\*\[(\d{2}:\d{2}:\d{2})\] (.+?):\*\* (.*)$")
END = re.compile(r"^_(?:End|Fin): (.+)_$")
ME_LABELS = {"Me", "Yo"}


def meeting_title(path):
    """The title is the .md heading; when it is the automatic one, the date is shown instead."""
    with path.open(encoding="utf-8") as f:
        first = f.readline().strip()
    heading = first[2:].strip() if first.startswith("# ") else ""
    match = DEFAULT_HEADING.match(heading)
    if heading and not match:
        return heading
    try:
        when = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M") if match else \
            datetime.strptime(path.stem, "%Y-%m-%d_%H-%M")
        return f"{when:%b %d, %Y  %H:%M}"
    except ValueError:
        return path.stem


def rename_meeting(path, title):
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    heading = f"# {title}\n"
    if lines and lines[0].startswith("# "):
        lines[0] = heading
    else:
        lines[:0] = [heading, "\n"]
    path.write_text("".join(lines), encoding="utf-8")


def show_in_file_manager(path):
    """Open the file manager with the file selected (or its folder when that is not possible)."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        bus.call_sync("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                      "org.freedesktop.FileManager1", "ShowItems",
                      GLib.Variant("(ass)", ([path.as_uri()], "")), None, Gio.DBusCallFlags.NONE, 3000)
    except GLib.Error:
        subprocess.Popen(["xdg-open", str(path.parent)])


def confirm_delete(parent, path, on_deleted):
    dialog = Adw.AlertDialog(heading="Delete this meeting?",
                             body=f"“{meeting_title(path)}” will be moved to the trash.")
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("delete", "Delete")
    dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

    def response(_dialog, answer):
        if answer == "delete":
            Gio.File.new_for_path(str(path)).trash(None)
            on_deleted(path)

    dialog.connect("response", response)
    dialog.present(parent)


def ask_title(parent, path, on_renamed):
    entry = Gtk.Entry(text=meeting_title(path), activates_default=True)
    dialog = Adw.AlertDialog(heading="Meeting title", extra_child=entry, default_response="save")
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("save", "Save")
    dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

    def response(_dialog, answer):
        if answer == "save" and (title := entry.get_text().strip()):
            rename_meeting(path, title)
            on_renamed(path)

    dialog.connect("response", response)
    dialog.present(parent)
    entry.grab_focus()


def icon_button(icon, tooltip, action):
    button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, css_classes=["flat"])
    button.connect("clicked", lambda *_: action())
    return button


class MeetingView(Gtk.Box):
    """Sticky bar on top (mode · title · actions) and the scrollable content below."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.path = None

        # --- sticky bar ---
        preview_btn = Gtk.ToggleButton(label="Preview", active=True, css_classes=["flat"])
        source_btn = Gtk.ToggleButton(label="Markdown", group=preview_btn, css_classes=["flat"])
        preview_btn.connect("toggled", lambda b: self.pages.set_visible_child_name(
            "preview" if b.get_active() else "source"))
        modes = Gtk.Box(css_classes=["pill-bar"])
        modes.append(preview_btn)
        modes.append(source_btn)

        self.title = Gtk.Label(css_classes=["file-title"], ellipsize=Pango.EllipsizeMode.END)
        actions = Gtk.Box(css_classes=["pill-bar"])
        for icon, tooltip, action in (
            ("document-edit-symbolic", "Edit title", self.edit_title),
            ("edit-copy-symbolic", "Copy all text", self.copy_all),
            ("folder-open-symbolic", "Show the .md file in the file manager", lambda: show_in_file_manager(self.path)),
            ("user-trash-symbolic", "Delete", self.delete),
        ):
            actions.append(icon_button(icon, tooltip, action))

        bar = Gtk.CenterBox(css_classes=["file-toolbar"], start_widget=modes, center_widget=self.title,
                            end_widget=actions)
        self.append(bar)

        # --- content ---
        self.preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                               margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        self.source = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                   left_margin=24, right_margin=24, top_margin=24, bottom_margin=24,
                                   monospace=True)
        self.pages = Gtk.Stack(vexpand=True)
        self.pages.add_named(Gtk.ScrolledWindow(child=Adw.Clamp(maximum_size=900, child=self.preview),
                                                hscrollbar_policy=Gtk.PolicyType.NEVER), "preview")
        self.pages.add_named(Gtk.ScrolledWindow(child=self.source), "source")
        self.append(self.pages)

    def load(self, path):
        self.path = path
        text = path.read_text(encoding="utf-8")
        self.title.set_text(meeting_title(path))
        self.source.get_buffer().set_text(text)
        while child := self.preview.get_first_child():
            self.preview.remove(child)
        for line in text.splitlines():
            self.preview_line(line.strip())

    def preview_line(self, line):
        if not line or line.startswith("# "):
            return  # the title is already in the bar
        if match := TURN.match(line):
            time, speaker, text = match.groups()
            css = "speaker-me" if speaker in ME_LABELS else "speaker-meeting"
            turn = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            turn.append(Gtk.Label(label=f"{time}  ·  {speaker}", xalign=0, css_classes=["turn-header", css]))
            turn.append(Gtk.Label(label=text, xalign=0, wrap=True, selectable=True, css_classes=["turn-text"]))
            self.preview.append(turn)
        elif match := END.match(line):
            self.preview.append(Gtk.Label(label=f"End: {match.group(1)}", xalign=0, css_classes=["dim-label"]))
        else:
            self.preview.append(Gtk.Label(label=line, xalign=0, wrap=True, selectable=True))

    def edit_title(self):
        ask_title(self.window, self.path, self.window.meeting_changed)

    def copy_all(self):
        Gdk.Display.get_default().get_clipboard().set(self.path.read_text(encoding="utf-8"))
        self.window.toast("Text copied to the clipboard")

    def delete(self):
        confirm_delete(self.window, self.path, self.window.meeting_deleted)
