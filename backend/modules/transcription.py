# modules/transcription.py
"""
Multi-provider transcription module.

Supports:
1. Google Gemini 1.5 Flash (Free tier, multimodal) - via google.genai
2. OpenAI Whisper (Fallback)
"""
import logging
import os

logger = logging.getLogger(__name__)

def transcribe_with_gemini(audio_path: str) -> str | None:
    """
    Transcribe audio using Google Gemini 1.5 Flash via the new google.genai SDK.

    Benefits:
    - Free tier (generous limits)
    - 1M token context window (handles long audio)
    - Multimodal native support
    - Can format/clean output via prompting

    Args:
        audio_path: Path to audio file (mp3, m4a, wav, etc.)

    Returns:
        Transcribed text or None if failed
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("[Gemini] GOOGLE_API_KEY not set, skipping Gemini transcription")
        return None

    try:
        from google import genai
        from google.genai import types

        # Initialize client
        client = genai.Client(api_key=api_key)

        # Read audio file
        with open(audio_path, "rb") as f:
            audio_data = f.read()

        # Determine mime type
        ext = os.path.splitext(audio_path)[1].lower()
        mime_types = {
            '.mp3': 'audio/mp3',
            '.m4a': 'audio/mp4',
            '.wav': 'audio/wav',
            '.webm': 'audio/webm',
            '.ogg': 'audio/ogg',
        }
        mime_type = mime_types.get(ext, 'audio/mp3')

        # Create content with audio
        audio_part = types.Part.from_bytes(data=audio_data, mime_type=mime_type)

        # Prompt for clean transcription
        prompt = """Transcribe this audio accurately.

        Instructions:
        - Output ONLY the transcribed text
        - Remove filler words like 'um', 'uh', 'you know'
        - Use proper punctuation and capitalization
        - Preserve the speaker's meaning and tone
        - Do not add any commentary or metadata
        """

        # Generate transcription
        model = os.getenv("GEMINI_EXTRACTION_MODEL", "gemini-3.5-flash-lite")
        response = client.models.generate_content(
            model=model,
            contents=[prompt, audio_part]
        )

        if response.text:
            logger.info("[Gemini] Successfully transcribed %s characters", len(response.text))
            return response.text.strip()

        return None

    except ImportError as e:
        logger.warning("[Gemini] google-genai package not installed: %s", e)
        logger.warning("[Gemini] Install with: pip install google-genai")
        return None
    except Exception as e:
        logger.error("[Gemini] Transcription error: %s", e)
        return None


def transcribe_with_whisper(audio_path: str) -> str | None:
    """
    Transcribe audio using OpenAI Whisper API.

    Args:
        audio_path: Path to audio file

    Returns:
        Transcribed text or None if failed
    """
    try:
        from modules.clients import get_openai_client

        client = get_openai_client()
        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )

        logger.info("[Whisper] Successfully transcribed %s characters", len(transcript.text))
        return transcript.text

    except Exception as e:
        logger.error("[Whisper] Transcription error: %s", e)
        return None


def transcribe_audio_multi(audio_path: str) -> str:
    """
    Transcribe audio using multiple providers with fallback.

    Order of preference:
    1. Google Gemini (free, high quality)
    2. OpenAI Whisper (paid, reliable)

    Args:
        audio_path: Path to audio file

    Returns:
        Transcribed text

    Raises:
        ValueError: If all transcription methods fail
    """
    # Try Gemini first (free)
    text = transcribe_with_gemini(audio_path)
    if text:
        return text

    # Fallback to Whisper
    text = transcribe_with_whisper(audio_path)
    if text:
        return text

    raise ValueError("All transcription methods failed. Check API keys and audio file format.")
