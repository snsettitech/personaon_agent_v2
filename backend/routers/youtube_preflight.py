"""
YouTube Ingestion Preflight Check Endpoint

Allows users to check if a YouTube video is ingestible before submitting full ingestion job.
Returns metadata: has captions, requires auth, is region-restricted, etc.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import re

logger = logging.getLogger(__name__)
import os
from modules.auth_guard import get_current_user
from modules.observability import log_ingestion_event


class YouTubePreflight(BaseModel):
    url: str


class PreflightResponse(BaseModel):
    video_id: str
    accessible: bool
    has_transcripts: bool
    has_audio: bool
    estimated_time_seconds: int
    requires_auth: bool
    region_restricted: bool
    recommendation: str
    metadata: dict


router = APIRouter(prefix="/youtube", tags=["youtube"])


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from URL."""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/)([0-9A-Za-z_-]{11}).*',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11}).*'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


@router.post("/preflight")
async def youtube_preflight_check(
    request: YouTubePreflight,
    user: dict = Depends(get_current_user)
) -> PreflightResponse:
    """
    Check if a YouTube video is ingestible without starting full ingestion.

    Returns:
    - has_transcripts: Video has captions available
    - has_audio: Video audio can be downloaded
    - estimated_time: Estimated ingestion time in seconds
    - requires_auth: Video needs authentication
    - region_restricted: Video is region-gated
    - recommendation: "use_transcript" | "use_audio" | "requires_proxy" | "not_ingestible"

    This is a fast metadata-only check, no audio download.
    """

    video_id = extract_video_id(request.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    accessible = True
    has_transcripts = False
    has_audio = True  # Assume true unless proven otherwise
    requires_auth = False
    region_restricted = False
    recommendation = "use_audio"
    metadata = {}

    # Try to get transcripts via YouTube Transcript API
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            if transcript_list.manually_created_transcripts or transcript_list.generated_transcripts:
                has_transcripts = True
                recommendation = "use_transcript"
                metadata["transcript_language"] = (
                    transcript_list.manually_created_transcripts[0].language
                    if transcript_list.manually_created_transcripts
                    else transcript_list.generated_transcripts[0].language
                )
        except Exception as e:
            error_msg = str(e).lower()
            if "unavailable" in error_msg:
                accessible = False
                recommendation = "not_ingestible"
            elif "region" in error_msg or "geo" in error_msg:
                region_restricted = True
                recommendation = "requires_proxy"
            elif "sign in" in error_msg or "403" in error_msg:
                requires_auth = True
                recommendation = "requires_auth"
    except ImportError:
        pass  # Library not available, continue

    # Check Google API for video metadata (if key available)
    google_api_key = os.getenv("GOOGLE_API_KEY")
    if google_api_key:
        try:
            from googleapiclient.discovery import build
            youtube = build('youtube', 'v3', developerKey=google_api_key)
            request_obj = youtube.videos().list(part="snippet,contentDetails", id=video_id)
            response = request_obj.execute()

            if response["items"]:
                snippet = response["items"][0]["snippet"]
                content_details = response["items"][0].get("contentDetails", {})

                metadata["title"] = snippet.get("title")
                metadata["channel"] = snippet.get("channelTitle")
                metadata["duration"] = content_details.get("duration")  # ISO 8601 format

                # Estimate transcription time (rough: 1 min audio = 10s transcription)
                duration = content_details.get("duration", "PT0S")
                # Parse ISO 8601 duration (PT1H30M45S -> seconds)
                import re
                match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
                if match:
                    hours = int(match.group(1) or 0)
                    minutes = int(match.group(2) or 0)
                    seconds = int(match.group(3) or 0)
                    total_seconds = hours * 3600 + minutes * 60 + seconds
                    # Transcription time estimate: ~10% of audio duration
                    estimated_time = max(5, int(total_seconds * 0.1))
                else:
                    estimated_time = 30  # Default estimate
        except Exception as e:
            logger.warning("[YouTube Preflight] Google API check failed: %s", e)
    else:
        estimated_time = 30  # Default if no API key

    # Log preflight check
    log_ingestion_event(video_id, user["tenant_id"], "info",
        f"YouTube preflight check: accessible={accessible}, has_transcripts={has_transcripts}, "
        f"requires_auth={requires_auth}, recommendation={recommendation}")

    return PreflightResponse(
        video_id=video_id,
        accessible=accessible,
        has_transcripts=has_transcripts,
        has_audio=has_audio,
        estimated_time_seconds=estimated_time if estimated_time > 0 else 30,
        requires_auth=requires_auth,
        region_restricted=region_restricted,
        recommendation=recommendation,
        metadata=metadata
    )
