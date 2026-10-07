import pytest


@pytest.fixture(autouse=True)
def _no_threaded(request, monkeypatch):
    """Fake ACIS clients answer every request alike, so threaded lookups are off unless a test asks for them."""
    if "threaded" not in request.keywords:
        monkeypatch.setattr("gridded_climo.stations.USE_THREADED", False)
