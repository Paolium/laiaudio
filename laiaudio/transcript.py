"""The meeting as Markdown: one paragraph per speaker turn."""
import threading
from datetime import datetime

MAX_PARAGRAPH = 600  # characters per paragraph before starting a new one
MEETING, ME = "Meeting", "Me"  # speakers: what plays on the output, and the microphone


class Transcript:
    def __init__(self, folder):
        self.started = datetime.now()
        self.folder = folder
        self.path = folder / f"{self.started:%Y-%m-%d_%H-%M}.md"
        self.file = None
        self.open = {}  # speaker -> [start, text]
        self.lock = threading.Lock()

    def add(self, speaker, start, text, end_of_turn):
        with self.lock:
            para = self.open.setdefault(speaker, [start, ""])
            para[1] = f"{para[1]} {text}".strip()
            if end_of_turn or len(para[1]) > MAX_PARAGRAPH:
                self._flush(speaker)

    def _flush(self, speaker):
        start, text = self.open.pop(speaker)
        if not text:
            return
        if self.file is None:
            self.folder.mkdir(parents=True, exist_ok=True)
            self.file = self.path.open("a", encoding="utf-8")
            self.file.write(f"# Meeting — {self.started:%Y-%m-%d %H:%M}\n\n")
        self.file.write(f"**[{datetime.fromtimestamp(start):%H:%M:%S}] {speaker}:** {text}\n\n")
        self.file.flush()

    def close(self):
        """Close the file; return its path, or None when nothing was transcribed."""
        with self.lock:
            for speaker in sorted(self.open, key=lambda k: self.open[k][0]):
                self._flush(speaker)
            if not self.file:
                return None
            self.file.write(f"_End: {datetime.now():%H:%M}_\n")
            self.file.close()
            return self.path
