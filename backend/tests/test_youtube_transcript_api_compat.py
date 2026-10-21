import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.ingestion import fetch_youtube_transcript_compat


def test_fetch_youtube_transcript_compat_new_fetch_api():
    class FakeFetched:
        def to_raw_data(self):
            return [{"text": "hello"}, {"text": "world"}]

    class FakeYTA:
        def fetch(self, video_id, languages=("en",)):  # noqa: ANN001
            assert video_id == "abc123xyz00"
            return FakeFetched()

    text, error, method = fetch_youtube_transcript_compat("abc123xyz00", yta_cls=FakeYTA)
    assert text == "hello world"
    assert error is None
    assert method == "fetch"


def test_fetch_youtube_transcript_compat_new_list_api_fallback():
    class FakeTranscript:
        def fetch(self, preserve_formatting=False):  # noqa: ANN001
            return [{"text": "from"}, {"text": "list"}]

    class FakeList:
        def find_manually_created_transcript(self, _langs):  # noqa: ANN001
            raise Exception("no manual transcript")

        def find_generated_transcript(self, _langs):  # noqa: ANN001
            return FakeTranscript()

    class FakeYTA:
        def fetch(self, video_id, languages=("en",)):  # noqa: ANN001
            raise Exception("fetch not available")

        def list(self, video_id):  # noqa: ANN001
            assert video_id == "abc123xyz00"
            return FakeList()

    text, error, method = fetch_youtube_transcript_compat("abc123xyz00", yta_cls=FakeYTA)
    assert text == "from list"
    assert error is None
    assert method == "list"


def test_fetch_youtube_transcript_compat_old_static_api_fallback():
    class FakeOldYTA:
        @staticmethod
        def get_transcript(video_id):  # noqa: ANN001
            assert video_id == "abc123xyz00"
            return [{"text": "legacy"}, {"text": "api"}]

    text, error, method = fetch_youtube_transcript_compat("abc123xyz00", yta_cls=FakeOldYTA)
    assert text == "legacy api"
    assert error is None
    assert method == "get_transcript"
