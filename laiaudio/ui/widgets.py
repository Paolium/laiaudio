"""Small widgets shared across the UI."""
import cairo
from gi.repository import Gtk


class StateToggle(Gtk.ToggleButton):
    """Background-less on/off toggle: the icon (or text) turns colored when on and gets a diagonal slash when off."""

    def __init__(self, css, tooltip, active, icon=None, label=None):
        super().__init__(active=active, tooltip_text=tooltip, css_classes=["flat", "state-toggle", css])
        content = Gtk.Image(icon_name=icon) if icon else Gtk.Label(label=label, css_classes=["state-label"])
        self.slash = Gtk.DrawingArea(can_target=False)
        self.slash.set_draw_func(self.draw_slash)
        overlay = Gtk.Overlay(child=content)
        overlay.add_overlay(self.slash)
        self.set_child(overlay)
        self.connect("toggled", lambda *_: self.slash.queue_draw())

    def draw_slash(self, area, cr, width, height):
        if self.get_active():
            return
        color = area.get_color()
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_width(1.7)
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        # Short slash, centered over the icon or text
        size = min(width, height) * 0.8
        x0, y0 = (width - size) / 2, (height + size) / 2
        cr.move_to(x0, y0)
        cr.line_to(x0 + size, y0 - size)
        cr.stroke()
