"""
audio2video.gemini_prompt — Gemini prompt and schema for audio-to-scene analysis.

Unlike the clipping prompt (which picks viral moments from a video), this prompt
asks Gemini to break an audio transcript into visual scenes and generate B-roll
search queries for each scene.
"""

from google.genai import types


def build_scene_analysis_prompt(
    transcript: str,
    audio_duration: float,
    target_segment_duration: float = 20.0,
) -> str:
    return f"""You are a Visual Director and B-Roll Producer. Your job is to analyze an audio transcript and create a visual scene timeline for a video that will be composed entirely of stock B-roll footage.

The audio is {audio_duration:.1f} seconds long. You will receive a transcript with timestamps in the format:
[start_time - end_time] text

YOUR TASK:
1. Read the entire transcript and understand the content, themes, and emotional arc.
2. Break the audio into consecutive, non-overlapping visual scenes. Each scene should be approximately {target_segment_duration:.0f} seconds long (can vary from 10-40 seconds depending on content shifts).
3. For each scene, generate 2-3 English search queries that will be used to find matching B-roll stock footage on Pexels.
4. The queries must be specific and descriptive enough to find RELEVANT footage.

CRITICAL RULES FOR SEARCH QUERIES:
- Queries must be in English (Pexels is an English-language platform).
- Be SPECIFIC. If the lyrics talk about "the harbor burning", use queries like ["harbor fire disaster", "port explosion aerial", "burning ships night"] — NOT just ["fire"].
- If the content mentions a real event (e.g., Beirut port explosion), include queries that reference it directly: ["beirut port explosion 2020", "lebanon explosion disaster"].
- Think about what visuals would ENHANCE the viewer's understanding of the audio at that moment.
- Consider the MOOD: sad lyrics → melancholic visuals, energetic → dynamic footage, informational → documentary-style footage.
- Provide 2-3 fallback queries per scene, ordered from most specific to most generic.
- Avoid abstract queries like "emotion" or "feeling". Use concrete visual nouns: "rainy window", "crowded market", "empty highway sunset".

SCENE BREAKDOWN RULES:
- Scenes must cover the ENTIRE audio duration from 0 to {audio_duration:.1f}s.
- Scenes must be consecutive (no gaps, no overlaps).
- Scene boundaries should align with natural content shifts (topic change, mood change, verse/chorus transition, paragraph break).
- Each scene's "lyrics_excerpt" should contain the key text from that time range (for context, not for display).

MOOD CLASSIFICATION:
- Classify each scene's mood as one of: dramatic, sad, uplifting, energetic, calm, mysterious, tense, joyful, dark, neutral, informational.

TRANSITIONS:
- Suggest a transition between this scene and the next: "crossfade" (default), "cut" (hard cut for dramatic effect), "flash" (white flash for energetic transitions).

OUTPUT FORMAT:
Return a JSON object with a "segments" array. Each segment has:
- start: float (seconds)
- end: float (seconds)
- lyrics_excerpt: string (key text from this time range)
- search_queries: array of 2-3 strings (English, specific, ordered most-specific first)
- mood: string (one of the mood classifications above)
- transition: string ("crossfade", "cut", or "flash")

TRANSCRIPT TO ANALYZE:

{transcript}
"""


def build_scene_analysis_schema() -> types.Schema:
    return types.Schema(
        type="OBJECT",
        properties={
            "segments": types.Schema(
                type="ARRAY",
                items=types.Schema(
                    type="OBJECT",
                    properties={
                        "start": types.Schema(type="NUMBER"),
                        "end": types.Schema(type="NUMBER"),
                        "lyrics_excerpt": types.Schema(type="STRING"),
                        "search_queries": types.Schema(
                            type="ARRAY",
                            items=types.Schema(type="STRING"),
                        ),
                        "mood": types.Schema(type="STRING"),
                        "transition": types.Schema(type="STRING"),
                    },
                    required=["start", "end", "lyrics_excerpt", "search_queries", "mood", "transition"],
                ),
            ),
        },
        required=["segments"],
    )