"""List an app's routes as (path, methods) in match order, across FastAPI versions.

FastAPI 0.141+ keeps each include_router() call as one `_IncludedRouter`
entry in `app.routes` instead of copying its routes in flat, so tests that
walk `app.routes` looking for a path stop seeing included routes. Expand
those entries through `effective_candidates()`, which yields the routes with
their full (prefixed) paths in the order the router matches them.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def iter_routes(app: Any) -> Iterator[tuple[str, set[str]]]:
    for route in app.routes:
        expand = getattr(route, "effective_candidates", None)
        entries = expand() if callable(expand) else [route]
        for entry in entries:
            yield getattr(entry, "path", ""), set(getattr(entry, "methods", None) or ())
