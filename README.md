# SeedVR2 Video Upscaler — RunPod serverless worker

Diffusion **video** upscaler (ByteDance SeedVR2 7B) wrapped as a RunPod serverless
endpoint, for the Local AI Aggregator's `/upscale` feature.

Built by forking the structure of `wlsdml1114/generate_video` (ComfyUI + a custom
`handler.py`) and swapping in the [`numz/ComfyUI-SeedVR2_VideoUpscaler`](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler)
node. ComfyUI graph: `VHS_LoadVideoPath → SeedVR2 (DiT + VAE loaders) → SeedVR2VideoUpscaler → VHS_VideoCombine`.

## API contract
```json
// input
{ "input": { "video_base64": "<raw base64 mp4>", "scale": 2, "seed": 42, "batch_size": 5 } }
// output
{ "video": "<base64 mp4>" }
```
- `scale` (2 or 4): the upscaler targets a shortest-edge resolution; the handler
  `ffprobe`s the input and sets `resolution = round(short_edge × scale)`.
- Output fps + audio are carried from the source clip.

## Deploy (RunPod serverless, from this GitHub repo)
1. New endpoint → import this repo → it builds from `Dockerfile`.
2. **GPU: 48 GB+ (Blackwell — RTX PRO 6000 / 5090)** to match the base image. 7B fp16 ≈ 16 GB.
3. **Container disk ≥ 100 GB** (weights auto-download to `ComfyUI/models/SEEDVR2` on the first job; ~17 GB).
4. **Execution timeout: raise to ~20 min** — the *first* job also downloads the weights (one-time, slow cold start). Later jobs are just the upscale.

## Notes / known tuning points
- Weights are **not baked** into the image (the 7B would exceed RunPod's 30-min image-export limit) → auto-download on first run. For persistent caching across cold workers, mount a network volume at the SeedVR2 cache dir (future optimization).
- `attention_mode` is `sdpa` (stable, always available). `batch_size` must be `4n+1` (1, 5, 9…); higher = better temporal consistency + more VRAM.
- Long clips: SeedVR2 caps practical single-pass length; keep clips short for v1 (the app limits the upload to ~7 MB).
- First-deploy wiring to verify on the maiden run: VHS node output indices (image=0, audio=2) and the exact SeedVR2 model option strings.
