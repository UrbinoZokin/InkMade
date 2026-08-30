"""The panel lock that keeps two refreshes off the SPI bus at once."""
import fcntl
import sys
import types

import pytest
from PIL import Image

from inkycal import display_inky
from inkycal.display_inky import display_lock, show_on_inky


@pytest.fixture
def lock_path(tmp_path):
    return str(tmp_path / "display.lock")


def _hold(path):
    """An independently flock()ed handle on `path`, as a competing render has."""
    handle = open(path, "a+", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def _is_locked(path) -> bool:
    with open(path, "a+", encoding="utf-8") as probe:
        try:
            fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
        return False


def test_acquires_an_uncontended_lock(lock_path):
    with display_lock(lock_path, timeout=1) as acquired:
        assert acquired is True


def test_holds_the_lock_for_the_whole_block(lock_path):
    with display_lock(lock_path, timeout=1):
        assert _is_locked(lock_path)


def test_releases_the_lock_on_the_way_out(lock_path):
    with display_lock(lock_path, timeout=1):
        pass

    assert not _is_locked(lock_path)


def test_releases_the_lock_when_the_render_raises(lock_path):
    with pytest.raises(RuntimeError):
        with display_lock(lock_path, timeout=1):
            raise RuntimeError("panel exploded")

    assert not _is_locked(lock_path)


def test_waits_out_a_holder_then_refreshes_anyway(lock_path):
    """A wedged holder must not cost us the refresh -- that's the failure this
    lock exists to avoid, not one it should cause."""
    holder = _hold(lock_path)
    try:
        with display_lock(lock_path, timeout=0.1) as acquired:
            assert acquired is False
    finally:
        holder.close()


def test_acquires_once_the_previous_render_finishes(lock_path):
    holder = _hold(lock_path)
    holder.close()

    with display_lock(lock_path, timeout=1) as acquired:
        assert acquired is True


def test_renders_unlocked_when_the_lock_directory_is_unusable(tmp_path):
    """No /var/lib/inkycal to lock in is a reason to render unlocked, never a
    reason not to render."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")

    with display_lock(str(blocker / "display.lock"), timeout=1) as acquired:
        assert acquired is False


def test_renders_unlocked_when_the_lock_path_is_malformed(tmp_path):
    """A bad INKYCAL_DISPLAY_LOCK raises ValueError, not OSError; neither may
    take the display down with it."""
    with display_lock(str(tmp_path / "displ\0ck"), timeout=1) as acquired:
        assert acquired is False


def test_default_path_follows_the_module_constant(tmp_path, monkeypatch):
    """Callers pass no path, so the constant has to be read per call rather
    than frozen into a default argument at import."""
    lock = tmp_path / "elsewhere.lock"
    monkeypatch.setattr(display_inky, "DISPLAY_LOCK_PATH", str(lock))

    with display_lock(timeout=1) as acquired:
        assert acquired is True
        assert lock.exists()


class _FakeInky:
    """Stands in for the panel, recording whether the lock was held at show()."""

    def __init__(self, lock_path):
        self._lock_path = lock_path
        self.locked_during_show = None
        self.border = None
        self.image = None

    def set_border(self, border):
        self.border = border

    def set_image(self, img):
        self.image = img

    def show(self):
        self.locked_during_show = _is_locked(self._lock_path)


@pytest.fixture
def fake_inky(monkeypatch, lock_path):
    """Install a fake `inky.auto` so show_on_inky runs without hardware."""
    panel = _FakeInky(lock_path)
    auto_module = types.ModuleType("inky.auto")
    auto_module.auto = lambda ask_user=False, verbose=False: panel
    inky_module = types.ModuleType("inky")
    inky_module.auto = auto_module
    monkeypatch.setitem(sys.modules, "inky", inky_module)
    monkeypatch.setitem(sys.modules, "inky.auto", auto_module)
    monkeypatch.setattr(display_inky, "DISPLAY_LOCK_PATH", lock_path)
    return panel


def test_show_on_inky_holds_the_lock_while_driving_the_panel(fake_inky, lock_path):
    show_on_inky(Image.new("RGB", (8, 8), "white"))

    assert fake_inky.locked_during_show is True
    assert not _is_locked(lock_path), "lock should be released once the refresh is done"


def test_show_on_inky_converts_and_rotates_before_taking_the_lock(fake_inky):
    show_on_inky(Image.new("RGB", (8, 4), "white"), rotate_degrees=90, border="black")

    assert fake_inky.image.mode == "P"
    assert fake_inky.image.size == (4, 8)
    assert fake_inky.border == "black"
