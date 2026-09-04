"""
audio2video.pipeline — Transcribe audio → Gemini scene analysis → B-roll fetch → render

Takes any audio file (song, voiceover, podcast, narration) and produces a
video composed entirely of B-roll stock footage synced to the audio, with
karaoke subtitles.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Reuse existing infrastructure from clipping/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib.util

_STUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "clipping", "studio")


def _load_studio_module(file_name: str, module_alias: str):
    """Load a clipping/studio/*.py module by file path (same pattern as the repo)."""
    module_path = os.path.join(_STUDIO_DIR, file_name)
    spec = importlib.util.spec_from_file_location(module_alias, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


from clipping.engine import transcribe_video, transcribe_video_groq, _generate_json_with_retry
_broll_mod = _load_studio_module("broll.py", "clipcast_broll")
download_pexels_broll = _broll_mod.download_pexels_broll
crop_center_broll = _broll_mod.crop_center_broll
from audio2video.broll_scorer import search_pexels_with_scoring, BrollSegment
from audio2video.renderer import render_audio_video
from audio2video.gemini_prompt import build_scene_analysis_prompt, build_scene_analysis_schema


def _get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", audio_path,
        ],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def transcribe_audio(
    audio_path: str,
    max_words_per_subtitle: int = 5,
    model_size: str = "large-v3",
    device: str = "cpu",
    compute_type: str = "int8",
) -> tuple[str, list[dict]]:
    """
    Transcribe an audio file.

    Order of preference:
    1. Groq API (if GROQ_API_KEY is set in environment) — fast cloud faster-whisper
    2. Local Faster-Whisper (CPU/CUDA) — fallback

    Both paths return the exact same (transkrip_lengkap, data_segmen) structure.
    """
    groq_api_key = os.environ.get("GROQ_API_KEY", "")

    if groq_api_key:
        print("[1/4] Transcribing via Groq API (cloud faster-whisper)...")
        try:
            return transcribe_video_groq(
                audio_path,
                max_words_per_subtitle=max_words_per_subtitle,
                api_key=groq_api_key,
                model_size=model_size,
            )
        except Exception as groq_err:
            print(f"   ⚠️ Groq API failed ({groq_err}). Falling back to local Whisper...")

    print("[1/4] Transcribing audio with Faster-Whisper (local)...")
    return transcribe_video(
        audio_path,
        max_words_per_subtitle=max_words_per_subtitle,
        model_size=model_size,
        device=device,
        compute_type=compute_type,
    )


def analyze_scenes(
    transkrip_lengkap: str,
    audio_duration: float,
    api_key: str,
    gemini_model: str = "gemini-2.0-flash",
    fallback_model: str = "gemini-2.5-flash",
    target_segment_duration: float = 20.0,
) -> list[dict]:
    """
    Send transcript to Gemini and get back a scene timeline with B-roll queries.

    Returns a list of segments:
    [
        {
            "start": 0.0,
            "end": 25.3,
            "lyrics_excerpt": "The harbor burned...",
            "search_queries": ["beirut port explosion", "harbor fire disaster"],
            "mood": "dramatic",
            "transition": "crossfade"
        },
        ...
    ]
    """
    print("[2/4] Analyzing content with Gemini AI for scene breakdown...")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    prompt = build_scene_analysis_prompt(
        transkrip_lengkap, audio_duration, target_segment_duration
    )
    schema = build_scene_analysis_schema()

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
    )

    result = _generate_json_with_retry(
        client, gemini_model, fallback_model, prompt, config
    )

    segments = result.get("segments", [])

    if not segments:
        raise RuntimeError("Gemini returned no scene segments. Check your API key and try again.")

    print(f"   ✅ Gemini generated {len(segments)} scene segments")
    for i, seg in enumerate(segments):
        queries = seg.get("search_queries", [])
        print(f"   🎬 Segment {i+1}: {seg['start']:.1f}s-{seg['end']:.1f}s "
              f"| queries: {queries} | mood: {seg.get('mood', 'unknown')}")

    return segments


def fetch_broll_segments(
    segments: list[dict],
    ratio: str,
    pexels_api_key: str,
    broll_strict: bool = False,
    gemini_api_key: str = "",
    gemini_model: str = "gemini-2.0-flash",
    output_dir: str = "outputs",
) -> list[BrollSegment]:
    """
    For each scene segment, search Pexels and download the best-matching B-roll.

    Uses metadata scoring by default. With broll_strict=True, also sends
    video thumbnails to Gemini for visual relevance scoring.
    """
    print("[3/4] Fetching B-roll footage from Pexels...")

    if not pexels_api_key:
        print("   ⚠️ No PEXELS_API_KEY found. B-roll will be skipped.")
        return []

    os.makedirs(output_dir, exist_ok=True)
    broll_segments: list[BrollSegment] = []

    for i, seg in enumerate(segments):
        queries = seg.get("search_queries", [])
        if not queries:
            queries = [seg.get("search_query", "abstract background")]

        duration = seg["end"] - seg["start"]
        print(f"\n   🎥 Segment {i+1}/{len(segments)}: {seg['start']:.1f}s-{seg['end']:.1f}s "
              f"({duration:.1f}s) | queries: {queries}")

        best_video = search_pexels_with_scoring(
            queries=queries,
            ratio=ratio,
            pexels_api_key=pexels_api_key,
            segment_context=seg.get("lyrics_excerpt", ""),
            strict=broll_strict,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
        )

        if best_video is None:
            print(f"   ⚠️ No B-roll found for segment {i+1}, will use solid color fallback")
            broll_segments.append(BrollSegment(
                start=seg["start"],
                end=seg["end"],
                filepath=None,
                search_queries=queries,
                mood=seg.get("mood", "neutral"),
                transition=seg.get("transition", "crossfade"),
                lyrics_excerpt=seg.get("lyrics_excerpt", ""),
            ))
            continue

        output_filename = os.path.join(output_dir, f"broll_seg_{i:03d}.mp4")
        success = download_pexels_broll_from_url(best_video["download_url"], output_filename)

        if success:
            print(f"   ✅ Downloaded: {best_video.get('title', 'untitled')} "
                  f"(score: {best_video.get('score', 'N/A')})")
            broll_segments.append(BrollSegment(
                start=seg["start"],
                end=seg["end"],
                filepath=output_filename,
                search_queries=queries,
                mood=seg.get("mood", "neutral"),
                transition=seg.get("transition", "crossfade"),
                lyrics_excerpt=seg.get("lyrics_excerpt", ""),
            ))
        else:
            print(f"   ⚠️ Download failed for segment {i+1}")
            broll_segments.append(BrollSegment(
                start=seg["start"],
                end=seg["end"],
                filepath=None,
                search_queries=queries,
                mood=seg.get("mood", "neutral"),
                transition=seg.get("transition", "crossfade"),
                lyrics_excerpt=seg.get("lyrics_excerpt", ""),
            ))

    return broll_segments


def download_pexels_broll_from_url(url: str, output_filename: str) -> bool:
    """Download a Pexels video from a direct URL."""
    import urllib.request
    import shutil

    from .ssl_ctx import get_ssl_context

    try:
        temp_path = output_filename + ".part"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=get_ssl_context()) as response, open(temp_path, "wb") as f:
            shutil.copyfileobj(response, f)
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) < 1024:
            raise RuntimeError(f"downloaded file too small ({os.path.getsize(temp_path) if os.path.exists(temp_path) else 0} bytes)")
        # Verify the file is a readable video via ffprobe
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", temp_path],
            capture_output=True, text=True,
        )
        probe_ok = False
        try:
            json.loads(probe.stdout).get("format", {}).get("duration")
            probe_ok = True
        except Exception:
            probe_ok = False
        if not probe_ok:
            raise RuntimeError("downloaded file is not a readable video (ffprobe failed)")
        os.replace(temp_path, output_filename)
        return True
    except Exception as e:
        if os.path.exists(output_filename + ".part"):
            os.remove(output_filename + ".part")
        if os.path.exists(output_filename):
            os.remove(output_filename)
        print(f"   ⚠️ Download error: {e}")
        return False


def run_pipeline(
    audio_path: str,
    ratio: str = "9:16",
    output_path: str = "outputs/audio_video.mp4",
    font_style: str = "HORMOZI",
    words_per_sub: int = 5,
    whisper_model: str = "large-v3",
    whisper_device: str = "cpu",
    whisper_compute_type: str = "int8",
    gemini_model: str = "gemini-2.0-flash",
    gemini_fallback_model: str = "gemini-2.5-flash",
    broll_strict: bool = False,
    no_broll: bool = False,
    no_subs: bool = False,
    target_segment_duration: float = 20.0,
    render_height: int = 1080,
    video_crf: int = 20,
    video_preset: str = "medium",
):
    """Main pipeline: audio → transcribe → analyze → fetch B-roll → render."""

    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    google_api_key = os.environ.get("GOOGLE_API_KEY", "")
    pexels_api_key = os.environ.get("PEXELS_API_KEY", "")

    if not google_api_key:
        raise RuntimeError("GOOGLE_API_KEY not set. Add it to your .env file.")

    # Step 1: Get audio duration
    audio_duration = _get_audio_duration(audio_path)
    print(f"   📁 Audio duration: {audio_duration:.1f}s ({audio_duration/60:.1f} min)")

    # Step 2: Transcribe
    transkrip_lengkap, data_segmen = transcribe_audio(
        audio_path,
        max_words_per_subtitle=words_per_sub,
        model_size=whisper_model,
        device=whisper_device,
        compute_type=whisper_compute_type,
    )

    if not transkrip_lengkap.strip():
        raise RuntimeError("Whisper produced no transcription. The audio may be silent or corrupted.")

    print(f"   ✅ Transcription complete: {len(data_segmen)} word segments")

    # Step 3: Gemini scene analysis
    segments = analyze_scenes(
        transkrip_lengkap,
        audio_duration,
        google_api_key,
        gemini_model=gemini_model,
        fallback_model=gemini_fallback_model,
        target_segment_duration=target_segment_duration,
    )

    # Save scene analysis for debugging/reuse
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    scene_path = os.path.join(os.path.dirname(output_path) or ".", "scene_analysis.json")
    with open(scene_path, "w") as f:
        json.dump({"segments": segments, "audio_duration": audio_duration}, f, indent=2)
    print(f"   💾 Scene analysis saved to {scene_path}")

    # Step 4: Fetch B-roll
    if no_broll:
        print("[3/4] B-roll disabled (--no-broll)")
        broll_segments = []
    else:
        broll_segments = fetch_broll_segments(
            segments,
            ratio=ratio,
            pexels_api_key=pexels_api_key,
            broll_strict=broll_strict,
            gemini_api_key=google_api_key,
            gemini_model=gemini_model,
            output_dir=os.path.join(os.path.dirname(output_path) or ".", "broll_cache"),
        )

    # Step 5: Render
    print("[4/4] Rendering final video...")
    render_audio_video(
        audio_path=audio_path,
        broll_segments=broll_segments,
        data_segmen=data_segmen,
        ratio=ratio,
        output_path=output_path,
        font_style=font_style,
        words_per_sub=words_per_sub,
        no_subs=no_subs,
        render_height=render_height,
        video_crf=video_crf,
        video_preset=video_preset,
        audio_duration=audio_duration,
    )

    print(f"\n✅ Done! Video saved to: {output_path}")
    return output_path