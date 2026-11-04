"""Model card: its strength and trade-off, plus Download / progress / Ready / Delete."""
from gi.repository import Adw, GLib, Gtk

from ..hardware import recommend
from ..models import Download


class ModelCard(Adw.ActionRow):
    def __init__(self, on_change=None):
        super().__init__(subtitle_lines=0, title_lines=0)  # never cut with an ellipsis
        self.on_change = on_change  # se llama al terminar una descarga o al borrar
        self.model = None
        self.problem = None
        self.download = None

        self.download_btn = Gtk.Button(valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
        self.download_btn.connect("clicked", lambda *_: self.start_download())
        self.cancel_btn = Gtk.Button(label="Cancel", valign=Gtk.Align.CENTER)
        self.cancel_btn.connect("clicked", lambda *_: self.download and self.download.cancel())
        self.progress = Gtk.ProgressBar(valign=Gtk.Align.CENTER, show_text=True, width_request=160)
        self.ready = Gtk.Label(label="✓ Ready", css_classes=["success"], valign=Gtk.Align.CENTER)
        self.delete_btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                     tooltip_text="Delete the downloaded model", css_classes=["flat"])
        self.delete_btn.connect("clicked", lambda *_: self.confirm_delete())
        box = Gtk.Box(spacing=8)
        for w in (self.progress, self.cancel_btn, self.download_btn, self.ready, self.delete_btn):
            box.append(w)
        self.add_suffix(box)

    def set_model(self, model, problem=None):
        self.model, self.problem = model, problem
        badge = "  ·  Recommended for your machine" if model in recommend() else ""
        needs = [f"Requires: {model.hardware}"] if model.hardware else []
        if model.downloadable:
            needs.append(f"Size {model.size_label}")
        lines = [model.gains, model.loses] + (["  ·  ".join(needs)] if needs else [])
        if problem:
            lines.append(f"⚠ {problem}")
        self.set_title(GLib.markup_escape_text(model.name + badge))
        self.set_subtitle(GLib.markup_escape_text("\n".join(f"•  {line}" for line in lines)))
        self.refresh()

    def refresh(self):
        model = self.model
        download = Download.active.get(model.id)
        if download and download is not self.download:
            download.listen(self.on_progress)
        self.download = download
        downloading = download is not None
        installed = not downloading and model.installed()
        self.progress.set_visible(downloading)
        self.cancel_btn.set_visible(downloading)
        self.download_btn.set_visible(not downloading and not installed and not self.problem)
        self.download_btn.set_label(f"Download ({model.size_label})")
        self.ready.set_visible(installed and model.downloadable)
        self.delete_btn.set_visible(installed and model.downloadable)
        if downloading:
            self.progress.set_fraction(download.progress)
            self.progress.set_text(f"{download.progress:.0%}")

    def start_download(self):
        Download.start_for(self.model)
        self.refresh()

    def on_progress(self, download, done, error):
        if download.model is not self.model:
            return False
        if not done:
            self.progress.set_fraction(download.progress)
            self.progress.set_text(f"{download.progress:.0%}")
            return False
        self.download = None
        self.refresh()
        if error:
            self.add_error(error)
        if self.on_change:
            self.on_change(self.model)
        return False

    def add_error(self, error):
        self.set_subtitle(GLib.markup_escape_text(f"⚠ Download failed: {error}"))

    def confirm_delete(self):
        dialog = Adw.AlertDialog(heading=f"Delete {self.model.name}?",
                                 body=f"This frees {self.model.size_label}. You can download it again at any time.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self.on_delete_response)
        dialog.present(self.get_root())

    def on_delete_response(self, _dialog, response):
        if response != "delete":
            return
        self.model.delete()
        self.refresh()
        if self.on_change:
            self.on_change(self.model)
