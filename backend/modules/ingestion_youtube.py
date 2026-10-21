"""
YouTube ingestion pipeline.

Extracted from ingestion.py -- contains all YouTube-specific transcript
fetching, download, and ingestion logic.
"""

import os
import re
import json
import html
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

try:
    import yt_dlp
except ImportError:
    yt_dlp = None  # type: ignore[assignment]

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None  # type: ignore[assignment,misc]

from modules.transcription import transcribe_audio_multi
from modules.observability import supabase, log_ingestion_event
from modules.ingestion_diagnostics import start_step, finish_step, build_error
from modules.health_checks import calculate_content_hash
from modules.governance import AuditLogger

from modules.ingestion_config import (
    YouTubeConfig,
    ErrorClassifier,
    LanguageDetector,
    PIIScrubber,
    _resolve_tenant_id,
)


def extract_video_id(url: str) -> str:
    """
    Extracts the video ID from a YouTube URL.
    """
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


def _build_yt_dlp_opts(video_id: str, source_id: str, twin_id: str) -> dict:
    """
    Build yt-dlp options with enterprise-grade toggles:
    - Multiple client emulation strategies (Android, web, iOS)
    - Optional cookies (file only) for age/region-gated videos
    - Optional proxy for IP reputation routing
    - Browser headers to avoid bot detection
    """
    temp_dir = "temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    temp_filename = f"yt_{video_id}"

    cookie_file = os.getenv("YOUTUBE_COOKIES_FILE")
    proxy_url = os.getenv("YOUTUBE_PROXY")

    # Start with Android client emulation (most reliable for containers)
    ydl_opts = {
        'format': 'm4a/bestaudio/best',
        'outtmpl': os.path.join(temp_dir, f"{temp_filename}.%(ext)s"),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
        # Multiple client strategies (try Android first, then web/iOS)
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web', 'ios'],
                'player_skip': ['webpage', 'configs', 'js'],
                'include_live_dash': [True],
            }
        },
        'nocheckcertificate': True,
        'socket_timeout': 30,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'retries': 5,
        'fragment_retries': 5,
        'skip_unavailable_fragments': True,
    }

    if proxy_url:
        ydl_opts['proxy'] = proxy_url
        log_ingestion_event(source_id, twin_id, "info", "Using YOUTUBE_PROXY for YouTube download")

    # Only use file-based cookies (cookiesfrombrowser doesn't work in containers)
    if cookie_file and os.path.exists(cookie_file):
        ydl_opts['cookiefile'] = cookie_file
        log_ingestion_event(source_id, twin_id, "info", "Using YOUTUBE_COOKIES_FILE for YouTube download")
    else:
        if YouTubeConfig.VERBOSE_LOGGING:
            log_ingestion_event(source_id, twin_id, "info", "No cookie file found; using client emulation only")

    # Log configuration for telemetry
    log_ingestion_event(source_id, twin_id, "info",
        f"YouTube config: ASR={YouTubeConfig.ASR_PROVIDER}:{YouTubeConfig.ASR_MODEL}, "
        f"MaxRetries={YouTubeConfig.MAX_RETRIES}, LanguageDetection={YouTubeConfig.LANGUAGE_DETECTION}, "
        f"PIIScrub={YouTubeConfig.PII_SCRUB}")

    return ydl_opts, temp_dir, temp_filename


def _transcript_items_to_text(items: Any) -> str | None:
    """Normalize transcript payloads from different youtube-transcript-api versions."""
    if items is None:
        return None

    raw_items = items
    if hasattr(items, "to_raw_data"):
        raw_items = items.to_raw_data()

    if raw_items is None:
        return None

    if not isinstance(raw_items, list):
        try:
            raw_items = list(raw_items)
        except Exception:
            return None

    parts: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            parts.append(str(item.get("text", "")))
        elif isinstance(item, str):
            parts.append(item)

    text = " ".join(parts).strip()
    return text or None


