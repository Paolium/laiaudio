# Development workflow

## Before coding

1. Read `AGENTS.md` and the relevant document in `docs/`.
2. Check the worktree with `git status`.

## Running from the repository

The installed app lives in `~/.local/share/laiaudio/venv`. To try local changes, reinstall the package into it:

```bash
~/.local/share/laiaudio/venv/bin/pip install --no-deps --force-reinstall .
laiaudio
```

Or run straight from the source tree with the same interpreter:

```bash
LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so ~/.local/share/laiaudio/venv/bin/python -m laiaudio
```

`LD_PRELOAD` is required by gtk4-layer-shell. Set `LAIAUDIO_MODELS=<empty folder>` to see the first-run flow.

## Verification

- Byte-compile everything: `~/.local/share/laiaudio/venv/bin/python -m py_compile laiaudio/*.py laiaudio/ui/*.py`.
- Check the log: `~/.cache/laiaudio/app.log`.
- When touching `asr.py` or `translate.py`, measure latency with continuous speech (median word latency and audio
  staleness) and compare with `docs/models.md`.
- When touching the GPU path, check `nvidia-smi` (VRAM and BAR1) while a video plays in the browser.
- There is no automated test suite yet; report what was verified by hand.
