from tests._routes import iter_routes


def test_sources_diagnostics_routes_are_not_shadowed():
    from main import app

    detail_path = "/sources/{twin_id}/{source_id}"
    events_path = "/sources/{source_id}/events"
    logs_path = "/sources/{source_id}/logs"

    route_entries = [
        (index, path, methods) for index, (path, methods) in enumerate(iter_routes(app))
    ]

    detail_idx = next(
        index
        for index, path, methods in route_entries
        if path == detail_path and "GET" in methods
    )
    events_idx = next(
        index
        for index, path, methods in route_entries
        if path == events_path and "GET" in methods
    )
    logs_idx = next(
        index
        for index, path, methods in route_entries
        if path == logs_path and "GET" in methods
    )

    assert events_idx < detail_idx
    assert logs_idx < detail_idx
