"""Desktop detection: decides how the floating captions are drawn on this session.

Compositors with layer-shell (Hyprland, Sway, KDE Plasma, wlroots…) get a real overlay surface. GNOME and X11
sessions (Cinnamon, Xfce…) do not support layer-shell, so the whole app runs through X11 (XWayland on GNOME)
and the captions use an undecorated "always on top" X11 window instead. On Windows the native app (winui/) draws
the whole UI, so only `WINDOWS` and `NO_CONSOLE` apply there.
"""
import os
import subprocess
import sys

LAYER_SHELL, X11 = "layer-shell", "x11"
WINDOWS = sys.platform == "win32"
# Console programs (nvidia-smi, llama-server) started from the app must not open a console window on Windows
NO_CONSOLE = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NO_LAYER_SHELL = ("gnome", "unity", "cinnamon", "budgie", "pantheon", "mate", "xfce")


def _has_layer_shell_typelib():
    import gi

    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        return True
    except ValueError:
        return False


def overlay_backend():
    forced = os.environ.get("LAIAUDIO_OVERLAY")
    if forced in (LAYER_SHELL, X11):
        return forced
    if os.environ.get("XDG_SESSION_TYPE") == "x11" or not os.environ.get("WAYLAND_DISPLAY"):
        return X11
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if any(name in desktop for name in _NO_LAYER_SHELL) or not _has_layer_shell_typelib():
        return X11
    return LAYER_SHELL


def prepare():
    """Call before GTK starts: the X11 overlay needs the whole app on the X11 backend."""
    if overlay_backend() == X11:
        os.environ["GDK_BACKEND"] = "x11"
