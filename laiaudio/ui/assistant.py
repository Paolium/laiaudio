"""Text translator: paste Spanish to get clear B2 English, or English to get Spanish (local LLM)."""
from gi.repository import Adw, Gdk, GLib, Gtk

from ..translate import TextAssistant, assistant_model, looks_spanish


def text_box(editable):
    view = Gtk.TextView(editable=editable, cursor_visible=editable, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                        top_margin=12, bottom_margin=12, left_margin=14, right_margin=14,
                        css_classes=["assistant-text"])
    scroll = Gtk.ScrolledWindow(child=view, vexpand=True, min_content_height=140, css_classes=["assistant-box"])
    return view, scroll


class AssistantDialog(Adw.Dialog):
    def __init__(self, app):
        super().__init__(title="Translator", content_width=760, content_height=600)
        self.app = app
        self.assistant = TextAssistant()
        self.connect("closed", lambda *_: self.assistant.close())  # frees the GPU when nobody else uses the AI

        hint = Gtk.Label(label="Paste Spanish to get clear B2 English, or English to get Spanish.",
                         xalign=0, wrap=True, css_classes=["dim-label"])
        self.input, input_scroll = text_box(editable=True)
        self.input.get_buffer().connect("changed", lambda *_: self.update_direction())

        self.direction = Gtk.Label(xalign=0, hexpand=True, css_classes=["assistant-direction"])
        self.spinner = Gtk.Spinner()
        self.run_btn = Gtk.Button(label="Translate", css_classes=["suggested-action"],
                                  tooltip_text="Translate (Ctrl+Enter)")
        self.run_btn.connect("clicked", lambda *_: self.run())
        actions = Gtk.Box(spacing=10)
        for widget in (self.direction, self.spinner, self.run_btn):
            actions.append(widget)

        self.output, output_scroll = text_box(editable=False)
        self.status = Gtk.Label(xalign=0, hexpand=True, wrap=True, css_classes=["dim-label"])
        copy = Gtk.Button(child=Adw.ButtonContent(icon_name="edit-copy-symbolic", label="Copy"), css_classes=["flat"])
        copy.connect("clicked", lambda *_: self.copy())
        footer = Gtk.Box(spacing=10)
        footer.append(self.status)
        footer.append(copy)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       margin_top=6, margin_bottom=18, margin_start=18, margin_end=18)
        for widget in (hint, input_scroll, actions, output_scroll, footer):
            body.append(widget)
        toolbar = Adw.ToolbarView(content=body)
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar)

        shortcut = Gtk.ShortcutController()
        shortcut.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string("<Control>Return"),
                                           action=Gtk.CallbackAction.new(lambda *_: self.run() or True)))
        self.add_controller(shortcut)

        self.update_direction()
        if assistant_model() is None:
            self.run_btn.set_sensitive(False)
            self.status.set_text("Download Qwen3 4B or Gemma 3 4B in Settings → Translation to use the translator.")
        GLib.idle_add(self.input.grab_focus)

    def text(self, view):
        buffer = view.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()

    def update_direction(self):
        text = self.text(self.input)
        if not text:
            self.direction.set_text("")
        elif looks_spanish(text):
            self.direction.set_text("Spanish → English (B2)")
        else:
            self.direction.set_text("English → Spanish")

    def run(self):
        text = self.text(self.input)
        if not text or not self.run_btn.get_sensitive():
            return
        self.run_btn.set_sensitive(False)
        self.spinner.start()
        self.assistant.run(text, self.on_done, self.status.set_text)

    def on_done(self, result, error):
        self.spinner.stop()
        self.run_btn.set_sensitive(True)
        if error:
            self.status.set_text(f"Could not translate: {error}")
        else:
            self.output.get_buffer().set_text(result)
            self.status.set_text("")
        return False

    def copy(self):
        if text := self.text(self.output):
            Gdk.Display.get_default().get_clipboard().set(text)
            self.status.set_text("Copied to the clipboard")
