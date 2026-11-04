# Models and hardware

## Catalog

| Id | Kind | Engine | Video memory | Notes |
| --- | --- | --- | --- | --- |
| `parakeet-v2` | transcription | ONNX Runtime CUDA | ~2.9 GB | NVIDIA only. Updates every 0.2 s. |
| `parakeet-v2-int8` | transcription | ONNX Runtime CPU | 0 | Always on the CPU. Updates every 0.6 s. |
| `qwen3-4b` | translation | llama.cpp (Vulkan) | ~2.6 GB | Recommended translation engine. |
| `gemma3-4b` | translation | llama.cpp (Vulkan) | ~2.6 GB | Alternative to Qwen3. |
| `marian` | translation | CTranslate2 CPU | 0 | Literal and instant; also the catch-up fallback. |
| `none` | translation | — | 0 | Translation off. |

Downloads come from Hugging Face (and Argos for Marian), are written to `.part` files and renamed when complete.

## Hardware rules (`hardware.py`)

- NVIDIA is detected with `nvidia-smi`; AMD through `/sys/class/drm/*/device/mem_info_vram_total`; integrated
  GPUs count as "no dedicated GPU".
- Budget for models = total VRAM − 1.5 GB (desktop and browser) − 1 GB kept free.
- A model needing CUDA is blocked without NVIDIA. A GPU model is blocked without a dedicated GPU, or when it does
  not fit the budget together with the other selected model.
- Recommendation: Parakeet v2 when it fits, otherwise Parakeet v2 Lite; then Qwen3 4B when it fits next to it,
  otherwise Marian.

## Measurements behind the defaults

Measured on an RTX 2060 SUPER (8 GB) and an Intel Core i7-9700:

- Word latency (word spoken → word shown), 60 s of continuous speech: median 0.51 s, 90 % under 0.9 s.
- Audio staleness during 200 s of speech with translation running non-stop: median 0.3 s, worst 0.65 s.
- Parakeet v2 Lite on the CPU: 8 s of audio in ~430 ms; 0.7 % of words differ from the full model.
- Qwen3 4B with 1 GB of free VRAM: ~0.6 s per sentence; with 2 GB part of it ran on the CPU and took ~1.7 s.
- Parakeet v2 on the GPU while Qwen3 translates: median decode 64 ms (56 ms alone).
