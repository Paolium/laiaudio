# Product context

## Purpose

Laiaudio turns the audio of any meeting into live captions you can read while people speak, translates them into
Spanish when you need it, and leaves a clean Markdown transcript at the end. It exists for people who work in
English-speaking meetings and want to follow every word without sending their conversations to a cloud service.

## Primary user

A professional on a Linux desktop (Arch / Omarchy) who joins video calls in English, often as a non-native speaker,
and needs real-time captions, a quick translation and a written record of the meeting.

## What the app does

- Captures the meeting audio (whatever plays on the default output) and, optionally, the user's microphone.
- Transcribes English in real time with Parakeet and shows stable words as they are confirmed.
- Shows the captions in the main window and on a floating bar over any app.
- Translates finished sentences into Mexican Spanish with a local LLM (or Marian, literal and instant).
- Saves one Markdown file per meeting and lets the user search, rename, preview, copy and delete them.
- Detects the hardware and only allows model combinations that fit the GPU and video memory.

## Principles

- **Local only.** Audio and text never leave the machine. The network is used only to download models.
- **Readable in real time.** Captions must never fall behind: the pipeline always catches up with the present
  instead of queueing old audio, and the floating bar never jumps or shrinks mid-sentence.
- **Honest about hardware.** The app recommends what fits and blocks what does not, instead of letting a user pick a
  model that will crash the GPU or the browser.
- **Calm interface.** Few controls, clear states, the Paolium dark palette and no visual noise.

## Non-goals

- Cloud transcription or translation, accounts, sync or analytics.
- Speaker diarization (telling meeting participants apart). The app separates "Meeting" and "Me" only.
- Languages other than English speech and Spanish translation (for now).
- Windows or macOS builds.
