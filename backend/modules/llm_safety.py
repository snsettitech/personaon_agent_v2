"""
LLM Safety Module
=================

Provides input sanitization and prompt injection protection for all LLM interactions.

SECURITY FIXES (HIGH Bug H3):
- Input sanitization before sending to LLM
- Prompt injection detection and prevention
- Content length limits
- Output validation
"""

import re
import html
from dataclasses import dataclass

# Maximum content length to prevent DoS via huge inputs
MAX_PROMPT_LENGTH = 100000  # 100K characters
MAX_USER_CONTENT_LENGTH = 50000  # 50K characters for user content

# Prompt injection patterns to detect and block
PROMPT_INJECTION_PATTERNS = [
    # Direct instruction overrides
    r"ignore\s+(all\s+)?(previous\s+)?instructions",
    r"disregard\s+(all\s+)?(previous\s+)?(instructions|commands)",
    r"forget\s+(all\s+)?(previous\s+)?(instructions|commands|context)",
    r"you\s+are\s+now\s+.*",
    r"your\s+new\s+(role|instructions|persona)\s+is",
    r"system\s*:\s*",
    r"assistant\s*:\s*",
    r"user\s*:\s*",

    # Jailbreak attempts
    r"DAN\s*\(|do\s+anything\s+now",
    r"jailbreak",
    r"developer\s+mode",
    r"sudo\s+mode",
    r"root\s+access",

    # Delimiter manipulation
    r"```\s*system",
    r"<\s*system\s*>",
    r"\[\s*system\s*\]",

    # Unicode obfuscation
    r"[\u200B-\u200F]",  # Zero-width characters
    r"[\u2060-\u2064]",  # Word joiners
    r"[\uFEFF]",         # BOM
]

# Compiled patterns for efficiency
_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in PROMPT_INJECTION_PATTERNS]


@dataclass
class SanitizationResult:
    """Result of content sanitization."""
    sanitized_text: str
    is_safe: bool
    warnings: list[str]
    was_modified: bool
    original_length: int


class PromptInjectionError(Exception):
    """Raised when prompt injection is detected."""
    pass


class ContentTooLongError(Exception):
    """Raised when content exceeds maximum length."""
    pass


