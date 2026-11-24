"""Audio sources and capture: PipeWire/PulseAudio (pactl, parec) on Linux, WASAPI on Windows (wasapi.py)."""
import json
import subprocess

from .desktop import WINDOWS

NO_OUTPUT = ("No audio output found (check the Windows sound settings)" if WINDOWS else
             "No audio output found (is PipeWire running?)")


def _pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5).stdout


def _wasapi(query, default):
    """query(wasapi), or `default` when Windows audio is not available (no device, service stopped…)."""
    from . import wasapi

    try:
        return query(wasapi)
    except OSError as e:
        print(f"Audio devices: {e}", flush=True)
        return default


def list_sources():
    """[(name, description, is_monitor)] for every audio source."""
    if WINDOWS:
        return _wasapi(lambda w: [(i, name, True) for i, name in w.outputs()] +
                                 [(i, name, False) for i, name in w.inputs()], [])
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
    if WINDOWS:  # the id of the default output; Capture records what plays on it (loopback)
        return _wasapi(lambda w: w.default_output(), None)
    sink = _pactl("get-default-sink").strip()
    return f"{sink}.monitor" if sink else None


def mic_source(setting):
    """None = the system default microphone."""
    return None if setting == "auto" else setting


class Capture:
    """Mono float32 audio from a source (None = default microphone), read in blocks of bytes until closed."""

    def __init__(self, device, client_name, rate):
        self.device, self.rate = device, rate
        if WINDOWS:
            self.closed = False
            self.wasapi = None
            return
        cmd = ["parec", "--raw", "--format=float32le", f"--rate={rate}", "--channels=1",
               "--latency-msec=50", f"--client-name={client_name}"]
        if device:
            cmd.append(f"--device={device}")
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self, size):
        """Up to `size` bytes; b"" when the capture ended or was closed."""
        if not WINDOWS:
            return self.proc.stdout.read(size)
        from . import wasapi

        try:
            if self.closed:
                return b""
            if self.wasapi is None:  # opened by the thread that reads: COM objects stay on one thread
                self.wasapi = wasapi.Capture(self.device, self.rate)
            return self.wasapi.read(size)
        except OSError as e:  # device unplugged or disabled: end like parec would
            print(f"Audio capture ({self.device or 'default microphone'}): {e}", flush=True)
            self.closed = True
            return b""
        finally:
            if self.closed and self.wasapi:
                self.wasapi.close()
                self.wasapi = None

    def close(self):
        if not WINDOWS:
            self.proc.terminate()
            return
        self.closed = True  # the reading thread releases the device after its current chunk
