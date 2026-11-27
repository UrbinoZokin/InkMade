import pytest


@pytest.fixture(autouse=True)
def _no_real_address_lookups(monkeypatch):
    """Keep every test off OpenStreetMap's geocoder.

    run_once looks event addresses up whenever it draws the daily view, so any
    test with a location on an event would otherwise send it out. A Geocoder
    built without a session (as run_once builds it) fails its lookups instead,
    which leaves those events on home weather. Tests of the lookups themselves
    pass a session of their own.
    """

    def offline():
        raise OSError("no address lookups in tests")

    monkeypatch.setattr("inkycal.geocode._default_session", offline)
