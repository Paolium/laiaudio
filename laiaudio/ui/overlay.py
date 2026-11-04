"""Floating caption bar: only the drag handle receives clicks, to move it.

Two placements share the same text logic: layer-shell (Hyprland, Sway, KDE…) and an "always on top" X11 window
(GNOME on Ubuntu, X11 sessions such as Linux Mint). `create_overlay` picks the one this session supports.
"""
import json
import os
import socket
import textwrap
import time
from pathlib import Path

import cairo
from gi.repository import Gdk, GLib, Gtk

from .. import desktop
from ..config import config

LINE_CHARS = 80     # characters per line
HIDE_AFTER = 10.0   # hide after 10 s without speech
BOTTOM_GAP = 70     # default distance from the bottom of the screen


def create_overlay(app):
    if desktop.overlay_backend() == desktop.LAYER_SHELL:
        return LayerShellOverlay(app)
    return X11Overlay(app)


class Overlay(Gtk.Window):
    """Text logic shared by every placement: fixed lines that never jump or shrink mid-sentence."""

    APPROX_WIDTH = 1150  # approximate bar width, to center it the first time

    def __init__(self, app):
        super().__init__(application=app, css_classes=["overlay-window"])
        self.handle = Gtk.Image(icon_name="list-drag-handle-symbolic", pixel_size=20,
                                css_classes=["drag-handle"], tooltip_text="Drag to move")
        self.handle.set_cursor(Gdk.Cursor.new_from_name("grab"))
        self.box = Gtk.Box(css_classes=["captions"])
        self.label = Gtk.Label(xalign=0, width_chars=LINE_CHARS, max_width_chars=LINE_CHARS)
        self.box.append(self.handle)
        self.box.append(self.label)
        self.set_child(self.box)

        self.font_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.font_css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        self.apply_style()

        self.wanted = False      # recording with the bar enabled
        self.previewing = False  # shown briefly after switching screens
        self.history = ""        # recently committed text
        self.live = ""           # stable words in progress
        self.last_change = 0.0
        GLib.timeout_add(1000, self.auto_hide)

    def apply_style(self):
        self.font_css.load_from_string(f".captions label {{ font-size: {int(config['overlay_font_size'])}px; }}")

    @property
    def lines(self):
        return int(config["overlay_lines"])

    def monitors(self):
        mons = self.get_display().get_monitors()
        return [mons.get_item(i) for i in range(mons.get_n_items())]

    def default_monitor(self):
        mons = self.monitors()
        return next((m for m in mons if m.get_connector() == config["overlay_monitor"]), mons[0])

    def bar_size(self):
        return self.get_width() or self.APPROX_WIDTH, self.get_height() or 80

    def move_to_monitor(self, connector=None):
        """Move the bar to the given screen, centered at the bottom, and show it briefly."""
        raise NotImplementedError

    def preview(self):
        if not self.history and not self.live:
            self.history = "Captions will appear here"
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

    def update_input_region(self):
        """Clicks pass through the bar except on the drag handle."""
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


def hyprland_cursor():
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


