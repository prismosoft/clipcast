"""
audio2video.broll_scorer — Pexels B-roll search with relevance scoring.

Two-tier scoring system:
1. Metadata scoring (default): scores Pexels video results by tag/title/description
   overlap with the search query. Fast, free, no extra API calls.
2. Visual scoring (--broll-strict): sends video thumbnails to Gemini for visual
   relevance scoring. Slower, uses API calls, but highest accuracy.
"""

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from .ssl_ctx import get_ssl_context


@dataclass
class BrollSegment:
    """A single B-roll segment in the video timeline."""
    start: float
    end: float
    filepath: Optional[str]
    search_queries: list[str]
    mood: str = "neutral"
    transition: str = "crossfade"
    lyrics_excerpt: str = ""


USED_PEXELS_IDS: set[int] = set()


def _search_pexels(
    query: str,
    ratio: str,
    pexels_api_key: str,
    per_page: int = 30,
) -> list[dict]:
    """Search Pexels video API and return raw video results."""
    orientation = "portrait" if ratio in ("9:16", "3:4", "4:5") else "landscape"

    params = urllib.parse.urlencode({
        "query": query,
        "orientation": orientation,
        "per_page": per_page,
        "size": "large",
    })
    search_url = f"https://api.pexels.com/videos/search?{params}"

    req = urllib.request.Request(
        search_url,
        headers={"Authorization": pexels_api_key, "User-Agent": "Mozilla/5.0"},
    )

    try:
        with urllib.request.urlopen(req, context=get_ssl_context()) as response:
            data = json.load(response)
        return data.get("videos", [])
    except Exception as e:
        print(f"      ⚠️ Pexels search error for '{query}': {e}")
        return []


def _get_best_video_file(video_data: dict) -> Optional[str]:
    """Pick the best quality MP4 file from a Pexels video entry."""
    video_files = [
        vf for vf in video_data.get("video_files", [])
        if vf.get("file_type") == "video/mp4"
    ]
    if not video_files:
        return None

    video_files.sort(
        key=lambda vf: (
            vf.get("quality") != "hd",
            -(vf.get("width") or 0),
            -(vf.get("height") or 0),
        )
    )
    return video_files[0]["link"]


def _score_by_metadata(video: dict, query: str) -> float:
    """
    Score a Pexels video by how well its metadata matches the query.

    Uses simple text overlap scoring on title, tags, and description.
    Returns a score from 0.0 to 10.0.
    """
    query_words = set(query.lower().split())
    if not query_words:
        return 0.0

    title = (video.get("title") or "").lower()
    tags_raw = video.get("tags") or ""
    if isinstance(tags_raw, list):
        tags = " ".join(str(t) for t in tags_raw).lower()
    else:
        tags = str(tags_raw).lower()
    description = (video.get("description") or "").lower()

    combined_text = f"{title} {tags} {description}"

    score = 0.0
    matched_words = 0
    for word in query_words:
        if len(word) < 3:
            continue
        if word in combined_text:
            matched_words += 1
            if word in title:
                score += 3.0
            elif word in tags:
                score += 2.0
            elif word in description:
                score += 1.0

    total_meaningful = sum(1 for w in query_words if len(w) >= 3)
    if total_meaningful > 0:
        coverage = matched_words / total_meaningful
        score += coverage * 2.0

    return min(score, 10.0)


