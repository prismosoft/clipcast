---
name: clipcast-clipping
description: AI auto-clipper that transforms long-form videos and podcasts into viral short-form clips. Use when the user asks to clip a video, make shorts from a YouTube video, extract highlights, create TikTok/Reels/Shorts from a long video, or split a podcast into clips. Also use for face-tracking clips, karaoke subtitles, B-roll overlays, podcast split-screen, or camera-switch modes.
---

# ClipCast Clipping

Transform long-form videos into viral short-form clips with AI-powered transcription, face-tracking, karaoke subtitles, and B-roll.

## Prerequisites

- **FFmpeg** installed and in PATH
- **Google Gemini API Key** — get one at https://aistudio.google.com/apikey
- Optional: **Pexels API Key** for B-roll — https://www.pexels.com/api/
- Optional: **HuggingFace Token** for podcast split-screen/camera-switch — https://huggingface.co/settings/tokens

## CLI Command

```bash
clipcast --url "VIDEO_URL" [options]
```

The `clipcast` command should already be installed globally. If not, run directly:

```bash
python /Users/prismosoft/Sites/Clipping/clipcast/main.py --help
```

## Quick Start Examples

```bash
# Basic — 5 clips from a YouTube video
clipcast --url "https://youtube.com/watch?v=VIDEO_ID" --clips 5 --ratio 9:16

# Podcast split-screen (visual, no HF token needed)
clipcast --url "VIDEO_URL" --split-screen --dynamic-split --split-trigger face

# Podcast camera-switch (needs HF_TOKEN)
clipcast --url "VIDEO_URL" --camera-switch

# Faster transcription on Mac (CPU, no CUDA)
clipcast --url "VIDEO_URL" --whisper-device cpu --whisper-compute-type int8

# Use smaller Whisper model for speed
clipcast --url "VIDEO_URL" --whisper-model base --whisper-device cpu --whisper-compute-type int8

# Disable B-roll and BGM
clipcast --url "VIDEO_URL" --no-broll --no-bgm

# Square output for Instagram Feed
clipcast --url "VIDEO_URL" --ratio 1:1 --clips 5

# Landscape output for YouTube
clipcast --url "VIDEO_URL" --ratio 16:9 --clips 5

# TikTok source
clipcast --url "https://www.tiktok.com/@username/video/1234567890" --source tiktok --clips 3
```

## All Options

Run `clipcast --help` for the complete list. Key options:

| Option | Default | Description |
|--------|---------|-------------|
| `--url, -u` | — | Video URL (required) |
| `--source` | youtube | Platform: youtube, tiktok, instagram, gdrive |
| `--clips, -n` | 7 | Number of highlight clips |
| `--ratio, -r` | 9:16 | Output ratio: 9:16, 16:9, 1:1, 3:4, 4:5 |
| `--whisper-model` | large-v3 | Whisper model size |
| `--whisper-device` | cuda | cuda, cpu, or auto |
| `--whisper-compute-type` | float16 | int8 for CPU, float16 for CUDA |
| `--font-style` | HORMOZI | DEFAULT, STORYTELLER, HORMOZI, CINEMATIC |
| `--face-detector` | mediapipe | mediapipe or yolo |
| `--no-broll` | — | Disable B-roll |
| `--no-bgm` | — | Disable background music |
| `--no-subs` | — | Disable subtitles |
| `--split-screen` | — | Podcast split-screen mode |
| `--camera-switch` | — | Podcast camera-switch mode |
| `--hook-v2` | — | Multi-hook intro |
| `--voiceover` | — | AI voice-over commentary |

## Output

Clips are saved to `outputs/` directory:
- `outputs/highlight_rank_N_ready.mp4` — final rendered clips
- `outputs/thumbnail_rank_N.jpg` — auto-generated thumbnails
- `outputs/render_manifest.json` — metadata manifest

## Mac (Apple Silicon) Notes

- Use `--whisper-device cpu --whisper-compute-type int8` for best performance on M-series chips
- No CUDA available; Whisper runs on CPU (fast enough on M4)
- YOLO face detector uses MPS (Metal) via PyTorch automatically