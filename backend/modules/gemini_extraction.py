"""
Gemini 2.5 extraction module.

Provides Gemini-powered alternatives for:
  - Web content extraction (from raw HTML)
  - PDF text extraction (native multimodal)
  - Audio transcription (native audio)
  - Chunk content analysis (replaces GPT-4o-mini)

All functions are async-compatible and gracefully return None on failure
so callers can fall back to existing strategies.

Toggle with env var: GEMINI_EXTRACTION_ENABLED=true (default: true)
Model: GEMINI_EXTRACTION_MODEL (default: gemini-3.5-flash-lite)
"""

import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

GEMINI_EXTRACTION_ENABLED = os.getenv("GEMINI_EXTRACTION_ENABLED", "true").lower() == "true"
GEMINI_EXTRACTION_MODEL = os.getenv("GEMINI_EXTRACTION_MODEL", "gemini-3.5-flash-lite")


def _get_genai_client():
    """Return a native google.genai Client."""
    import google.genai as genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured")
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------------------------
# Web content extraction
# ---------------------------------------------------------------------------

async def gemini_extract_web_content(url: str, html: str) -> str | None:
    """
    Use Gemini to extract clean, meaningful content from raw HTML.

    Returns extracted text, or None if extraction fails.
    Gemini understands page structure (nav, ads, main content) far better
    than BeautifulSoup get_text().
    """
    if not GEMINI_EXTRACTION_ENABLED:
        return None
    if not html or len(html) < 100:
        return None

    # Truncate HTML to avoid token limits (Gemini 2.5 Flash: 1M ctx)
    html_input = html[:400_000]

    prompt = (
        "You are a content extraction assistant. "
        "From the HTML below, extract the main meaningful content of the page. "
        "Remove all navigation, ads, footers, cookie banners, scripts, and boilerplate. "
        "Keep: article text, headings, lists, key metadata (author, date, title). "
        "Format the output as clean readable text with headings preserved using markdown (#, ##). "
        "Do NOT summarise — preserve the full content.\n\n"
        f"URL: {url}\n\n"
        f"HTML:\n{html_input}"
    )

    try:
        client = _get_genai_client()
        response = client.models.generate_content(
            model=GEMINI_EXTRACTION_MODEL,
            contents=prompt,
        )
        text = (response.text or "").strip()
        if len(text) < 50:
            logger.warning("[GeminiExtract] Web extraction too short (%d chars) for %s", len(text), url)
            return None
        logger.info("[GeminiExtract] Web extraction: %d chars from %s", len(text), url)
        return text
    except Exception as exc:
        logger.warning("[GeminiExtract] Web extraction failed for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

async def gemini_extract_pdf(file_path: str) -> str | None:
    """
    Use Gemini's native PDF understanding to extract text.

    Handles scanned PDFs, images embedded in PDFs, and complex table layouts
    that PyPDF2 cannot handle. Returns extracted text or None on failure.
    """
    if not GEMINI_EXTRACTION_ENABLED:
        return None
    if not os.path.exists(file_path):
        return None

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return None
    # Gemini Files API limit: 2GB, but large PDFs are slow — cap at 50MB
    if file_size > 50 * 1024 * 1024:
        logger.warning("[GeminiExtract] PDF too large (%d MB), skipping Gemini extraction", file_size // (1024 * 1024))
        return None

    try:
        import google.genai as genai
        import google.genai.types as genai_types

        client = _get_genai_client()

        logger.info("[GeminiExtract] Uploading PDF to Gemini Files API: %s", file_path)
        uploaded_file = client.files.upload(
            file=file_path,
            config=genai_types.UploadFileConfig(mime_type="application/pdf"),
        )

        response = client.models.generate_content(
            model=GEMINI_EXTRACTION_MODEL,
            contents=[
                uploaded_file,
                (
                    "Extract ALL text content from this PDF document. "
                    "Preserve the document structure using markdown headings. "
                    "Include tables as pipe-separated markdown tables. "
                    "Do NOT summarise — output the complete verbatim content."
                ),
            ],
        )

        text = (response.text or "").strip()

        # Clean up uploaded file to avoid storage accumulation
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass

        if len(text) < 20:
            logger.warning("[GeminiExtract] PDF extraction too short (%d chars)", len(text))
            return None

        logger.info("[GeminiExtract] PDF extraction: %d chars from %s", len(text), file_path)
        return text

    except Exception as exc:
        logger.warning("[GeminiExtract] PDF extraction failed for %s: %s", file_path, exc)
        return None


# ---------------------------------------------------------------------------
# Audio transcription
# ---------------------------------------------------------------------------

async def gemini_transcribe_audio(file_path: str) -> str | None:
    """
    Use Gemini to transcribe audio files (MP3, WAV, M4A, WEBM).

    Returns transcript text or None on failure.
    """
    if not GEMINI_EXTRACTION_ENABLED:
        return None
    if not os.path.exists(file_path):
        return None

    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        ".mp3": "audio/mp3",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }
    mime_type = mime_map.get(ext)
    if not mime_type:
        logger.warning("[GeminiExtract] Unsupported audio format: %s", ext)
        return None

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return None

    try:
        import google.genai as genai
        import google.genai.types as genai_types

        client = _get_genai_client()

        logger.info("[GeminiExtract] Uploading audio to Gemini Files API: %s (%s)", file_path, mime_type)
        uploaded_file = client.files.upload(
            file=file_path,
            config=genai_types.UploadFileConfig(mime_type=mime_type),
        )

        response = client.models.generate_content(
            model=GEMINI_EXTRACTION_MODEL,
            contents=[
                uploaded_file,
                (
                    "Transcribe the audio content verbatim. "
                    "Format as clean readable text with paragraph breaks where natural pauses occur. "
                    "Include speaker labels if multiple speakers are identifiable (Speaker 1:, Speaker 2:). "
                    "Do NOT summarise or add commentary."
                ),
            ],
        )

        text = (response.text or "").strip()

        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass

        if len(text) < 20:
            logger.warning("[GeminiExtract] Audio transcription too short (%d chars)", len(text))
            return None

        logger.info("[GeminiExtract] Audio transcription: %d chars from %s", len(text), file_path)
        return text

    except Exception as exc:
        logger.warning("[GeminiExtract] Audio transcription failed for %s: %s", file_path, exc)
        return None


# ---------------------------------------------------------------------------
# Chunk content analysis (replaces GPT-4o-mini)
# ---------------------------------------------------------------------------

async def gemini_analyze_chunk(text: str) -> dict | None:
    """
    Analyze a text chunk using Gemini 2.5 Flash.

    Generates synthetic questions, category (FACT/OPINION), tone, and opinion map.
    Returns dict or None on failure (caller should fall back to safe defaults).
    """
    if not GEMINI_EXTRACTION_ENABLED:
        return None
    if not text or len(text.strip()) < 10:
        return None

    prompt = f"""Analyze the following text chunk. Return a valid JSON object with exactly these fields:
- "questions": array of 3 brief questions this chunk answers
- "category": "OPINION" if it contains personal beliefs, values, or perspectives; "FACT" if it is objective information
- "tone": single word describing the writing style (e.g. Assertive, Casual, Technical, Thoughtful, Analytical)
- "opinion_map": if category is "OPINION", an object with {{ "topic": string, "stance": string, "intensity": integer 1-10 }}; if "FACT", set to null

Respond with ONLY the JSON object, no markdown, no explanation.

Text chunk:
{text[:3000]}"""

    try:
        client = _get_genai_client()
        response = client.models.generate_content(
            model=GEMINI_EXTRACTION_MODEL,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        raw = (response.text or "").strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            # Gemini occasionally returns slightly malformed JSON — truncate at last valid object
            last_brace = raw.rfind("}")
            result = json.loads(raw[:last_brace + 1] if last_brace != -1 else raw)
        logger.debug("[GeminiExtract] Chunk analysis complete, category=%s", result.get("category"))
        return result
    except Exception as exc:
        logger.warning("[GeminiExtract] Chunk analysis failed: %s", exc)
        return None