def _score_by_gemini_visual(
    videos: list[dict],
    query: str,
    segment_context: str,
    api_key: str,
    model: str = "gemini-3.6-flash",
) -> list[tuple[dict, float]]:
    """
    Send video thumbnails to Gemini for visual relevance scoring.

    Returns a list of (video_data, score) tuples sorted by score descending.
    """
    from google import genai
    from google.genai import types as gtypes
    import tempfile
    import http.client

    client = genai.Client(api_key=api_key)

    scored: list[tuple[dict, float]] = []

    image_parts = []
    video_indices = []

    for idx, video in enumerate(videos[:20]):
        image_url = video.get("image") or video.get("pictures", {}).get("large", "")
        if not image_url:
            continue

        try:
            req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10, context=get_ssl_context()) as resp:
                img_data = resp.read()

            image_parts.append(gtypes.Part.from_bytes(data=img_data, mime_type="image/jpeg"))
            video_indices.append(idx)
        except Exception as e:
            print(f"      ⚠️ Could not fetch thumbnail for video {idx}: {e}")
            continue

    if not image_parts:
        return [(v, _score_by_metadata(v, query)) for v in videos]

    prompt = f"""You are a strict visual relevance judge for B-roll selection. You will see thumbnails of {len(image_parts)} stock video candidates.

SEARCH QUERY: "{query}"
AUDIO CONTEXT (what the audience is hearing): "{segment_context}"

Your job: rate each candidate 1-10 on how well its VISUAL CONTENT matches the query AND the audio context.

SCORING RULES — be strict:
- 10: The footage could have been shot FOR this content. Location, people, mood, era all match.
- 7-9: Strong match. Clear topical and geographic/cultural alignment.
- 4-6: Topically related but with visible mismatches (wrong country, wrong demographic, wrong mood).
- 1-3: Weak or irrelevant match.

AUTOMATIC LOW SCORES (1-3) if the candidate:
- Shows recognizable flags, landmarks, or signage from the WRONG country or region (e.g., Turkish flag in content about Lebanon)
- Shows people whose evident ethnicity/demographic clearly mismatches the content's setting (e.g., East Asian dancers for a Middle Eastern song)
- Shows modern technology, fashion, or vehicles in a historical piece (or vice versa)
- Has a mood that contradicts the audio (e.g., festive party footage for tragic content)

Geographic and cultural accuracy matters MORE than generic topical relevance. A "beautiful city street" is NOT a match for "Beirut" if it clearly looks like Tokyo.

Return JSON: {{"scores": [score1, score2, ...]}} — one score per candidate, in order."""

    config = gtypes.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=gtypes.Schema(
            type="OBJECT",
            properties={
                "scores": gtypes.Schema(
                    type="ARRAY",
                    items=gtypes.Schema(type="NUMBER"),
                ),
            },
            required=["scores"],
        ),
    )

    try:
        contents = [prompt] + image_parts
        response = client.models.generate_content(
            model=model, contents=contents, config=config
        )
        result = json.loads(response.text)
        scores = result.get("scores", [])

        for i, score in enumerate(scores):
            if i < len(video_indices):
                video_idx = video_indices[i]
                scored.append((videos[video_idx], float(score)))

        for idx in range(len(videos)):
            if idx not in video_indices:
                scored.append((videos[idx], _score_by_metadata(videos[idx], query)))

    except Exception as e:
        print(f"      ⚠️ Gemini visual scoring failed: {e}, falling back to metadata scoring")
        scored = [(v, _score_by_metadata(v, query)) for v in videos]

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def search_pexels_with_scoring(
    queries: list[str],
    ratio: str,
    pexels_api_key: str,
    segment_context: str = "",
    strict: bool = True,
    gemini_api_key: str = "",
    gemini_model: str = "gemini-3.6-flash",
) -> Optional[dict]:
    """
    Search Pexels with multiple fallback queries and score results.

    Tries each query in order. For each query, searches Pexels and scores results
    using Gemini visual scoring (default, when gemini_api_key is provided) or
    metadata matching (fallback when no key or --broll-fast).

    strict=False (--broll-fast) skips Gemini visual scoring entirely.

    Returns the best matching video dict with added 'download_url' and 'score' fields,
    or None if no results found across all queries.
    """
    global USED_PEXELS_IDS

    for query_idx, query in enumerate(queries):
        print(f"      🔍 Query {query_idx+1}/{len(queries)}: '{query}'")

        videos = _search_pexels(query, ratio, pexels_api_key)
        if not videos:
            print(f"      ⚠️ No results for '{query}'")
            continue

        available = [v for v in videos if v["id"] not in USED_PEXELS_IDS]
        if not available:
            print(f"      🔄 All results already used, reusing pool")
            available = videos

        if gemini_api_key and strict:
            print(f"      🎯 Gemini visual scoring: rating {len(available)} candidates...")
            scored = _score_by_gemini_visual(
                available, query, segment_context, gemini_api_key, gemini_model
            )
        else:
            scored = [(v, _score_by_metadata(v, query)) for v in available]
            scored.sort(key=lambda x: x[1], reverse=True)

        if not scored:
            continue

        best_video, best_score = scored[0]
        print(f"      🏆 Best match: score={best_score:.1f}/10 — {best_video.get('title', 'untitled')[:60]}")

        # Quality bar: reject clips Gemini scored below 5 — better to try the next
        # query than use a culturally/geographically mismatched clip.
        if best_score < 5.0 and query_idx < len(queries) - 1:
            print(f"      ⚠️ Below quality bar (<5.0), trying next fallback query...")
            continue

        download_url = _get_best_video_file(best_video)
        if not download_url:
            print(f"      ⚠️ No downloadable MP4 for best match")
            continue

        USED_PEXELS_IDS.add(best_video["id"])
        best_video["download_url"] = download_url
        best_video["score"] = best_score
        return best_video

    return None