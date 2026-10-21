# backend/modules/_core/artifact_pipeline.py
"""Artifact injection pipeline for cognitive graph seeding.

The pipeline:
1. Accepts an uploaded file (PDF, DOCX, TXT, MD).
2. Extracts raw text using appropriate library.
3. Calls the Scribe engine to extract structured output.
4. Returns the structured data for graph storage.
"""
from pathlib import Path
from typing import Any
import logging

from modules._core.scribe_engine import extract_structured_output, score_confidence

logger = logging.getLogger(__name__)


def extract_text_from_file(file_path: str) -> str:
    """Extract text content from a file based on its extension.

    Supports: PDF, DOCX, TXT, MD, and common text formats.

    Args:
        file_path: Path to the file on disk.
    Returns:
        Extracted text content as a string.
    Raises:
        ValueError: If the file type is not supported.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix in [".txt", ".md", ".markdown", ".rst", ".json", ".yaml", ".yml"]:
        # Plain text files
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    elif suffix == ".pdf":
        # PDF extraction using pdfminer.six (if available)
        try:
            from pdfminer.high_level import extract_text as pdf_extract_text
            return pdf_extract_text(str(path))
        except ImportError:
            logger.warning("pdfminer.six not installed; falling back to basic PDF read")
            # Fallback: try to read as bytes and decode (won't work well)
            with path.open("rb") as f:
                raw = f.read()
            # Attempt naive text extraction
            try:
                return raw.decode("utf-8", errors="ignore")
            except Exception:
                return ""

    elif suffix in [".docx"]:
        # DOCX extraction using python-docx (if available)
        try:
            from docx import Document
            doc = Document(str(path))
            paragraphs = [p.text for p in doc.paragraphs]
            return "\n".join(paragraphs)
        except ImportError:
            logger.warning("python-docx not installed; cannot extract DOCX")
            return ""

    elif suffix in [".doc"]:
        # Legacy .doc files - not supported without additional libraries
        logger.warning(".doc files not supported; use .docx format")
        return ""

    elif suffix in [".html", ".htm"]:
        # HTML extraction
        try:
            from bs4 import BeautifulSoup
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
            return soup.get_text(separator="\n")
        except ImportError:
            logger.warning("bs4 not installed; falling back to raw HTML")
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                return f.read()

    else:
        raise ValueError(f"Unsupported file type: {suffix}")


def process_artifact(file_path: str, scribe_schema: dict[str, Any]) -> dict[str, Any]:
    """Process an uploaded artifact and return structured extraction.

    Args:
        file_path: Path to the uploaded file on disk.
        scribe_schema: The JSON schema defining the expected structured output.
    Returns:
        A dict with keys: node_updates, edge_updates, narratives,
        contradictions, missing_slots.
    """
    # Step 1: Extract text
    try:
        text = extract_text_from_file(file_path)
    except ValueError as e:
        logger.error(f"Failed to extract text: {e}")
        return {
            "node_updates": [],
            "edge_updates": [],
            "narratives": [],
            "contradictions": [],
            "missing_slots": [],
            "error": str(e),
        }

    if not text.strip():
        logger.warning(f"No text extracted from {file_path}")
        return {
            "node_updates": [],
            "edge_updates": [],
            "narratives": [],
            "contradictions": [],
            "missing_slots": [],
            "warning": "No text content extracted",
        }

    # Step 2: Call Scribe engine to extract structured data
    # Pass the extracted text and schema to the scribe engine
    extracted = extract_structured_output(text, scribe_schema)

    # Step 3: Score confidence
    confidence = score_confidence(extracted)
    extracted["confidence"] = confidence

    # Step 4: Log audit event (placeholder)
    logger.info(f"Artifact processed: {file_path}, confidence={confidence}")

    return extracted

