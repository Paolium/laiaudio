"""PipeWire/PulseAudio sources (through pactl)."""
import json
import subprocess


def _pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5).stdout


def list_sources():
    """[(name, description, is_monitor)] for every audio source."""
    try:
        sources = json.loads(_pactl("--format=json", "list", "sources"))
    except (ValueError, OSError, subprocess.SubprocessError):
        return []
    # On PipeWire, monitors carry the name of their output in "monitor_source"
    return [(s["name"], s.get("description") or s["name"], bool(s.get("monitor_source")))
            for s in sources]


def outputs():
    """Output monitors: what plays on each output (speakers, headphones…)."""
    return [(name, desc) for name, desc, monitor in list_sources() if monitor]


def inputs():
    """Microphones and other real inputs."""
    return [(name, desc) for name, desc, monitor in list_sources() if not monitor]


def meeting_source(setting):
    """Source with the meeting audio: the monitor of the default output when set to "auto"."""
    if setting != "auto":
        return setting
    sink = _pactl("get-default-sink").strip()
    return f"{sink}.monitor" if sink else None


def mic_source(setting):
    """None = the system default microphone."""
    return None if setting == "auto" else setting
