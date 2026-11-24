"""Windows audio (WASAPI) through COM with ctypes: list devices and capture mono float32 at any rate.

Windows converts from whatever format the device uses (AUTOCONVERTPCM), so every microphone and output works.
An output is captured through loopback: what plays on it. Only imported on Windows.
"""
import ctypes
import time
import uuid
from ctypes import POINTER, byref, c_void_p, wintypes

_ole32 = ctypes.windll.ole32
_ole32.CoCreateInstance.argtypes = [c_void_p, c_void_p, wintypes.DWORD, c_void_p, POINTER(c_void_p)]
_ole32.CoCreateInstance.restype = ctypes.HRESULT
_ole32.CoTaskMemFree.argtypes = [c_void_p]
_ole32.PropVariantClear.argtypes = [c_void_p]

_RENDER, _CAPTURE = 0, 1                 # EDataFlow
_CONSOLE = 0                             # ERole
_DEVICE_STATE_ACTIVE = 1
_CLSCTX_ALL = 0x17
_STREAMFLAGS = (0x80000000    # AUTOCONVERTPCM: Windows converts to the format we ask for
                | 0x08000000  # SRC_DEFAULT_QUALITY: good resampling
                | 0x00080000)  # NOPERSIST
_LOOPBACK = 0x00020000
_BUFFER_SILENT = 0x2
_WAVE_FORMAT_IEEE_FLOAT = 3


def _guid(text):
    return (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)


_CLSID_ENUMERATOR = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
_IID_ENUMERATOR = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
_IID_ENDPOINT = _guid("1BE09788-6894-4089-8586-9A2A6C265AC5")
_IID_AUDIO_CLIENT = _guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")
_IID_CAPTURE_CLIENT = _guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317")


class _PropertyKey(ctypes.Structure):
    _fields_ = [("fmtid", ctypes.c_byte * 16), ("pid", wintypes.DWORD)]


_FRIENDLY_NAME = _PropertyKey(_guid("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14)


class _PropVariant(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("reserved", ctypes.c_ushort * 3), ("pwszVal", ctypes.c_wchar_p),
                ("padding", ctypes.c_void_p)]


class _WaveFormat(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD), ("nSamplesPerSec", wintypes.DWORD),
                ("nAvgBytesPerSec", wintypes.DWORD), ("nBlockAlign", wintypes.WORD),
                ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]


_P = c_void_p  # every pointer argument (byref(...), interface pointers, NULL) is passed as void*


def _call(obj, index, argtypes, *args):
    """Call method number `index` of the COM interface `obj` (raises OSError on a failed HRESULT)."""
    vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(vtable[index])(obj, *args)


def _release(obj):
    if obj:
        vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
        ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)(vtable[2])(obj)


def init_thread():
    """COM for the calling thread (multithreaded; the GTK thread already has its own, which is fine too)."""
    ctypes.windll.ole32.CoInitializeEx(None, 0)


def _enumerator():
    init_thread()
    enumerator = c_void_p()
    _ole32.CoCreateInstance(byref(_CLSID_ENUMERATOR), None, _CLSCTX_ALL, byref(_IID_ENUMERATOR), byref(enumerator))
    return enumerator


def _device_id(device):
    text = ctypes.c_wchar_p()
    _call(device, 5, [_P], byref(text))  # IMMDevice::GetId
    try:
        return text.value
    finally:
        _ole32.CoTaskMemFree(text)


def _friendly_name(device):
    store, value = c_void_p(), _PropVariant()
    _call(device, 4, [wintypes.DWORD, _P], 0, byref(store))  # IMMDevice::OpenPropertyStore(STGM_READ)
    try:
        _call(store, 5, [_P, _P], byref(_FRIENDLY_NAME), byref(value))  # IPropertyStore::GetValue
        return value.pwszVal or "Audio device"
    finally:
        _ole32.PropVariantClear(byref(value))
        _release(store)


def devices(flow):
    """[(id, name)] of the active outputs (flow 0) or inputs (flow 1)."""
    enumerator, collection, found = _enumerator(), c_void_p(), []
    try:
        _call(enumerator, 3, [ctypes.c_int, wintypes.DWORD, _P], flow, _DEVICE_STATE_ACTIVE, byref(collection))  # EnumAudioEndpoints
        count = wintypes.UINT()
        _call(collection, 3, [_P], byref(count))
        for i in range(count.value):
            device = c_void_p()
            _call(collection, 4, [wintypes.UINT, _P], i, byref(device))
            try:
                found.append((_device_id(device), _friendly_name(device)))
            finally:
                _release(device)
    finally:
        _release(collection)
        _release(enumerator)
    return found


