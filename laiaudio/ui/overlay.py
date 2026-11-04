"""Floating caption bar (layer-shell): only the drag handle receives clicks, to move it."""
import json
import os
import socket
import textwrap
import time
from pathlib import Path

import cairo
from gi.repository import Gdk, GLib, Gtk
from gi.repository import Gtk4LayerShell as LayerShell

from ..config import config

LINE_CHARS = 80     # characters per line
HIDE_AFTER = 10.0   # hide after 10 s without speech


def cursor_position():
    """Global cursor position (Hyprland logical coordinates), or None on another compositor."""
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not signature:
        return None
    path = Path(os.environ["XDG_RUNTIME_DIR"]) / "hypr" / signature / ".socket.sock"
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(str(path))
        s.sendall(b"j/cursorpos")
        data = b""
        while chunk := s.recv(4096):
            data += chunk
    pos = json.loads(data)
    return pos["x"], pos["y"]


class Overlay(Gtk.Window):
    APPROX_WIDTH = 1150  # approximate bar width, to center it the first time

    def __init__(self, app):
        super().__init__(application=app, css_classes=["overlay-window"])
        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "laiaudio")
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_anchor(self, LayerShell.Edge.BOTTOM, True)
        LayerShell.set_anchor(self, LayerShell.Edge.LEFT, True)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)

        self.handle = Gtk.Image(icon_name="list-drag-handle-symbolic", pixel_size=20,
                                css_classes=["drag-handle"], tooltip_text="Drag to move")
        self.handle.set_cursor(Gdk.Cursor.new_from_name("grab"))
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self.on_drag_begin)
        drag.connect("drag-update", self.on_drag_update)
        drag.connect("drag-end", self.on_drag_end)
        self.handle.add_controller(drag)

        self.box = Gtk.Box(css_classes=["captions"])
        self.label = Gtk.Label(xalign=0, width_chars=LINE_CHARS, max_width_chars=LINE_CHARS)
        self.box.append(self.handle)
        self.box.append(self.label)
        self.set_child(self.box)
        self.connect("map", lambda *_: GLib.idle_add(self.place))

        self.font_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.font_css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        self.apply_style()

        self.wanted = False      # recording with the bar enabled
        self.previewing = False  # shown briefly after switching screens
        self.monitor = None
        self.left, self.bottom = 0, 70
        self.grab = (0, 0)
        self.history = ""  # recently committed text
        self.live = ""     # stable words in progress
        self.last_change = 0.0
        GLib.timeout_add(1000, self.auto_hide)

    def apply_style(self):
        self.font_css.load_from_string(f".captions label {{ font-size: {int(config['overlay_font_size'])}px; }}")

    @property
    def lines(self):
        return int(config["overlay_lines"])

    # --- position ---
    def monitors(self):
        mons = self.get_display().get_monitors()
        return [mons.get_item(i) for i in range(mons.get_n_items())]

    def place(self):
        if self.monitor is not None:  # already placed; it gets remapped when switching screens
            self.update_input_region()
            return False
        saved = config["overlay_position"] or {}
        mon = next((m for m in self.monitors() if m.get_connector() == saved.get("monitor")), None)
        if mon:
            self.left, self.bottom = saved["left"], saved["bottom"]
            self.fit(mon)
        else:
            mon = next((m for m in self.monitors() if m.get_connector() == config["overlay_monitor"]),
                       self.monitors()[0])
            self.center_on(mon)
        self.move_to(mon)
        self.update_input_region()
        return False

    def center_on(self, mon):
        width = self.get_width() or self.APPROX_WIDTH
        self.left = max(0, (mon.get_geometry().width - width) // 2)
        self.bottom = 70

    def move_to(self, mon):
        LayerShell.set_margin(self, LayerShell.Edge.LEFT, int(self.left))
        LayerShell.set_margin(self, LayerShell.Edge.BOTTOM, int(self.bottom))
        if mon != self.monitor:
            self.monitor = mon
            LayerShell.set_monitor(self, mon)
            self.save_position()

    def move_to_monitor(self, connector=None):
        """Move the bar to the given screen (or the next one), centered at the bottom, and show it briefly."""
        mons = self.monitors()
        if connector:
            mon = next((m for m in mons if m.get_connector() == connector), mons[0])
        else:
            current = mons.index(self.monitor) if self.monitor in mons else -1
            mon = mons[(current + 1) % len(mons)]
        self.center_on(mon)
        self.move_to(mon)
        self.save_position()
        self.preview()

    def preview(self):
        if not self.history and not self.live:
            where = self.monitor.get_connector() if self.monitor else ""
            self.history = f"Captions will appear here ({where})"
        self.previewing = True
        self.render()
        GLib.timeout_add_seconds(1, self.end_preview)

    def end_preview(self):
        if time.time() - self.last_change < 6:
            return True
        self.previewing = False
        if not self.wanted:
            self.reset()
        return False

    def on_drag_begin(self, _gesture, x, y):
        ok, bounds = self.handle.compute_bounds(self)
        self.grab = (bounds.origin.x + x, bounds.origin.y + y) if ok else (x, y)

    def on_drag_update(self, _gesture, _dx, _dy):
        # While dragging, the bar only moves inside its screen: switching screens with the pointer grabbed
        # makes the compositor destroy and recreate it, and GTK gets stuck
        pos = cursor_position()
        if pos is None:
            return
        self.follow_cursor(self.monitor, *pos)
        self.last_change = time.time()
        self.move_to(self.monitor)

    def on_drag_end(self, _gesture, _dx, _dy):
        pos = cursor_position()
        target = pos and next((m for m in self.monitors() if self.contains(m.get_geometry(), *pos)), None)
        if target and target != self.monitor:
            # Dropped on another screen: move it there now that the pointer is released
            GLib.idle_add(self.drop_on, target, *pos)
        else:
            self.save_position()

    def drop_on(self, mon, cx, cy):
        self.follow_cursor(mon, cx, cy)
        self.move_to(mon)
        self.save_position()
        return False

    def follow_cursor(self, mon, cx, cy):
        g = mon.get_geometry()
        self.left = cx - g.x - self.grab[0]
        self.bottom = g.height - (cy - g.y - self.grab[1]) - self.get_height()
        self.fit(mon)

    def fit(self, mon):
        """Keep the whole bar inside the screen."""
        g = mon.get_geometry()
        w, h = self.get_width() or self.APPROX_WIDTH, self.get_height() or 80
        self.left = min(max(0, self.left), max(0, g.width - w))
        self.bottom = min(max(0, self.bottom), max(0, g.height - h))

    @staticmethod
    def contains(g, x, y):
        return g.x <= x < g.x + g.width and g.y <= y < g.y + g.height

    def save_position(self):
        if self.monitor:
            config.set("overlay_position", {"monitor": self.monitor.get_connector(),
                                            "left": int(self.left), "bottom": int(self.bottom)})

    def reset_position(self):
        config.set("overlay_position", None)
        self.monitor = None
        if self.get_mapped():
            self.place()
            self.preview()

    def update_input_region(self):
        surface = self.get_surface()
        if not surface:
            return False
        ok, b = self.handle.compute_bounds(self)
        if ok and self.box.get_visible():
            rect = cairo.RectangleInt(int(b.origin.x) - 6, int(b.origin.y) - 6,
                                      int(b.size.width) + 12, int(b.size.height) + 12)
            surface.set_input_region(cairo.Region(rect))
        else:
            surface.set_input_region(cairo.Region())
        return False

    # --- text ---
    def reset(self):
        self.history, self.live = "", ""
        self.render()

    def set_live(self, stable):
        # The bar never shrinks mid-sentence (the model sometimes loses its stable words for an instant);
        # it does accept corrections of equal or greater length, usually 1–2 words
        if len(stable.split()) >= len(self.live.split()):
            self.live = stable
            self.render()

    def add_committed(self, text):
        self.history = f"{self.history} {text}".strip()
        self.live = ""
        lines = self.wrap(self.history)
        if len(lines) > 40:  # trim by whole lines so the text does not reflow
            self.history = " ".join(lines[-self.lines:])
        self.render()

    @staticmethod
    def wrap(text):
        return textwrap.wrap(text, LINE_CHARS, break_long_words=False, break_on_hyphens=False)

    def render(self):
        # Fixed lines: new text goes at the end and, when full, everything moves up one line
        lines = self.wrap(f"{self.history} {self.live}".strip())[-self.lines:]
        self.label.set_text("\n".join(lines + [""] * (self.lines - len(lines))))
        self.last_change = time.time()
        self.box.set_visible(bool(lines))
        self.set_visible(self.wanted or self.previewing)
        GLib.idle_add(self.update_input_region)

    def auto_hide(self):
        if self.box.get_visible() and time.time() - self.last_change > HIDE_AFTER:
            self.reset()
        return True
