def test_extract_text_from_pdf_handles_none_pages(monkeypatch):
    from modules import ingestion_file as ingestion

    class _Page:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class _Reader:
        def __init__(self, *_args, **_kwargs):
            self.pages = [_Page(None), _Page("LinkedIn profile summary"), _Page("")]

    monkeypatch.setattr(ingestion, "PdfReader", _Reader)

    text = ingestion.extract_text_from_pdf("dummy.pdf")
    assert text == "LinkedIn profile summary"


def test_extract_pdf_text_and_chunk_entries_assigns_page_fallback_section_metadata(monkeypatch):
    from modules import ingestion_file as ingestion

    class _Page:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class _Reader:
        def __init__(self, *_args, **_kwargs):
            self.pages = [_Page("First page content"), _Page("Second page content")]

    monkeypatch.setattr(ingestion, "PdfReader", _Reader)

    text, chunk_entries = ingestion.extract_pdf_text_and_chunk_entries(
        "dummy.pdf",
        doc_name="Manual.pdf",
        chunk_size=1000,
        overlap=200,
    )

    assert "First page content" in text
    assert "Second page content" in text
    assert chunk_entries
    assert any(entry.get("section_title") == "page_1" for entry in chunk_entries)
    assert any(entry.get("section_path") == "Manual.pdf/page_1" for entry in chunk_entries)
    assert any(entry.get("page_number") == 1 for entry in chunk_entries)