def outputs():
    return devices(_RENDER)


def inputs():
    return devices(_CAPTURE)


def default_output():
    """Id of the default output (speakers or headphones), or None."""
    enumerator, device = _enumerator(), c_void_p()
    try:
        _call(enumerator, 4, [ctypes.c_int, ctypes.c_int, _P], _RENDER, _CONSOLE, byref(device))  # GetDefaultAudioEndpoint
        return _device_id(device)
    except OSError:
        return None
    finally:
        _release(device)
        _release(enumerator)


class Capture:
    """Mono float32 samples from a device: an input, or what plays on an output (loopback). One thread uses it."""

    def __init__(self, device_id, rate):
        """device_id None = the default microphone."""
        self.rate = rate
        self.client = self.capture = None
        enumerator, device = _enumerator(), c_void_p()
        try:
            if device_id:
                _call(enumerator, 5, [wintypes.LPCWSTR, _P], device_id, byref(device))  # GetDevice
            else:
                _call(enumerator, 4, [ctypes.c_int, ctypes.c_int, _P], _CAPTURE, _CONSOLE, byref(device))
            self.loopback = self._flow(device) == _RENDER
            client = c_void_p()
            _call(device, 3, [_P, wintypes.DWORD, _P, _P], byref(_IID_AUDIO_CLIENT), _CLSCTX_ALL, None, byref(client))  # Activate
            self.client = client
        finally:
            _release(device)
            _release(enumerator)
        fmt = _WaveFormat(_WAVE_FORMAT_IEEE_FLOAT, 1, rate, rate * 4, 4, 32, 0)
        flags = _STREAMFLAGS | (_LOOPBACK if self.loopback else 0)
        _call(self.client, 3, [ctypes.c_int, wintypes.DWORD, ctypes.c_longlong, ctypes.c_longlong, _P, _P],
              0, flags, 2_000_000, 0, byref(fmt), None)  # Initialize: shared, 200 ms buffer
        capture = c_void_p()
        _call(self.client, 14, [_P, _P], byref(_IID_CAPTURE_CLIENT), byref(capture))  # GetService
        self.capture = capture
        _call(self.client, 10, [])  # Start
        self.pending = bytearray()
        self.last_data = time.monotonic()

    @staticmethod
    def _flow(device):
        endpoint, flow = c_void_p(), ctypes.c_int()
        _call(device, 0, [_P, _P], byref(_IID_ENDPOINT), byref(endpoint))  # QueryInterface(IMMEndpoint)
        try:
            _call(endpoint, 3, [_P], byref(flow))  # IMMEndpoint::GetDataFlow
        finally:
            _release(endpoint)
        return flow.value

    def read(self, size):
        """Exactly `size` bytes. While nothing plays on an output Windows sends no data: that time is silence."""
        while len(self.pending) < size:
            if not self._take_packet():
                time.sleep(0.01)
                idle = time.monotonic() - self.last_data
                if self.loopback and idle > 0.1:
                    self.pending += bytes(int(idle * self.rate) * 4)
                    self.last_data = time.monotonic()
        data, self.pending = bytes(self.pending[:size]), self.pending[size:]
        return data

    def _take_packet(self):
        frames = wintypes.UINT()
        _call(self.capture, 5, [_P], byref(frames))  # GetNextPacketSize
        if not frames.value:
            return False
        data, flags = c_void_p(), wintypes.DWORD()
        _call(self.capture, 3, [_P] * 5, byref(data), byref(frames), byref(flags), None, None)  # GetBuffer
        size = frames.value * 4
        self.pending += bytes(size) if flags.value & _BUFFER_SILENT else ctypes.string_at(data, size)
        _call(self.capture, 4, [wintypes.UINT], frames.value)  # ReleaseBuffer
        self.last_data = time.monotonic()
        return True

    def close(self):
        if self.client:
            try:
                _call(self.client, 11, [])  # Stop
            except OSError:
                pass  # the device was unplugged
        _release(self.capture)
        _release(self.client)
        self.client = self.capture = None
