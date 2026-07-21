"""Application construction regression tests."""

from app.main import create_app


def test_create_app_registers_health_routes() -> None:
    app = create_app()

    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/ready" in paths