def fetch_youtube_transcript_compat(video_id: str, yta_cls: Any | None = None) -> tuple[str | None, str | None, str | None]:
    """
    Fetch transcript text while supporting both old and new youtube-transcript-api APIs.

    Returns:
      (text, error_message, method_used)
      method_used is one of: fetch, list, get_transcript, list_transcripts.
    """
    transcript_error: str | None = None

    try:
        if yta_cls is None:
            from youtube_transcript_api import YouTubeTranscriptApi as yta_cls  # type: ignore[no-redef]

        # New API: instance.fetch(video_id, languages=...)
        try:
            api = yta_cls()
            if hasattr(api, "fetch"):
                fetched = api.fetch(video_id, languages=("en", "en-US", "en-GB"))
                text = _transcript_items_to_text(fetched)
                if text:
                    return text, None, "fetch"
        except Exception as e:
            transcript_error = str(e)

        # New API fallback: instance.list(video_id).find_*_transcript(...).fetch()
        try:
            api = yta_cls()
            if hasattr(api, "list"):
                transcript_list = api.list(video_id)
                transcript = None
                try:
                    if hasattr(transcript_list, "find_manually_created_transcript"):
                        transcript = transcript_list.find_manually_created_transcript(["en", "en-US", "en-GB"])
                except Exception:
                    transcript = None
                if transcript is None:
                    try:
                        if hasattr(transcript_list, "find_generated_transcript"):
                            transcript = transcript_list.find_generated_transcript(["en", "en-US", "en-GB"])
                    except Exception:
                        transcript = None
                if transcript is None:
                    transcript = transcript_list.find_transcript(["en", "en-US", "en-GB"])

                fetched = transcript.fetch(preserve_formatting=False)
                text = _transcript_items_to_text(fetched)
                if text:
                    return text, None, "list"
        except Exception as e:
            if not transcript_error:
                transcript_error = str(e)

        # Old API fallback: static get_transcript(video_id)
        if hasattr(yta_cls, "get_transcript"):
            try:
                items = yta_cls.get_transcript(video_id)
                text = _transcript_items_to_text(items)
                if text:
                    return text, None, "get_transcript"
            except Exception as e:
                if not transcript_error:
                    transcript_error = str(e)

        # Old API fallback: static list_transcripts(video_id)
        if hasattr(yta_cls, "list_transcripts"):
            try:
                transcript_list = yta_cls.list_transcripts(video_id)

                for transcript in getattr(transcript_list, "manually_created_transcripts", []) or []:
                    try:
                        text = _transcript_items_to_text(transcript.fetch())
                        if text:
                            return text, None, "list_transcripts"
                    except Exception:
                        continue

                for transcript in getattr(transcript_list, "generated_transcripts", []) or []:
                    try:
                        text = _transcript_items_to_text(transcript.fetch())
                        if text:
                            return text, None, "list_transcripts"
                    except Exception:
                        continue
            except Exception as e:
                if not transcript_error:
                    transcript_error = str(e)
    except Exception as e:
        transcript_error = str(e)

    return None, transcript_error, None


