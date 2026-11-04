# System architecture

```
PipeWire ──parec──▶ Stream (Meeting) ─┐                      ┌─▶ TranscriptView (window)
         ──parec──▶ Stream (Me)    ───┼─▶ Engine (Parakeet) ─┼─▶ Overlay (floating bar)
                                      │                      └─▶ Transcript (.md file)
                                      └─ finished sentences ──▶ Translator ─▶ Spanish column
```

## Components

| Component | Module | Responsibility |
| --- | --- | --- |
| Audio sources | `audio.py` | Lists PipeWire sources with `pactl` and resolves the monitor of the default output. |
| Engine | `asr.py` | Loads Parakeet with ONNX Runtime (CUDA or CPU), measures its speed and serializes inference. |
| Stream | `asr.py` | One thread per source: reads audio with `parec`, decodes the growing buffer and commits stable words. |
| Transcript | `transcript.py` | Writes one paragraph per speaker turn to Markdown, incrementally, so nothing is lost on a crash. |
| Translator | `translate.py` | Translates finished sentences in order on its own thread through llama.cpp or Marian. |
| Models | `models.py` | Catalog of downloadable models and the downloader with progress. |
| Hardware | `hardware.py` | Detects the GPU and video memory, decides what fits and what to recommend. |
| UI | `ui/` | GTK4 + libadwaita window, floating bar, settings and meeting viewer. |

## Streaming recognition

Parakeet is not a streaming model, so each `Stream` re-decodes the audio since the last committed point:

1. A reader thread pushes 0.1 s chunks from `parec`; the decode loop takes everything that arrived, so a slow
   read never builds a backlog.
2. Every 0.2 s (0.6 s on CPU) the buffer is decoded. Words that match the previous hypothesis, ignoring case and
   punctuation, are *stable* and shown.
3. A 0.6 s pause commits the sentence. With no pause, stable words older than 1.5 s are committed once the buffer
   passes 8 s (5 s on CPU), and everything is committed at 15 s, so each read stays cheap.
4. A failed read (for example, out of GPU memory) is logged and skipped; captions keep running.

The microphone stream is gated while the meeting speaks, to avoid transcribing echo from speakers.

## Translation

Turns send complete sentences (or the rest of a turn when it closes) to the `Translator` queue, which merges
consecutive fragments of the same turn and passes the previous six fragments as context. A sentence that waits more
than 3 s goes through Marian instead, so the Spanish column never falls behind.

The text translator (`TextAssistant`) reuses the same local LLM: Spanish text is rewritten as clear B2 English
and English text is translated into Spanish.

Both share a single `llama-server` process (`acquire_llama` / `release_llama`), so the model never sits twice in
video memory; it stops when neither the live translation nor the translator page uses it. It is always started
from one long-lived thread, because `PR_SET_PDEATHSIG` fires when the *thread* that forked it exits.

`llama-server` runs as a child process that dies with the app (`PR_SET_PDEATHSIG`), leaves 1 GB of video memory
free, and disables host-visible video memory so it never fills the 256 MB BAR1 window that browsers need to play
video on GPUs without Resizable BAR.

## Threads

The GTK main thread only handles UI. Audio reading, inference, downloads and translation run on worker threads
and report back with `GLib.idle_add`.