def _remove_invisible_chars(text: str) -> str:
    """Remove invisible Unicode characters used for obfuscation."""
    # Zero-width characters and other invisible Unicode
    invisible = [
        '\u200B', '\u200C', '\u200D', '\u200E', '\u200F',  # Zero-width chars
        '\u2060', '\u2061', '\u2062', '\u2063', '\u2064',  # Formatting chars
        '\uFEFF',  # BOM
        '\u180E',  # Mongolian vowel separator
    ]
    for char in invisible:
        text = text.replace(char, '')
    return text


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace to prevent spacing-based attacks."""
    # Replace multiple spaces/newlines with single space
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def detect_prompt_injection(text: str) -> tuple[bool, list[str]]:
    """
    Detect potential prompt injection attacks.

    Args:
        text: Input text to analyze

    Returns:
        Tuple of (is_safe, list_of_detected_patterns)
    """
    warnings = []

    # Check length first
    if len(text) > MAX_USER_CONTENT_LENGTH:
        warnings.append(f"Content exceeds maximum length ({len(text)} > {MAX_USER_CONTENT_LENGTH})")

    # Check for injection patterns
    _ = text.lower()

    for i, pattern in enumerate(_COMPILED_PATTERNS):
        if pattern.search(text):
            pattern_name = PROMPT_INJECTION_PATTERNS[i][:50]  # Truncate for readability
            warnings.append(f"Potential prompt injection detected: {pattern_name}")

    # Check for excessive newlines (might be trying to break out of context)
    newline_count = text.count('\n')
    if newline_count > 100:
        warnings.append(f"Excessive newlines detected ({newline_count})")

    return len(warnings) == 0, warnings


def sanitize_for_llm(
    text: str,
    max_length: int = None,
    allow_html: bool = False,
    strict_mode: bool = True
) -> SanitizationResult:
    """
    Sanitize user content before sending to LLM.

    Args:
        text: User input text
        max_length: Maximum allowed length (uses default if not specified)
        allow_html: Whether to allow HTML (default: strip it)
        strict_mode: If True, raise on injection detection; if False, just warn

    Returns:
        SanitizationResult with sanitized text and metadata

    Raises:
        PromptInjectionError: If injection detected in strict mode
        ContentTooLongError: If content exceeds max length
    """
    original_length = len(text)
    max_length = max_length or MAX_USER_CONTENT_LENGTH
    warnings = []
    was_modified = False

    # Check length
    if len(text) > max_length:
        if strict_mode:
            raise ContentTooLongError(
                f"Content too long: {len(text)} characters (max: {max_length})"
            )
        text = text[:max_length]
        warnings.append(f"Content truncated from {original_length} to {max_length}")
        was_modified = True

    # Remove invisible characters
    text_clean = _remove_invisible_chars(text)
    if text_clean != text:
        warnings.append("Removed invisible Unicode characters")
        was_modified = True
        text = text_clean

    # Detect prompt injection
    is_safe, injection_warnings = detect_prompt_injection(text)
    warnings.extend(injection_warnings)

    if injection_warnings and strict_mode:
        raise PromptInjectionError(
            f"Prompt injection detected: {'; '.join(injection_warnings[:3])}"
        )

    # HTML escape if not allowed
    if not allow_html:
        text_escaped = html.escape(text)
        if text_escaped != text:
            text = text_escaped
            warnings.append("HTML entities escaped")
            was_modified = True

    # Normalize whitespace
    text_normalized = _normalize_whitespace(text)
    if text_normalized != text:
        text = text_normalized
        warnings.append("Whitespace normalized")
        was_modified = True

    return SanitizationResult(
        sanitized_text=text,
        is_safe=is_safe,
        warnings=warnings,
        was_modified=was_modified,
        original_length=original_length
    )


def sanitize_chat_messages(
    messages: list[dict],
    strict_mode: bool = True
) -> list[dict]:
    """
    Sanitize all messages in a chat completion request.

    Args:
        messages: List of message dicts with 'role' and 'content'
        strict_mode: Whether to raise on injection detection

    Returns:
        Sanitized messages
    """
    sanitized = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Only sanitize user content (system/assistant assumed safe)
        if role == "user":
            result = sanitize_for_llm(content, strict_mode=strict_mode)
            sanitized.append({
                "role": role,
                "content": result.sanitized_text
            })
        else:
            sanitized.append(msg)

    return sanitized


def create_safe_prompt(
    system_prompt: str,
    user_content: str,
    strict_mode: bool = True
) -> list[dict]:
    """
    Create a safe chat completion prompt with sanitized user content.

    Args:
        system_prompt: System instructions (assumed safe)
        user_content: User content to sanitize
        strict_mode: Whether to raise on injection detection

    Returns:
        List of message dicts ready for OpenAI API
    """
    # Sanitize user content
    result = sanitize_for_llm(user_content, strict_mode=strict_mode)

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": result.sanitized_text}
    ]


def validate_llm_output(
    output: str,
    expected_format: str = None,
    max_length: int = MAX_PROMPT_LENGTH
) -> tuple[bool, list[str]]:
    """
    Validate LLM output for safety issues.

    Args:
        output: LLM-generated text
        expected_format: Optional format validation (e.g., 'json', 'markdown')
        max_length: Maximum expected length

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []

    # Check length
    if len(output) > max_length:
        issues.append(f"Output too long: {len(output)} chars")

    # Check for null bytes
    if '\x00' in output:
        issues.append("Null bytes in output")

    # Check for control characters (except normal whitespace)
    control_chars = re.findall(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', output)
    if control_chars:
        issues.append(f"Unexpected control characters: {len(control_chars)} found")

    # Format validation
    if expected_format == "json":
        try:
            import json
            json.loads(output)
        except json.JSONDecodeError as e:
            issues.append(f"Invalid JSON: {e}")

    return len(issues) == 0, issues


# Convenience function for common use case
def safe_llm_content(text: str) -> str:
    """
    Quick sanitize function that returns sanitized text or raises on issues.

    Args:
        text: User input to sanitize

    Returns:
        Sanitized text

    Raises:
        PromptInjectionError: On injection detection
        ContentTooLongError: On length violation
    """
    result = sanitize_for_llm(text, strict_mode=True)
    return result.sanitized_text
