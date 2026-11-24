"""Settings page: tabs for General, Audio, Transcription and Translation."""
from gi.repository import Adw, Gio, GLib, Gtk

from .. import audio
from ..config import config
from ..hardware import detect, problem, recommend
from ..models import BY_ID, of_kind
from .model_card import ModelCard
from .overlay import monitor_name


def combo(title, labels, selected, on_selected, subtitle=None):
    row = Adw.ComboRow(title=title, model=Gtk.StringList.new(labels), selected=max(0, selected))
    if subtitle:
        row.set_subtitle(subtitle)
    row.connect("notify::selected", lambda r, _p: on_selected(r.get_selected()))
    return row


def widen(widget, size=920):
    """libadwaita caps pages at ~600 px; in the wide workspace that cuts names with an ellipsis."""
    child = widget.get_first_child()
    while child:
        if isinstance(child, (Adw.Clamp, Adw.ClampScrollable)):
            child.set_maximum_size(size)
            child.set_tightening_threshold(size)
        widen(child, size)
        child = child.get_next_sibling()


SETTING = {"asr": "asr_model", "translation": "translation"}


class SettingsView(Gtk.Box):
    """Sticky bar with the tabs as a centered pill bar and the selected tab below (the header shows the title).

    The tabs are rebuilt every time the page opens, so devices, screens and models are always current.
    """

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.pickers = {}       # kind -> (dropdown, models, card)
        self.updating = False   # ignore the changes made by the code itself
        self.bar = Gtk.CenterBox(css_classes=["file-toolbar"])
        self.toasts = Adw.ToastOverlay(vexpand=True)
        self.append(self.bar)
        self.append(self.toasts)

    def load(self, tab=None):
        self.pickers.clear()
        tabs = Gtk.Stack()
        pills = Gtk.Box(css_classes=["pill-bar"])
        for page in (self.general_page(), self.audio_page(),
                     self.model_page("asr", "transcription", "Transcription", "audio-input-microphone-symbolic",
                                     "Transcription model", "Turns English speech into text"),
                     self.model_page("translation", "translation", "Translation",
                                     "preferences-desktop-locale-symbolic",
                                     "Translation engine", "What appears in the Spanish column (ES button)")):
            tabs.add_named(page, page.get_name())
            page.connect("map", widen)  # pages finish building when shown
            button = Gtk.ToggleButton(label=page.get_title(), css_classes=["flat"], group=pills.get_first_child(),
                                      active=page.get_name() == (tab or "general"))
            button.connect("toggled", lambda b, name=page.get_name(): b.get_active() and
                           tabs.set_visible_child_name(name))
            pills.append(button)
        tabs.set_visible_child_name(tab or "general")
        self.bar.set_center_widget(pills)
        self.toasts.set_child(tabs)

    def add_toast(self, toast):
        self.toasts.add_toast(toast)

    # --- General ---
    def general_page(self):
        page = Adw.PreferencesPage(name="general", title="General", icon_name="emblem-system-symbolic")

        asr, translation = recommend()
        note = "" if detect().cuda else (" · Laiaudio is optimized for NVIDIA GPUs: on this machine "
                                          "transcription uses the Lite model on the CPU")
        team = Adw.PreferencesGroup(title="Your machine",
                                    description=f"Models that do not fit are marked “won't fit” and cannot be chosen{note}")
        hw_row = Adw.ActionRow(title=GLib.markup_escape_text(detect().summary),
                               subtitle=f"Recommended: {asr.short} + {translation.short}")
        use = Gtk.Button(label="Use recommended", valign=Gtk.Align.CENTER)
        use.connect("clicked", lambda *_: self.use_recommended())
        hw_row.add_suffix(use)
        team.add(hw_row)
        page.add(team)

        meetings = Adw.PreferencesGroup(title="Meetings")
        self.folder_row = Adw.ActionRow(title="Transcript folder (.md)", subtitle=str(config.meetings_dir))
        change = Gtk.Button(label="Change", valign=Gtk.Align.CENTER)
        change.connect("clicked", lambda *_: self.choose_folder())
        self.folder_row.add_suffix(change)
        meetings.add(self.folder_row)
        page.add(meetings)

        bar = Adw.PreferencesGroup(title="Floating captions")
        enabled = Adw.SwitchRow(title="Show while recording", active=config["overlay_enabled"])
        enabled.connect("notify::active", lambda r, _p: self.app.set_overlay_enabled(r.get_active()))
        bar.add(enabled)

        monitors = self.app.overlay.monitors()
        connectors = [monitor_name(m) for m in monitors]
        labels = [f"{monitor_name(m)}  ({m.get_geometry().width}×{m.get_geometry().height})" for m in monitors]
        current = (config["overlay_position"] or {}).get("monitor") or config["overlay_monitor"]
        bar.add(combo("Screen", labels, connectors.index(current) if current in connectors else 0,
                      lambda i: self.set_monitor(connectors[i])))

        lines = Adw.SpinRow.new_with_range(1, 4, 1)
        lines.set_title("Lines")
        lines.set_value(config["overlay_lines"])
        lines.connect("notify::value", lambda r, _p: self.set_overlay("overlay_lines", int(r.get_value())))
        bar.add(lines)

        size = Adw.SpinRow.new_with_range(14, 40, 1)
        size.set_title("Font size")
        size.set_value(config["overlay_font_size"])
        size.connect("notify::value", lambda r, _p: self.set_overlay("overlay_font_size", int(r.get_value())))
        bar.add(size)

        page.add(bar)
        return page

    def use_recommended(self):
        asr, translation = recommend()
        config.set("asr_model", asr.id)
        config.set("translation", translation.id)
        for kind in self.pickers:
            self.refresh_picker(kind)
            self.app.models_changed(kind)
        self.add_toast(Adw.Toast(title=f"Using {asr.short} + {translation.short}"))

    def choose_folder(self):
        dialog = Gtk.FileDialog(title="Transcript folder",
                                initial_folder=Gio.File.new_for_path(str(config.meetings_dir)))
        dialog.select_folder(self.app.win, None, self.on_folder_chosen)

    def on_folder_chosen(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return  # cancelled
        config.set("meetings_dir", folder.get_path())
        self.folder_row.set_subtitle(folder.get_path())
        self.app.win.refresh_meetings()

    def set_monitor(self, connector):
        config.set("overlay_monitor", connector)
        self.app.overlay.move_to_monitor(connector)

    def set_overlay(self, key, value):
        config.set(key, value)
        self.app.overlay.apply_style()
        self.app.overlay.preview()

    # --- Audio ---
    def audio_page(self):
        page = Adw.PreferencesPage(name="audio", title="Audio", icon_name="audio-speakers-symbolic")
        group = Adw.PreferencesGroup(title="What gets transcribed",
                                     description="Applies the next time you press Start")

        outputs = audio.outputs()
        names = ["auto"] + [name for name, _ in outputs]
        labels = ["Automatic (whatever plays on the default output)"] + [desc for _, desc in outputs]
        group.add(combo("Meeting audio", labels,
                        names.index(config["system_source"]) if config["system_source"] in names else 0,
                        lambda i: config.set("system_source", names[i])))

        use_mic = Adw.SwitchRow(title="Also transcribe my microphone", subtitle="Shows up as “Me”",
                                active=config["use_mic"])
        use_mic.connect("notify::active", lambda r, _p: self.app.set_use_mic(r.get_active()))
        group.add(use_mic)

        inputs = audio.inputs()
        mic_names = ["auto"] + [name for name, _ in inputs]
        mic_labels = ["Automatic (default microphone)"] + [desc for _, desc in inputs]
        group.add(combo("Microphone", mic_labels,
                        mic_names.index(config["mic_source"]) if config["mic_source"] in mic_names else 0,
                        lambda i: config.set("mic_source", mic_names[i])))
        page.add(group)
        return page

    # --- Transcription / Translation ---
    def model_page(self, kind, name, title, icon, combo_title, description):
        page = Adw.PreferencesPage(name=name, title=title, icon_name=icon)
        group = Adw.PreferencesGroup(title=combo_title, description=description)
        card = ModelCard(on_change=lambda m: self.app.models_changed(kind))
        row = Adw.ComboRow(title="Model")
        row.connect("notify::selected", lambda r, _p: self.on_pick(kind, r.get_selected()))
        self.pickers[kind] = (row, of_kind(kind), card)
        self.refresh_picker(kind)
        group.add(row)
        group.add(card)
        page.add(group)

        if kind == "asr":
            hw = Adw.PreferencesGroup(title="Hardware")
            devices = ["auto", "cpu"]
            hw.add(combo("Run on", ["Automatic", "CPU only"],
                         devices.index(config["asr_device"]),
                         lambda i: (config.set("asr_device", devices[i]), self.app.models_changed("asr")),
                         subtitle=f"Automatic uses the NVIDIA GPU when available, otherwise the CPU. "
                                  f"{self.app.engine_description()}"))
            page.add(hw)
        return page

    # --- what fits this machine ---
    def picker_problem(self, kind, model):
        """Transcription is judged alone (translation adapts if it no longer fits); translation, together with it."""
        return problem(model, BY_ID.get(config["asr_model"]) if kind == "translation" else None)

    def refresh_picker(self, kind):
        row, models, card = self.pickers[kind]
        # Short name in the list (the full one is on the card) and a mark on the ones that do not fit
        labels = [m.short + ("  ·  won't fit" if self.picker_problem(kind, m) else "") for m in models]
        ids = [m.id for m in models]
        current = config[SETTING[kind]]
        self.updating = True
        row.set_model(Gtk.StringList.new(labels))
        row.set_selected(ids.index(current) if current in ids else 0)
        self.updating = False
        model = models[row.get_selected()]
        card.set_model(model, self.picker_problem(kind, model))
        return False  # also used with GLib.idle_add

    def on_pick(self, kind, index):
        if self.updating:
            return
        _row, models, _card = self.pickers[kind]
        model = models[index]
        if reason := self.picker_problem(kind, model):
            self.add_toast(Adw.Toast(title=GLib.markup_escape_text(reason), timeout=6))
            # Go back to the previous option after this event: changing the list inside its own
            # selection notification makes GTK notify again and creates an endless loop
            GLib.idle_add(self.refresh_picker, kind)
            return
        config.set(SETTING[kind], model.id)
        if kind == "asr":  # a heavier Parakeet can leave no room for the translation AI
            translation = BY_ID.get(config["translation"])
            if translation and problem(translation, model):
                config.set("translation", "marian")
                self.add_toast(Adw.Toast(title=f"With {model.short}, {translation.short} no longer fits: "
                                               "translation switched to Marian (literal)", timeout=6))
                self.app.models_changed("translation")
        for other in self.pickers:
            GLib.idle_add(self.refresh_picker, other)
        self.app.models_changed(kind)
