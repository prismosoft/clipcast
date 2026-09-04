#!/usr/bin/env python3
"""
audio2video.py — Transform any audio file into a B-roll video with subtitles.

Usage:
    python audio2video.py --audio "song.mp3" --ratio 9:16
    python audio2video.py --audio "narration.mp3" --ratio 16:9  # Gemini visual scoring is default
    python audio2video.py --audio "podcast.mp3" --no-broll --no-subs

Input: Any audio file (MP3, WAV, M4A, FLAC, etc.)
Output: MP4 video with B-roll stock footage + karaoke subtitles + original audio
"""

import argparse
import os
import sys

# Ensure we can import from the project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

# Ensure all HTTPS clients (urllib, httpx/Gemini) use certifi CA certs.
# Framework Python builds may ship without a configured CA bundle.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

from audio2video.pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="🎬 ClipCast Audio2Video — Transform any audio into a B-roll video with subtitles.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic — song to 9:16 video with B-roll
  python audio2video.py --audio "song.mp3" --ratio 9:16

  # Documentary narration, 16:9, strict B-roll matching
  python audio2video.py --audio "narration.mp3" --ratio 16:9  # Gemini visual scoring is default

  # Podcast clip, no B-roll (just subtitles + dark background)
  python audio2video.py --audio "podcast.mp3" --no-broll

  # Custom font style and subtitle settings
  python audio2video.py --audio "song.mp3" --font-style CINEMATIC --words-per-sub 3

  # Use smaller Whisper model for faster transcription
  python audio2video.py --audio "song.mp3" --whisper-model base --whisper-device cpu --whisper-compute-type int8
        """,
    )

    # Required
    parser.add_argument(
        "--audio", "-a",
        required=True,
        help="Path to audio file (MP3, WAV, M4A, FLAC, etc.)",
    )

    # Output settings
    parser.add_argument(
        "--ratio", "-r",
        default="9:16",
        choices=["9:16", "16:9", "1:1", "3:4", "4:5"],
        help="Output aspect ratio (default: 9:16)",
    )
    parser.add_argument(
        "--output", "-o",
        default="outputs/audio_video.mp4",
        help="Output video file path (default: outputs/audio_video.mp4)",
    )
    parser.add_argument(
        "--render-height",
        type=int,
        default=1080,
        help="Output video height in pixels (default: 1080)",
    )

    # B-roll settings
    parser.add_argument(
        "--no-broll",
        action="store_true",
        help="Disable B-roll (use solid color background)",
    )
    parser.add_argument(
        "--broll-fast",
        action="store_true",
        help="Skip Gemini visual scoring — metadata-only matching (faster, less accurate). "
             "Default is Gemini visual scoring for best relevance.",
    )
    parser.add_argument(
        "--target-segment-duration",
        type=float,
        default=20.0,
        help="Target duration for each B-roll segment in seconds (default: 20)",
    )

    # Subtitle settings
    parser.add_argument(
        "--no-subs",
        action="store_true",
        help="Disable subtitle overlay",
    )
    parser.add_argument(
        "--words-per-sub",
        type=int,
        default=5,
        help="Max words per subtitle group (default: 5)",
    )
    parser.add_argument(
        "--font-style",
        default="HORMOZI",
        choices=["DEFAULT", "STORYTELLER", "HORMOZI", "CINEMATIC"],
        help="Font style for subtitles (default: HORMOZI)",
    )

    # Whisper settings
    parser.add_argument(
        "--whisper-model",
        default="large-v3",
        help="Whisper model size (default: large-v3)",
    )
    parser.add_argument(
        "--whisper-device",
        default="cpu",
        choices=["cuda", "cpu", "auto"],
        help="Whisper device (default: cpu — use cpu on Mac, cuda on NVIDIA)",
    )
    parser.add_argument(
        "--whisper-compute-type",
        default="int8",
        help="Whisper compute type (default: int8 — best for CPU. Use float16 for CUDA, float32 for compatibility)",
    )

    # Gemini settings
    parser.add_argument(
        "--gemini-model",
        default="gemini-3.6-flash",
        help="Gemini model for scene analysis (default: gemini-3.6-flash)",
    )
    parser.add_argument(
        "--gemini-fallback-model",
        default="gemini-2.5-flash",
        help="Gemini fallback model (default: gemini-2.5-flash)",
    )

    # Video quality
    parser.add_argument(
        "--video-crf",
        type=int,
        default=20,
        help="libx264 CRF quality target, lower=sharper (default: 20)",
    )
    parser.add_argument(
        "--video-preset",
        default="medium",
        help="libx264 preset (default: medium. Use slow for better quality, fast for speed)",
    )

    args = parser.parse_args()

    # Validate
    if not os.path.exists(args.audio):
        print(f"❌ Audio file not found: {args.audio}")
        sys.exit(1)

    google_api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not google_api_key or google_api_key == "your-gemini-api-key-here":
        print("❌ GOOGLE_API_KEY not set. Add your Gemini API key to .env")
        print("   Get one at: https://aistudio.google.com/apikey")
        sys.exit(1)

    if not args.no_broll:
        pexels_key = os.environ.get("PEXELS_API_KEY", "")
        if not pexels_key or pexels_key == "your-pexels-api-key-here":
            print("⚠️ PEXELS_API_KEY not set. B-roll will be disabled.")
            print("   Get one at: https://www.pexels.com/api/")
            args.no_broll = True

    print("=" * 60)
    print("🎬 ClipCast Audio2Video")
    print("=" * 60)
    print(f"   📁 Audio: {args.audio}")
    print(f"   📐 Ratio: {args.ratio}")
    print(f"   🎥 B-roll: {'disabled' if args.no_broll else 'enabled' + (' (fast/metadata-only)' if args.broll_fast else ' (Gemini visual scoring)')}")
    print(f"   📝 Subtitles: {'disabled' if args.no_subs else 'enabled'}")
    print(f"   🔤 Font: {args.font_style}")
    print(f"   🤖 Gemini: {args.gemini_model}")
    print(f"   🎙️ Whisper: {args.whisper_model} ({args.whisper_device}/{args.whisper_compute_type})")
    print("=" * 60)
    print()

    try:
        output = run_pipeline(
            audio_path=args.audio,
            ratio=args.ratio,
            output_path=args.output,
            font_style=args.font_style,
            words_per_sub=args.words_per_sub,
            whisper_model=args.whisper_model,
            whisper_device=args.whisper_device,
            whisper_compute_type=args.whisper_compute_type,
            gemini_model=args.gemini_model,
            gemini_fallback_model=args.gemini_fallback_model,
            broll_strict=not args.broll_fast,
            no_broll=args.no_broll,
            no_subs=args.no_subs,
            target_segment_duration=args.target_segment_duration,
            render_height=args.render_height,
            video_crf=args.video_crf,
            video_preset=args.video_preset,
        )
    except KeyboardInterrupt:
        print("\n\n⏹️ Interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()