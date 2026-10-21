from modules.ingestion_diagnostics import build_error


def test_youtube_auth_unavailable_is_not_retryable():
    err = build_error(
        code="YOUTUBE_TRANSCRIPT_UNAVAILABLE",
        message="Auth required",
        provider="youtube",
        step="fetching",
        provider_error_code="auth",
    )
    assert err["retryable"] is False


def test_youtube_network_unavailable_is_retryable():
    err = build_error(
        code="YOUTUBE_TRANSCRIPT_UNAVAILABLE",
        message="Temporary network issue",
        provider="youtube",
        step="fetching",
        provider_error_code="network",
    )
    assert err["retryable"] is True
