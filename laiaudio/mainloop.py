"""Hop from a worker thread to the main thread: GLib's main loop in the GTK app, a plain queue in the Windows service.

Workers call `idle_add(callback, *args)`; the callback runs once on the main thread. The GTK app needs nothing
else. The Windows service (`service.py`), which has no GTK, calls `use_queue()` before starting any worker and
runs the callbacks from that queue.
"""
import queue

_queue = None


def use_queue():
    """Run callbacks through a queue instead of GLib; return it for the main thread to drain."""
    global _queue
    _queue = queue.SimpleQueue()
    return _queue


def idle_add(callback, *args):
    if _queue is None:
        from gi.repository import GLib

        GLib.idle_add(callback, *args)
    else:
        _queue.put((callback, args))
