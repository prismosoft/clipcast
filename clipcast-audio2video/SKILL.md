---
name: clipcast-audio2video
description: Transform any audio file into a B-roll video with subtitles. Takes an MP3/WAV of a song, narration, podcast, or voiceover and generates a video composed of stock B-roll footage matched to the audio content, with karaoke subtitles. Use when the user asks to create a video from audio, make a lyric video, turn narration into a documentary video, add B-roll to audio, or generate visuals for a song.
---

# ClipCast Audio2Video

Transform any audio file (song, narration, podcast, voiceover) into a video composed of B-roll stock footage synced to the audio, with karaoke subtitles.

## Prerequisites

- **FFmpeg** installed and in PATH
- **Google Gemini API Key** — get one at https://aistudio.google.com/apikey
- **Pexels API Key** — required for B-roll — https://www.pexels.com/api/
- API keys must be set in `.env` at `/Users/prismosoft/Sites/Clipping/clipcast/.env`

## CLI Command

```bash
clipcast-audio --audio "path/to/audio.mp3" [options]
```

The `clipcast-audio` command should already be installed globally. If not, run directly:

```bash
python /Users/prismosoft/Sites/Clipping/clipcast/audio2video.py --help
```

## Quick Start Examples

```bash
# Song to vertical 9:16 video with B-roll
clipcast-audio --audio "song.mp3" --ratio 9:16

# Documentary narration to landscape 16:9, strict B-roll matching
clipcast-audio --audio "narration.mp3" --ratio 16:9 --broll-strict

# Podcast clip, no B-roll (just subtitles + dark background)
clipcast-audio --audio "podcast.mp3" --no-broll

# Song with cinematic font and fewer words per subtitle
clipcast-audio --audio "song.mp3" --font-style CINEMATIC --words-per-sub 3

# Faster transcription with smaller Whisper model
clipcast-audio --audio "song.mp3" --whisper-model base --whisper-device cpu --whisper-compute-type int8

# No subtitles (B-roll only)
clipcast-audio --audio "song.mp3" --no-subs

# Custom output path
clipcast-audio --audio "song.mp3" --output "my_output/video.mp4"
```

## All Options

Run `clipcast-audio --help` for the complete list. Key options:

| Option | Default | Description |
|--------|---------|-------------|
| `--audio, -a` | — | Path to audio file (required) |
| `--ratio, -r` | 9:16 | Output ratio: 9:16, 16:9, 1:1, 3:4, 4:5 |
| `--output, -o` | outputs/audio_video.mp4 | Output video path |
| `--no-broll` | — | Disable B-roll (solid color background) |
| `--broll-strict` | — | Use Gemini visual scoring for B-roll (slower, more accurate) |
| `--no-subs` | — | Disable subtitle overlay |
| `--words-per-sub` | 5 | Max words per subtitle group |
| `--font-style` | HORMOZI | DEFAULT, STORYTELLER, HORMOZI, CINEMATIC |
| `--target-segment-duration` | 20 | Seconds per B-roll segment |
| `--whisper-model` | large-v3 | Whisper model size |
| `--whisper-device` | cpu | cuda, cpu, or auto |
| `--whisper-compute-type` | int8 | int8 for CPU, float16 for CUDA |
| `--gemini-model` | gemini-3.6-flash | Gemini model for scene analysis |
| `--video-crf` | 20 | Quality (lower = sharper) |
| `--video-preset` | medium | Encoding preset |
| `--render-height` | 1080 | Output video height in pixels |

## How It Works

1. **Whisper** transcribes the audio → word-level timestamps
2. **Gemini** analyzes the transcript → breaks it into visual scenes with B-roll search queries
3. **Pexels** fetches B-roll footage → scored by relevance (metadata or Gemini visual scoring)
4. **FFmpeg** renders → full-screen B-roll with Ken Burns + crossfades + karaoke subtitles + original audio

## B-Roll Matching

Two modes for B-roll selection:

- **Default (metadata scoring):** Scores Pexels results by tag/title/description overlap with the search query. Fast, free, no extra API calls.
- **Strict (`--broll-strict`):** Additionally sends video thumbnails to Gemini for visual relevance scoring. Slower but more accurate — Gemini sees the actual footage and rates how well it matches the audio content.

Gemini generates 2-3 fallback search queries per scene, ordered from most specific to most generic. If a query returns low-scoring results, it tries the next fallback.

## Output

- Video saved to `--output` path (default: `outputs/audio_video.mp4`)
- Scene analysis saved to `outputs/scene_analysis.json` for debugging
- B-roll clips cached in `outputs/broll_cache/`

## Mac (Apple Silicon) Notes

- Use `--whisper-device cpu --whisper-compute-type int8` (default for Mac)
- No CUDA available; Whisper runs on CPU
- M4 chips handle `large-v3` model in ~2-3 min per 10 min of audio
- Use `--whisper-model base` for faster (but less accurate) transcription