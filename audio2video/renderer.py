"""
audio2video.renderer — FFmpeg-based renderer for B-roll + subtitles + audio.

Composes full-screen B-roll clips with Ken Burns motion and crossfades,
overlays karaoke subtitles (reuses existing ASS subtitle generator),
and muxes the original audio as the main track.
"""

import json
import os
import subprocess
import sys
import math
from types import SimpleNamespace
from typing import Optional

import cv2
import numpy as np

# Reuse existing studio modules
_module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _module_dir)

import importlib.util

_STUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "clipping", "studio")


def _load_studio_module(file_name: str, module_alias: str):
    """Load a clipping/studio/*.py module by file path (same pattern as the repo)."""
    module_path = os.path.join(_STUDIO_DIR, file_name)
    spec = importlib.util.spec_from_file_location(module_alias, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_subtitles_mod = _load_studio_module("subtitles.py", "clipcast_subtitles")
buat_file_ass = _subtitles_mod.buat_file_ass
_utils_mod = _load_studio_module("utils.py", "clipcast_utils")
_resize_frame = _utils_mod._resize_frame
_get_render_dims = _utils_mod._get_render_dims
_is_vertical_ratio = _utils_mod._is_vertical_ratio
_helpers_mod = _load_studio_module("helpers.py", "clipcast_helpers")
format_seconds = _helpers_mod.format_seconds
escape_ffmpeg_filter_value = _helpers_mod.escape_ffmpeg_filter_value
_ffmpeg_utils_mod = _load_studio_module("ffmpeg_utils.py", "clipcast_ffmpeg_utils")
detect_video_encoder = _ffmpeg_utils_mod.detect_video_encoder
get_mp4_encode_args = _ffmpeg_utils_mod.get_mp4_encode_args
run_ffmpeg_with_progress = _ffmpeg_utils_mod.run_ffmpeg_with_progress
_typography_mod = _load_studio_module("typography.py", "clipcast_typography")
siapkan_font_tipografi = _typography_mod.siapkan_font_tipografi
register_fonts_for_libass = _typography_mod.register_fonts_for_libass
_broll_mod = _load_studio_module("broll.py", "clipcast_broll_mod")
crop_center_broll = _broll_mod.crop_center_broll
from audio2video.broll_scorer import BrollSegment


def _get_ffmpeg_path() -> str:
    return "ffmpeg"


def _probe_duration(video_path: str) -> float:
    """Get video duration using ffprobe. Raises if the file is not a readable video."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", video_path],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        raise RuntimeError(f"invalid or unreadable video file: {video_path}")


def _build_broll_concat(
    broll_segments: list[BrollSegment],
    output_width: int,
    output_height: int,
    audio_duration: float,
    work_dir: str,
    fps: int = 30,
) -> str:
    """
    Build a single concatenated B-roll video with Ken Burns effect and crossfades.

    Each B-roll clip is:
    1. Trimmed/looped to fill its segment duration
    2. Cropped to target aspect ratio
    3. Applied with Ken Burns zoom (slow zoom-in)
    4. Crossfaded with the next clip

    Segments with no B-roll file use a solid color background.

    Returns the path to the concatenated video file (no audio).
    """
    os.makedirs(work_dir, exist_ok=True)
    temp_clips = []

    for i, seg in enumerate(broll_segments):
        seg_duration = seg.end - seg.start
        if seg_duration <= 0:
            continue

        clip_path = os.path.join(work_dir, f"seg_{i:03d}.mp4")

        if seg.filepath and os.path.exists(seg.filepath) and os.path.getsize(seg.filepath) > 1024:
            try:
                _render_ken_burns_clip(
                    seg.filepath, clip_path, seg_duration,
                    output_width, output_height, fps, work_dir, i
                )
            except Exception as e:
                print(f"      ⚠️ B-roll clip {i} failed ({e}); using solid color fallback")
                _render_solid_color_clip(
                    clip_path, seg_duration, output_width, output_height, fps,
                    color=(10, 10, 15)
                )
        else:
            _render_solid_color_clip(
                clip_path, seg_duration, output_width, output_height, fps,
                color=(10, 10, 15)
            )

        temp_clips.append((clip_path, seg.transition))

    if not temp_clips:
        print("   ⚠️ No B-roll clips to concatenate, generating full solid color video")
        fallback = os.path.join(work_dir, "fallback_full.mp4")
        _render_solid_color_clip(
            fallback, audio_duration, output_width, output_height, fps,
            color=(10, 10, 15)
        )
        return fallback

    if len(temp_clips) == 1:
        return temp_clips[0][0]

    # Concatenate with crossfades
    concat_path = os.path.join(work_dir, "broll_concat.mp4")
    _concat_with_crossfades(temp_clips, concat_path, work_dir, fps)

    return concat_path


def _render_ken_burns_clip(
    input_path: str,
    output_path: str,
    target_duration: float,
    out_w: int,
    out_h: int,
    fps: int,
    work_dir: str,
    seg_index: int,
):
    """Render a single B-roll clip with Ken Burns zoom effect, trimmed/looped to target duration."""
    src_duration = _probe_duration(input_path)

    # Build FFmpeg filter for Ken Burns + crop + resize
    # Slow zoom from 1.0 to 1.15 over the clip duration
    zoom_end = 1.15
    trim_filter = ""
    loop_filter = ""

    if src_duration >= target_duration:
        trim_filter = f"trim=duration={target_duration},setpts=PTS-STARTPTS,"
    else:
        loops_needed = int(math.ceil(target_duration / src_duration))
        loop_filter = f"stream_loop={loops_needed-1},"

    # Ken Burns: zoompan with slow zoom
    # We use a simpler approach: scale up then crop with animated zoom
    filter_complex = (
        f"{loop_filter}"
        f"{trim_filter}"
        f"scale={int(out_w * zoom_end)}:{int(out_h * zoom_end)},"
        f"crop={out_w}:{out_h}:"
        f"x='(in_w-out_w)/2 + (in_w-out_w)*t/{target_duration}*0.3':"
        f"y='(in_h-out_h)/2',"
        f"scale={out_w}:{out_h},"
        f"setsar=1,fps={fps}"
    )

    encoder = detect_video_encoder()
    cmd = [
        _get_ffmpeg_path(), "-y", "-i", input_path,
        "-vf", filter_complex,
        "-t", str(target_duration),
        "-an",
        "-c:v", encoder,
        "-pix_fmt", "yuv420p",
    ]

    if encoder == "h264_videotoolbox":
        cmd += ["-b:v", "8M", "-allow_sw", "1"]
    else:
        cmd += ["-crf", "20", "-preset", "medium"]

    cmd += [output_path]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"      ⚠️ Ken Burns render failed for seg {seg_index}, using simple crop")
            _render_simple_crop(input_path, output_path, target_duration, out_w, out_h, fps)
    except Exception as e:
        print(f"      ⚠️ Ken Burns error: {e}, using simple crop")
        _render_simple_crop(input_path, output_path, target_duration, out_w, out_h, fps)


def _render_simple_crop(
    input_path: str, output_path: str,
    target_duration: float, out_w: int, out_h: int, fps: int,
):
    """Fallback: simple center crop + resize, no Ken Burns."""
    src_duration = _probe_duration(input_path)
    loop_arg = []
    if src_duration < target_duration:
        loops = int(math.ceil(target_duration / src_duration))
        loop_arg = ["-stream_loop", str(loops - 1)]

    filter = f"crop=min(iw\\,ih*{out_w}/{out_h}):min(ih\\,iw*{out_h}/{out_w}),(scale={out_w}:{out_h}),setsar=1,fps={fps}"

    cmd = (
        [_get_ffmpeg_path(), "-y"] + loop_arg +
        ["-i", input_path, "-vf", filter, "-t", str(target_duration), "-an",
         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
         output_path]
    )
    subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def _render_solid_color_clip(
    output_path: str,
    duration: float,
    out_w: int, out_h: int, fps: int,
    color=(10, 10, 15),
):
    """Generate a solid color video clip of the given duration."""
    color_hex = f"0x{color[0]:02x}{color[1]:02x}{color[2]:02x}"
    cmd = [
        _get_ffmpeg_path(), "-y",
        "-f", "lavfi",
        "-i", f"color=c={color_hex}:s={out_w}x{out_h}:d={duration}:r={fps}",
        "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def _concat_with_crossfades(
    clips: list[tuple[str, str]],
    output_path: str,
    work_dir: str,
    fps: int,
    crossfade_duration: float = 0.5,
):
    """Concatenate clips with crossfade transitions between them."""
    if len(clips) == 1:
        import shutil
        shutil.copy2(clips[0][0], output_path)
        return

    # Build xfade chain
    # For N clips, we need N-1 xfades
    n = len(clips)
    durations = []
    for clip_path, _ in clips:
        dur = _probe_duration(clip_path)
        durations.append(dur)

    # Build filter complex for xfade chain
    inputs = []
    for clip_path, _ in clips:
        inputs.extend(["-i", clip_path])

    # Calculate offsets for xfade
    filter_parts = []
    prev_label = "0:v"

    cumulative = durations[0]
    for i in range(1, n):
        transition = clips[i][1] if i < len(clips) else "crossfade"

        # Adjust for crossfade overlap
        offset = cumulative - crossfade_duration

        if transition == "cut":
            filter_parts.append(
                f"[{prev_label}][{i}:v]concat=n=1:v=1:a=0[v{i}]"
            )
            cumulative = cumulative + durations[i] - crossfade_duration
        elif transition == "flash":
            filter_parts.append(
                f"[{prev_label}][{i}:v]xfade=transition=fade:white:duration={crossfade_duration}:offset={offset}[v{i}]"
            )
            cumulative = cumulative + durations[i] - crossfade_duration
        else:
            filter_parts.append(
                f"[{prev_label}][{i}:v]xfade=transition=fade:duration={crossfade_duration}:offset={offset}[v{i}]"
            )
            cumulative = cumulative + durations[i] - crossfade_duration

        prev_label = f"v{i}"

    filter_complex = ";".join(filter_parts)

    cmd = (
        [_get_ffmpeg_path(), "-y"] + inputs +
        ["-filter_complex", filter_complex,
         "-map", f"[{prev_label}]",
         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-r", str(fps),
         output_path]
    )

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"   ⚠️ Crossfade concat failed, falling back to simple concat")
        _concat_simple(clips, output_path, work_dir)


def _concat_simple(clips: list[tuple[str, str]], output_path: str, work_dir: str):
    """Fallback: simple concatenation without transitions."""
    list_path = os.path.join(work_dir, "concat_list.txt")
    with open(list_path, "w") as f:
        for clip_path, _ in clips:
            f.write(f"file '{os.path.abspath(clip_path)}'\n")

    cmd = [
        _get_ffmpeg_path(), "-y", "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy", output_path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def render_audio_video(
    audio_path: str,
    broll_segments: list[BrollSegment],
    data_segmen: list[dict],
    ratio: str,
    output_path: str,
    font_style: str = "HORMOZI",
    words_per_sub: int = 5,
    no_subs: bool = False,
    render_height: int = 1080,
    video_crf: int = 20,
    video_preset: str = "medium",
    audio_duration: float = 0.0,
):
    """
    Render the final video: B-roll visual + karaoke subtitles + original audio.

    Steps:
    1. Build concatenated B-roll video (with Ken Burns + crossfades)
    2. Generate ASS subtitle file from word-level transcript
    3. Mux: B-roll video + subtitles + original audio → final MP4
    """
    # Compute output dimensions based on ratio
    ratio_map = {"9:16": (9, 16), "16:9": (16, 9), "1:1": (1, 1), "3:4": (3, 4), "4:5": (4, 5)}
    w_part, h_part = ratio_map.get(ratio, (16, 9))
    if _is_vertical_ratio(ratio):
        out_w = render_height
        out_h = int(render_height * h_part / w_part)
    else:
        out_h = render_height
        out_w = int(render_height * w_part / h_part)
    fps = 30
    work_dir = os.path.join(os.path.dirname(output_path) or ".", "render_work")
    os.makedirs(work_dir, exist_ok=True)

    # Step 1: Build B-roll video
    if broll_segments:
        print("   🎥 Building B-roll visual timeline...")
        broll_video = _build_broll_concat(
            broll_segments, out_w, out_h, audio_duration, work_dir, fps
        )
    else:
        print("   🎥 No B-roll, using solid color background...")
        broll_video = os.path.join(work_dir, "solid_bg.mp4")
        _render_solid_color_clip(broll_video, audio_duration, out_w, out_h, fps)

    # Ensure the B-roll video is exactly audio_duration long
    broll_final = os.path.join(work_dir, "broll_final.mp4")
    cmd_trim = [
        _get_ffmpeg_path(), "-y",
        "-i", broll_video,
        "-t", str(audio_duration),
        "-c:v", "libx264", "-crf", str(video_crf), "-preset", video_preset,
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-an",
        broll_final,
    ]
    print(f"   ✂️ Trimming B-roll to {audio_duration:.1f}s...")
    subprocess.run(cmd_trim, capture_output=True, text=True, timeout=600)

    # Step 2: Generate subtitles
    ass_path = None
    if not no_subs and data_segmen:
        print("   📝 Generating karaoke subtitles...")
        ass_path = os.path.join(work_dir, "subtitles.ass")

        # Prepare fonts — build a config object with all attributes the subtitle module expects
        from clipping.config import (
            DAFTAR_FONT, ASS_ALIGN_916, ASS_MARGIN_916, ASS_FONT_916,
            SCALE_KATA_KHUSUS_916, ASS_ALIGN_169, ASS_MARGIN_169, ASS_FONT_169,
            SCALE_KATA_KHUSUS_169, WARNA_KATA_KHUSUS,
        )
        font_cfg = SimpleNamespace(
            gaya_font_aktif=font_style,
            base_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            font_dir=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "custom_fonts"),
            daftar_font=DAFTAR_FONT,
            use_advanced_text=False,
            use_karaoke_effect=True,
            ass_align_916=ASS_ALIGN_916,
            ass_margin_916=ASS_MARGIN_916,
            ass_font_916=ASS_FONT_916,
            scale_kata_khusus_916=SCALE_KATA_KHUSUS_916,
            ass_align_169=ASS_ALIGN_169,
            ass_margin_169=ASS_MARGIN_169,
            ass_font_169=ASS_FONT_169,
            scale_kata_khusus_169=SCALE_KATA_KHUSUS_169,
            warna_kata_khusus=WARNA_KATA_KHUSUS,
        )
        try:
            siapkan_font_tipografi(font_cfg)
            register_fonts_for_libass(font_cfg)
        except Exception as e:
            print(f"   ⚠️ Font setup warning: {e}")

        buat_file_ass(
            data_segmen=data_segmen,
            start_clip=0.0,
            end_clip=audio_duration,
            nama_file_ass=ass_path,
            rasio=ratio,
            cfg=font_cfg,
            gunakan_advanced=False,
        )

    # Step 3: Mux B-roll + audio + subtitles
    print("   🔀 Muxing B-roll + audio + subtitles...")
    mux_cmd = [
        _get_ffmpeg_path(), "-y",
        "-i", broll_final,
        "-i", audio_path,
    ]

    if ass_path and os.path.exists(ass_path):
        # Burn subtitles into video
        sub_filter = f"subtitles='{ass_path}'"
        mux_cmd += ["-vf", sub_filter]

    mux_cmd += [
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264", "-crf", str(video_crf), "-preset", video_preset,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ]

    result = subprocess.run(mux_cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        print(f"   ❌ FFmpeg muxing failed:")
        print(f"   stderr: {result.stderr[-2000:]}")
        raise RuntimeError("FFmpeg muxing failed. See stderr above.")

    # Clean up temp files
    import shutil
    try:
        shutil.rmtree(work_dir)
    except Exception:
        pass

    print(f"   ✅ Render complete: {output_path}")