async def ingest_youtube_transcript(source_id: str, twin_id: str, url: str, correlation_id: str | None = None):
    """
    Ingest YouTube video transcript using robust multi-strategy approach.
    """
    # Lazy import to avoid circular dependency
    from modules.ingestion_chunking import process_and_index_text

    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError("Invalid YouTube URL")

    provider = "youtube"
    # -------------------------------------------------------------
    # Step 0: Ensure Source Record exists
    # -------------------------------------------------------------
    try:
        supabase.table("sources").upsert({
            "id": source_id,
            "twin_id": twin_id,
            "filename": f"YouTube: {video_id}",
            "file_size": 0,
            "content_text": "",
            "status": "processing",
            "citation_url": url,
        }).execute()
    except Exception as e:
        # Don't crash ingestion for telemetry upsert issues; later updates may still succeed.
        logger.warning("[YouTube] Warning: Failed to upsert source record: %s", e)

    text = None
    video_title = None
    transcript_error = None
    fetch_event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="fetching",
        correlation_id=correlation_id,
        message="Fetching YouTube transcript/captions",
        metadata={"video_id": video_id, "url": url},
    )

    # -------------------------------------------------------------
    # Step 1: Validate via YouTube Data API (if key available)
    # -------------------------------------------------------------
    google_api_key = os.getenv("GOOGLE_API_KEY")
    if google_api_key:
        try:
            from googleapiclient.discovery import build
            youtube = build('youtube', 'v3', developerKey=google_api_key)
            request = youtube.videos().list(part="snippet", id=video_id)
            response = request.execute()

            if response["items"]:
                snippet = response["items"][0]["snippet"]
                video_title = snippet["title"]
                # Update filename with real title
                supabase.table("sources").update({
                    "filename": f"YouTube: {video_title}"
                }).eq("id", source_id).execute()
                logger.info("[YouTube] Validated video: %s", video_title)
        except Exception as e:
            logger.warning("[YouTube] Data API check failed (non-blocking): %s", e)

    # -------------------------------------------------------------
    # Strategy 0: youtube-transcript-api (Fast, No Download)
    # -------------------------------------------------------------
    text, transcript_error, transcript_method = fetch_youtube_transcript_compat(video_id)
    if text:
        log_ingestion_event(
            source_id,
            twin_id,
            "info",
            f"Fetched YouTube transcript via youtube-transcript-api ({transcript_method})"
        )
    elif transcript_error and YouTubeConfig.VERBOSE_LOGGING:
        logger.warning("[YouTube] Transcript API failed: %s", transcript_error)

    # -------------------------------------------------------------
    # Strategy 1.6: Direct HTTP fetch with browser headers (bypasses library blocks)
    # -------------------------------------------------------------
    if not text:
        try:
            logger.info("[YouTube] Trying direct HTTP transcript fetch for %s", video_id)
            log_ingestion_event(source_id, twin_id, "info", "Attempting direct HTTP transcript fetch")

            # Use Chrome-like headers to appear as a real browser
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }

            # Fetch the video page
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
                response = await client.get(video_url)

                if response.status_code == 200:
                    page_content = response.text

                    # Extract caption track URLs from the page
                    # Strategy 1.6.a: Main Player Response
                    caption_match = re.search(r'"captionTracks":\s*(\[.*?\])', page_content)

                    # Strategy 1.6.b: Escaped JSON (mobile/older formats)
                    if not caption_match:
                        caption_match = re.search(r'captionTracks\\":(\[.*?\])', page_content)

                    # Strategy 1.6.c: Alternative escaped format
                    if not caption_match:
                        caption_match = re.search(r'\\u0022captionTracks\\u0022:\\s*(\\\[.*?\\\])', page_content)

                    if caption_match:
                        logger.info("[YouTube] Found caption tracks on page")
                        try:
                            raw_json = caption_match.group(1).replace('\\"', '"').replace('\\\\', '\\').replace('\\u0022', '"')
                            # Ensure we handle double brackets from some escaped formats
                            if raw_json.startswith('\\['): raw_json = json.loads(f'"{raw_json}"')
                            caption_tracks = json.loads(raw_json)

                            # Find English or first available caption
                            caption_url = None
                            for track in caption_tracks:
                                lang = track.get("languageCode", "")
                                if lang.startswith("en"):
                                    caption_url = track.get("baseUrl")
                                    break

                            # Fallback to first track if no English
                            if not caption_url and caption_tracks:
                                caption_url = caption_tracks[0].get("baseUrl")

                            if caption_url:
                                # Fetch the actual captions
                                caption_response = await client.get(caption_url)
                                if caption_response.status_code == 200:
                                    # Parse XML captions
                                    caption_xml = caption_response.text
                                    caption_texts = re.findall(r'<text[^>]*>(.*?)</text>', caption_xml, re.DOTALL)

                                    if caption_texts:
                                        # Unescape HTML entities and join
                                        text = " ".join([html.unescape(t.strip()) for t in caption_texts])
                                        text = re.sub(r'\s+', ' ', text).strip()
                                        log_ingestion_event(source_id, twin_id, "info", f"Direct HTTP transcript fetch successful ({len(text)} chars)")
                                        logger.info("[YouTube] Direct HTTP fetch succeeded: %s characters", len(text))
                        except json.JSONDecodeError:
                            logger.warning("[YouTube] Could not parse caption tracks JSON")
        except Exception as e:
            logger.warning("[YouTube] Direct HTTP fetch failed: %s", e)

    # -------------------------------------------------------------
    # Strategy 2: yt-dlp with Multiple Client Emulation & Better Error Handling
    # Using YouTubeRetryStrategy for enterprise-grade retry logic
    # -------------------------------------------------------------
    if not text:
        logger.info("[YouTube] No captions found. Starting robust audio download...")
        log_ingestion_event(source_id, twin_id, "warning", "Attempting robust audio download (yt-dlp with multiple clients)")

        from modules.youtube_retry_strategy import YouTubeRetryStrategy

        ydl_opts, temp_dir, temp_filename = _build_yt_dlp_opts(video_id, source_id, twin_id)

        # Initialize retry strategy with configured max_retries
        config = YouTubeConfig()
        strategy = YouTubeRetryStrategy(
            source_id=source_id,
            twin_id=twin_id,
            max_retries=config.MAX_RETRIES,
            verbose=config.VERBOSE_LOGGING
        )

        temp_audio_path = None

        while strategy.attempts < strategy.max_retries and not text:
            attempt_no = strategy.attempts + 1
            try:
                logger.info("[YouTube] Download attempt %s/%s for %s", attempt_no, strategy.max_retries, video_id)

                # Download audio
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

                temp_audio_path = os.path.join(temp_dir, f"{temp_filename}.mp3")

                if not os.path.exists(temp_audio_path):
                    raise FileNotFoundError(f"Audio file not created at {temp_audio_path}")

                # Transcribe
                logger.info("[YouTube] Transcribing audio for %s", video_id)
                text = transcribe_audio_multi(temp_audio_path)

                # Language detection
                language = LanguageDetector.detect(text)

                # PII detection
                pii_detected = PIIScrubber.has_pii(text) if config.PII_SCRUB else False
                detected_pii = PIIScrubber.detect_pii(text) if pii_detected else []

                # Log success with metadata
                strategy.attempts = attempt_no
                strategy.log_success(
                    content_length=len(text),
                    metadata={
                        "language": language,
                        "has_pii": pii_detected,
                        "pii_count": len(detected_pii)
                    }
                )

                log_ingestion_event(
                    source_id, twin_id, "info",
                    f"Audio transcribed via Gemini/Whisper ({len(text)} chars, lang={language}, pii={pii_detected})"
                )

                logger.info("[YouTube] Successfully transcribed %s: %s characters, language=%s", video_id, len(text), language)

            except Exception as download_error:
                error_msg = str(download_error)
                error_category, user_msg, retryable = ErrorClassifier.classify(error_msg)

                strategy.log_attempt(error_msg)

                logger.warning("[YouTube] Attempt %s failed [%s]: %s", strategy.attempts, error_category, error_msg)
                log_ingestion_event(
                    source_id, twin_id, "warning",
                    f"Download attempt {strategy.attempts} failed [{error_category}]: {error_msg}"
                )

                # Determine if we should retry
                if not strategy.should_retry(error_category):
                    logger.warning("[YouTube] Error category '%s' is non-retryable, stopping attempts", error_category)
                    break

                if strategy.attempts < strategy.max_retries:
                    wait_time = strategy.wait_for_retry()
                    logger.info("[YouTube] Waiting %ss before retry...", wait_time)
                else:
                    break

        # Cleanup temp file
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
            except OSError as cleanup_err:
                logger.warning("[YouTube] Temp file cleanup failed (%s): %s", temp_audio_path, cleanup_err)

        if not text:
            # Get final error message with classification
            final_error = strategy.get_final_error_message(strategy.last_error or "Unknown error")
            metrics = strategy.get_metrics()
            final_error_category, _, _ = ErrorClassifier.classify(strategy.last_error or final_error)

            log_ingestion_event(
                source_id, twin_id, "error",
                f"YouTube ingestion failed after {strategy.attempts} attempts. Metrics: {metrics}"
            )
            err = build_error(
                code="YOUTUBE_TRANSCRIPT_UNAVAILABLE",
                message=final_error,
                provider=provider,
                step="fetching",
                provider_error_code=final_error_category,
                correlation_id=correlation_id,
                raw={
                    "video_id": video_id,
                    "url": url,
                    "attempts": strategy.attempts,
                    "metrics": metrics,
                    "last_error": strategy.last_error,
                },
            )
            finish_step(
                event_id=fetch_event_id,
                source_id=source_id,
                twin_id=twin_id,
                provider=provider,
                step="fetching",
                status="error",
                correlation_id=correlation_id,
                error=err,
            )
            raise ValueError(final_error)

    if not text:
        err = build_error(
            code="YOUTUBE_TRANSCRIPT_UNAVAILABLE",
            message="No transcript could be extracted. This video may not have captions.",
            provider=provider,
            step="fetching",
            correlation_id=correlation_id,
            raw={"video_id": video_id, "url": url, "transcript_error": transcript_error},
        )
        finish_step(
            event_id=fetch_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="fetching",
            status="error",
            correlation_id=correlation_id,
            error=err,
        )
        raise ValueError(
            "No transcript could be extracted. This video may not have captions. "
            "Try a different video with closed captions (CC) enabled."
        )

    finish_step(
        event_id=fetch_event_id,
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="fetching",
        status="completed",
        correlation_id=correlation_id,
        metadata={"text_len": len(text), "has_title": bool(video_title)},
    )

    parsed_event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="parsed",
        correlation_id=correlation_id,
        message="Persisting transcript to sources.content_text",
    )

    try:
        # Direct indexing - extract and index immediately
        content_hash = calculate_content_hash(text)

        # Update existing source row (do NOT insert again; the row is created when job is queued)
        filename = f"YouTube: {video_title or video_id}"
        _update_payload = {
            "filename": filename,
            "file_size": len(text),
            "content_text": text,
            "content_hash": content_hash,
            "status": "processing",
            "extracted_text_length": len(text),
            "citation_url": url,
        }
        # Some columns may not exist in all deployments — strip missing ones gracefully.
        _optional_cols = ("content_text", "content_hash", "extracted_text_length")
        for _attempt in range(len(_optional_cols) + 1):
            try:
                supabase.table("sources").update(_update_payload).eq("id", source_id).eq("twin_id", twin_id).execute()
                break
            except Exception as _upd_err:
                _removed = next((c for c in _optional_cols if c in _update_payload and c in str(_upd_err)), None)
                if _removed:
                    logger.warning("[YouTube] Column '%s' not in DB, skipping: %s", _removed, _upd_err)
                    _update_payload.pop(_removed)
                else:
                    logger.warning("[YouTube] Source update failed (non-fatal): %s", _upd_err)
                    break

        finish_step(
            event_id=parsed_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="parsed",
            status="completed",
            correlation_id=correlation_id,
            metadata={"filename": filename, "text_len": len(text)},
        )

        log_ingestion_event(source_id, twin_id, "info", f"YouTube transcript extracted: {len(text)} characters")

        # Direct indexing
        num_chunks = await process_and_index_text(
            source_id,
            twin_id,
            text,
            metadata_override={
                "filename": filename,
                "type": "youtube",
                "video_id": video_id,
                "url": url,
            },
            provider=provider,
            correlation_id=correlation_id,
        )

        tenant_id = _resolve_tenant_id(twin_id, source_id=source_id)

        # Phase 8: Log the action
        AuditLogger.log(
            tenant_id=tenant_id,
            twin_id=twin_id,
            event_type="KNOWLEDGE_UPDATE",
            action="SOURCE_INDEXED",
            metadata={"source_id": source_id, "filename": filename, "type": "youtube", "chunks": num_chunks}
        )

        # Set status to live after successful Pinecone upsert
        supabase.table("sources").update({
            "status": "live",
            "chunk_count": num_chunks
        }).eq("id", source_id).execute()

        log_ingestion_event(source_id, twin_id, "info", f"YouTube content indexed: {num_chunks} chunks, status=live")

        live_event_id = start_step(
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="live",
            correlation_id=correlation_id,
            message="Source is live",
        )
        finish_step(
            event_id=live_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="live",
            status="completed",
            correlation_id=correlation_id,
            metadata={"chunks": num_chunks},
        )

        # Enqueue async content extraction to build graph nodes/edges
        try:
            from modules._core.scribe_engine import enqueue_content_extraction_job
            max_chunks = int(os.getenv("CONTENT_EXTRACT_MAX_CHUNKS", "6"))
            enqueue_content_extraction_job(
                twin_id=twin_id,
                source_id=source_id,
                tenant_id=tenant_id,
                source_type="youtube",
                max_chunks=max_chunks
            )
            log_ingestion_event(source_id, twin_id, "info", f"Graph extraction queued (max_chunks={max_chunks})")
        except Exception as e:
            log_ingestion_event(source_id, twin_id, "warning", f"Graph extraction enqueue failed: {e}")
            logger.warning("[Ingestion] Warning: Failed to enqueue graph extraction for source %s: %s", source_id, e)

        return num_chunks
    except Exception as e:
        try:
            err = build_error(
                code="YOUTUBE_INDEXING_FAILED",
                message=str(e),
                provider=provider,
                step="indexed",
                correlation_id=correlation_id,
                raw={"video_id": video_id, "url": url},
                exc=e,
            )
            finish_step(
                event_id="",
                source_id=source_id,
                twin_id=twin_id,
                provider=provider,
                step="indexed",
                status="error",
                correlation_id=correlation_id,
                error=err,
            )
        except Exception:
            pass
        logger.error("Error processing YouTube content: %s", e)
        log_ingestion_event(source_id, twin_id, "error", f"Error processing YouTube content: {e}")
        supabase.table("sources").update({"status": "error", "health_status": "failed"}).eq("id", source_id).execute()
        raise e
