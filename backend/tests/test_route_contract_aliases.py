from tests._routes import iter_routes


def _has_route(path: str, method: str) -> bool:
    from main import app

    return any(
        route_path == path and method.upper() in methods
        for route_path, methods in iter_routes(app)
    )


def test_governance_sources_twin_alias_route_exists():
    assert _has_route("/twins/{twin_id}/sources", "GET")
    assert _has_route("/sources/{twin_id}", "GET")


def test_invitation_acceptance_routes_exist():
    assert _has_route("/auth/invitation/{token}", "GET")
    assert _has_route("/auth/accept-invitation", "POST")


def test_public_marketplace_route_exists():
    assert _has_route("/public/marketplace", "GET")