class LayerShellOverlay(Overlay):
    """Overlay surface for compositors with layer-shell; positioned with margins from the bottom-left corner."""

    def __init__(self, app):
        super().__init__(app)
        import gi

        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell as LayerShell

        self.ls = LayerShell
        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "laiaudio")
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_anchor(self, LayerShell.Edge.BOTTOM, True)
        LayerShell.set_anchor(self, LayerShell.Edge.LEFT, True)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.NONE)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self.on_drag_begin)
        drag.connect("drag-update", self.on_drag_update)
        drag.connect("drag-end", self.on_drag_end)
        self.handle.add_controller(drag)
        self.connect("map", lambda *_: GLib.idle_add(self.place))

        self.monitor = None
        self.left, self.bottom = 0, BOTTOM_GAP
        self.grab = (0, 0)

    def place(self):
        if self.monitor is not None:  # already placed; it gets remapped when switching screens
            self.update_input_region()
            return False
        saved = config["overlay_position"] or {}
        mon = next((m for m in self.monitors() if m.get_connector() == saved.get("monitor")), None)
        if mon and "left" in saved:
            self.left, self.bottom = saved["left"], saved["bottom"]
            self.fit(mon)
        else:
            mon = self.default_monitor()
            self.center_on(mon)
        self.move_to(mon)
        self.update_input_region()
        return False

    def center_on(self, mon):
        self.left = max(0, (mon.get_geometry().width - self.bar_size()[0]) // 2)
        self.bottom = BOTTOM_GAP

    def move_to(self, mon):
        self.ls.set_margin(self, self.ls.Edge.LEFT, int(self.left))
        self.ls.set_margin(self, self.ls.Edge.BOTTOM, int(self.bottom))
        if mon != self.monitor:
            self.monitor = mon
            self.ls.set_monitor(self, mon)
            self.save_position()

    def move_to_monitor(self, connector=None):
        mons = self.monitors()
        mon = next((m for m in mons if m.get_connector() == connector), mons[0])
        self.center_on(mon)
        self.move_to(mon)
        self.save_position()
        self.preview()

    def on_drag_begin(self, _gesture, x, y):
        ok, bounds = self.handle.compute_bounds(self)
        self.grab = (bounds.origin.x + x, bounds.origin.y + y) if ok else (x, y)

    def on_drag_update(self, _gesture, _dx, _dy):
        # While dragging, the bar only moves inside its screen: switching screens with the pointer grabbed
        # makes the compositor destroy and recreate it, and GTK gets stuck
        pos = hyprland_cursor()
        if pos is None:
            return
        self.follow_cursor(self.monitor, *pos)
        self.last_change = time.time()
        self.move_to(self.monitor)

    def on_drag_end(self, _gesture, _dx, _dy):
        pos = hyprland_cursor()
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
        w, h = self.bar_size()
        self.left = min(max(0, self.left), max(0, g.width - w))
        self.bottom = min(max(0, self.bottom), max(0, g.height - h))

    @staticmethod
    def contains(g, x, y):
        return g.x <= x < g.x + g.width and g.y <= y < g.y + g.height

    def save_position(self):
        if self.monitor:
            config.set("overlay_position", {"monitor": self.monitor.get_connector(),
                                            "left": int(self.left), "bottom": int(self.bottom)})


class X11Overlay(Overlay):
    """Undecorated, always-on-top X11 window (GNOME through XWayland, or any X11 session).

    The window manager moves it while the handle is dragged; its position is read back and saved.
    """

    def __init__(self, app):
        super().__init__(app)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_title("Laiaudio captions")
        press = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        press.connect("pressed", self.on_handle_pressed)
        self.handle.add_controller(press)
        self.connect("realize", lambda *_: self.mark_as_overlay())
        self.connect("map", lambda *_: GLib.timeout_add(50, self.place))
        self.connect("unmap", lambda *_: self.on_unmap())
        self.xdisplay = self.xwin = None
        self.position = None  # (x, y) on the X11 root window
        self.placed = False   # do not read the position back until the bar has been placed
        GLib.timeout_add(1000, self.track_position)

    def mark_as_overlay(self):
        """Ask the window manager to keep the bar above everything, on every workspace, out of the taskbar."""
        from Xlib import Xatom
        from Xlib import display as xdisplay

        self.xdisplay = xdisplay.Display()
        self.xwin = self.xdisplay.create_resource_object("window", self.get_surface().get_xid())
        atom = self.xdisplay.intern_atom
        self.xwin.change_property(atom("_NET_WM_WINDOW_TYPE"), Xatom.ATOM, 32,
                                  [atom("_NET_WM_WINDOW_TYPE_UTILITY")])
        self.xwin.change_property(atom("_NET_WM_STATE"), Xatom.ATOM, 32, self.wm_states())
        # Initial position as a user-specified hint, so the window manager maps it there
        from Xlib import Xutil

        self.position = self.position or self.saved_position() or self.centered_on(self.default_monitor())
        self.xwin.set_wm_normal_hints(flags=Xutil.USPosition | Xutil.PPosition,
                                      x=int(self.position[0]), y=int(self.position[1]))
        self.xdisplay.flush()

    def wm_states(self):
        atom = self.xdisplay.intern_atom
        return [atom(name) for name in ("_NET_WM_STATE_ABOVE", "_NET_WM_STATE_STICKY",
                                        "_NET_WM_STATE_SKIP_TASKBAR", "_NET_WM_STATE_SKIP_PAGER")]

    def reassert_states(self):
        """Window managers may reset the initial state on map; ask again through the root window."""
        from Xlib import X
        from Xlib.protocol import event

        root = self.xdisplay.screen().root
        state = self.xdisplay.intern_atom("_NET_WM_STATE")
        for value in self.wm_states():
            message = event.ClientMessage(window=self.xwin, client_type=state, data=(32, [1, value, 0, 1, 0]))
            root.send_event(message, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        self.xdisplay.flush()

    @staticmethod
    def saved_position():
        saved = config["overlay_position"] or {}
        return (saved["x"], saved["y"]) if "x" in saved else None

    def place(self):
        if not self.xwin:
            return False
        self.position = self.position or self.saved_position() or self.centered_on(self.default_monitor())
        self.move(*self.position)
        self.reassert_states()
        self.update_input_region()
        GLib.timeout_add(500, self.mark_placed)
        return False

    def mark_placed(self):
        self.placed = True
        return False

    def centered_on(self, mon):
        g = mon.get_geometry()
        w, h = self.bar_size()
        return g.x + max(0, (g.width - w) // 2), g.y + g.height - h - BOTTOM_GAP

    def move(self, x, y):
        """Ask the window manager to move the bar (EWMH _NET_MOVERESIZE_WINDOW, flagged as a user action)."""
        from Xlib import X
        from Xlib.protocol import event

        flags = (1 << 8) | (1 << 9) | (2 << 12)  # x and y are set; source indication 2 = user / pager
        message = event.ClientMessage(window=self.xwin,
                                      client_type=self.xdisplay.intern_atom("_NET_MOVERESIZE_WINDOW"),
                                      data=(32, [flags, int(x), int(y), 0, 0]))
        self.xdisplay.screen().root.send_event(message, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        self.xwin.configure(x=int(x), y=int(y))  # for window managers without EWMH
        self.xdisplay.flush()

    def move_to_monitor(self, connector=None):
        mons = self.monitors()
        mon = next((m for m in mons if m.get_connector() == connector), mons[0])
        self.position = self.centered_on(mon)
        self.save_position()
        if self.xwin and self.get_mapped():
            self.move(*self.position)
        self.preview()

    def on_unmap(self):
        self.placed = False

    def on_handle_pressed(self, gesture, _n_press, x, y):
        ok, point = self.handle.compute_point(self, self.handle_point(x, y))
        surface = self.get_surface()
        if ok and surface:
            surface.begin_move(gesture.get_device(), Gdk.BUTTON_PRIMARY, point.x, point.y,
                               gesture.get_current_event_time())

    @staticmethod
    def handle_point(x, y):
        from gi.repository import Graphene

        return Graphene.Point().init(x, y)

    def track_position(self):
        """Save where the user dropped the bar (the window manager moved it, so read it back)."""
        if self.xwin and self.placed and self.get_mapped():
            root = self.xdisplay.screen().root
            coords = self.xwin.translate_coords(root, 0, 0)
            position = (-coords.x, -coords.y)
            if position != self.position:
                self.position = position
                self.save_position()
        return True

    def save_position(self):
        if self.position:
            config.set("overlay_position", {"x": int(self.position[0]), "y": int(self.position[1])})
