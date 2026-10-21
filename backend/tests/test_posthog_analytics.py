from types import SimpleNamespace


def test_ph_capture_exception_calls_native_sdk_method(monkeypatch):
    from modules import posthog_analytics

    captured = {}

    class FakeClient:
        def capture_exception(self, exc, **kwargs):
            captured["exc"] = exc
            captured.update(kwargs)

    posthog_analytics._client = None
    monkeypatch.setattr(posthog_analytics, "_get_client", lambda: FakeClient())

    err = ValueError("boom")
    posthog_analytics.ph_capture_exception(
        err, user_id="user-1", context={"job_id": "job-1"}
    )

    assert captured["exc"] is err
    assert captured["distinct_id"] == "user-1"
    assert captured["properties"] == {"job_id": "job-1"}


def test_ph_capture_exception_defaults_distinct_id_when_no_user(monkeypatch):
    from modules import posthog_analytics

    captured = {}

    class FakeClient:
        def capture_exception(self, exc, **kwargs):
            captured.update(kwargs)

    posthog_analytics._client = None
    monkeypatch.setattr(posthog_analytics, "_get_client", lambda: FakeClient())

    posthog_analytics.ph_capture_exception(ValueError("boom"))

    assert captured["distinct_id"] == "anonymous-backend"
    assert captured["properties"] == {}


def test_ph_capture_exception_is_fire_and_forget_on_sdk_failure(monkeypatch):
    """A PostHog SDK failure must never propagate to the caller."""
    from modules import posthog_analytics

    class FailingClient:
        def capture_exception(self, exc, **kwargs):
            raise RuntimeError("posthog is down")

    posthog_analytics._client = None
    monkeypatch.setattr(posthog_analytics, "_get_client", lambda: FailingClient())

    # Must not raise.
    posthog_analytics.ph_capture_exception(ValueError("boom"))


def test_ph_capture_exception_noop_when_client_not_configured(monkeypatch):
    from modules import posthog_analytics

    monkeypatch.setattr(posthog_analytics, "_get_client", lambda: None)

    # Must not raise even though there's no client to call.
    posthog_analytics.ph_capture_exception(ValueError("boom"))


def test_posthog_client_uses_project_api_key(monkeypatch):
    from modules import posthog_analytics

    captured_kwargs = {}

    class FakePosthog:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        def shutdown(self):
            pass

    posthog_analytics._client = None
    monkeypatch.setenv("POSTHOG_API_KEY", "ph_test_key")
    monkeypatch.setenv("POSTHOG_HOST", "https://posthog.example.com")
    monkeypatch.setitem(__import__("sys").modules, "posthog", SimpleNamespace(Posthog=FakePosthog))

    try:
        client = posthog_analytics._get_client()
    finally:
        posthog_analytics._client = None

    assert isinstance(client, FakePosthog)
    assert captured_kwargs["project_api_key"] == "ph_test_key"
    assert captured_kwargs["host"] == "https://posthog.example.com"
    assert "api_key" not in captured_kwargs


class _QueueBackedFakePosthog:
    """Mimics the SDK's consumer-thread model with no network.

    capture() enqueues; a consumer thread drains the queue; flush() is
    queue.join(); shutdown() flushes then stops the consumer. A capture after
    shutdown therefore leaves an item nobody will ever drain, and the next
    flush() blocks forever, which is exactly the #330 deadlock.
    """

    instances: list = []

    def __init__(self, **kwargs):
        import queue
        import threading

        self.queue = queue.Queue()
        self.sent: list = []
        self._stop = threading.Event()
        self._consumer = threading.Thread(target=self._drain, daemon=True)
        self._consumer.start()
        type(self).instances.append(self)

    def _drain(self):
        import queue

        while not self._stop.is_set():
            try:
                item = self.queue.get(timeout=0.01)
            except queue.Empty:
                continue
            self.sent.append(item)
            self.queue.task_done()

    def capture(self, **kwargs):
        self.queue.put(kwargs["event"])

    def flush(self):
        self.queue.join()

    def shutdown(self):
        self.flush()
        self._stop.set()
        self._consumer.join()


def _run_with_timeout(fn, timeout=2.0):
    import threading

    worker = threading.Thread(target=fn, daemon=True)
    worker.start()
    worker.join(timeout)
    return not worker.is_alive()


def _install_fake_posthog(monkeypatch):
    import sys
    from types import SimpleNamespace

    from modules import posthog_analytics

    _QueueBackedFakePosthog.instances = []
    monkeypatch.setattr(posthog_analytics, "_client", None)
    monkeypatch.setattr(posthog_analytics, "_atexit_registered", True)
    monkeypatch.setenv("POSTHOG_API_KEY", "ph_dummy_key")
    monkeypatch.setitem(
        sys.modules,
        "posthog",
        SimpleNamespace(Posthog=_QueueBackedFakePosthog),
    )
    return posthog_analytics


def test_shutdown_twice_across_lifespans_does_not_deadlock(monkeypatch):
    """Two app lifespans in one process: capture -> shutdown, twice (#330)."""
    ph = _install_fake_posthog(monkeypatch)

    def two_lifespans():
        ph.ph_capture(user_id="u1", event="first")
        ph.ph_shutdown()
        ph.ph_capture(user_id="u1", event="second")
        ph.ph_shutdown()

    assert _run_with_timeout(two_lifespans), "second ph_shutdown() deadlocked"

    first, second = _QueueBackedFakePosthog.instances
    assert first is not second, "capture after shutdown must build a fresh client"
    assert first.sent == ["first"]
    assert second.sent == ["second"]
    assert ph._client is None


def test_shutdown_is_idempotent(monkeypatch):
    ph = _install_fake_posthog(monkeypatch)
    ph.ph_capture(user_id="u1", event="only")

    assert _run_with_timeout(lambda: [ph.ph_shutdown() for _ in range(3)])
    assert len(_QueueBackedFakePosthog.instances) == 1
    assert _QueueBackedFakePosthog.instances[0].sent == ["only"]


def test_shutdown_without_client_is_noop(monkeypatch):
    from modules import posthog_analytics

    monkeypatch.setattr(posthog_analytics, "_client", None)
    posthog_analytics.ph_shutdown()
    assert posthog_analytics._client is None


def test_shutdown_failure_is_logged_and_client_cleared(monkeypatch, caplog):
    from modules import posthog_analytics

    class BrokenClient:
        def shutdown(self):
            raise RuntimeError("flush failed")

    monkeypatch.setattr(posthog_analytics, "_client", BrokenClient())
    with caplog.at_level("WARNING", logger="modules.posthog_analytics"):
        posthog_analytics.ph_shutdown()

    assert posthog_analytics._client is None
    assert "shutdown failed" in caplog.text


def test_atexit_registered_once_across_client_rebuilds(monkeypatch):
    ph = _install_fake_posthog(monkeypatch)
    monkeypatch.setattr(ph, "_atexit_registered", False)
    registered = []
    monkeypatch.setattr(ph.atexit, "register", lambda fn: registered.append(fn))

    for _ in range(3):
        ph.ph_capture(user_id="u1", event="e")
        ph.ph_shutdown()

    assert registered == [ph._shutdown]
