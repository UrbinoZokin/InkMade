"""End-to-end encryption of setup traffic (setupcrypto.py).

What has to hold: the setup code never travels, only the right code opens
anything, and a sealed message can't be replayed, reflected, altered or
passed off as another kind -- each of which would hand a listener the WiFi
password or the Google token, or let them change the device.
"""
from pathlib import Path

import pytest

pytest.importorskip("spake2")

from inkycal.provisioning import setupcrypto  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CODE = "482913"


def _paired(app_code=CODE, pi_code=CODE):
    app = setupcrypto.AppHandshake(app_code)
    answer, pi_channel = setupcrypto.pi_handshake(pi_code, app.message)
    return app.finish(answer), pi_channel


def test_the_pi_and_the_app_run_the_same_code():
    """Two copies, because the halves ship to different machines. They must
    not drift: a mismatch only fails on a real device, as a code that's
    "wrong" no matter what anyone types."""
    pi_copy = REPO / "src" / "inkycal" / "provisioning" / "setupcrypto.py"
    app_copy = REPO / "companion" / "inkycal_companion" / "setupcrypto.py"

    assert app_copy.read_bytes() == pi_copy.read_bytes()


def test_the_same_code_opens_both_ways():
    app, pi = _paired()

    assert pi.open(app.seal(b"secret wifi", setupcrypto.WIFI), setupcrypto.WIFI) == b"secret wifi"
    assert app.open(pi.seal(b"ok", setupcrypto.WIFI_REPLY), setupcrypto.WIFI_REPLY) == b"ok"


def test_the_code_never_travels():
    app = setupcrypto.AppHandshake(CODE)
    answer, _pi = setupcrypto.pi_handshake(CODE, app.message)

    for message in (app.message, answer):
        assert CODE.encode() not in message


def test_a_wrong_code_opens_nothing():
    app, pi = _paired(app_code="000000")

    with pytest.raises(setupcrypto.BadSeal):
        pi.open(app.seal(b"secret wifi", setupcrypto.WIFI), setupcrypto.WIFI)


def test_a_replay_is_refused():
    app, pi = _paired()
    sealed = app.seal(b"secret wifi", setupcrypto.WIFI)
    pi.open(sealed, setupcrypto.WIFI)

    with pytest.raises(setupcrypto.BadSeal):
        pi.open(sealed, setupcrypto.WIFI)


def test_a_message_cant_pass_as_another_kind():
    app, pi = _paired()

    with pytest.raises(setupcrypto.BadSeal):
        pi.open(app.seal(b"evil token", setupcrypto.WIFI), setupcrypto.GOOGLE_TOKEN)


def test_a_message_cant_be_sent_back_to_its_sender():
    app, _pi = _paired()

    with pytest.raises(setupcrypto.BadSeal):
        app.open(app.seal(b"ok", setupcrypto.WIFI_REPLY), setupcrypto.WIFI_REPLY)


@pytest.mark.parametrize("flip", [0, 12, -1])  # nonce, ciphertext, tag
def test_an_altered_message_is_refused(flip):
    app, pi = _paired()
    sealed = bytearray(app.seal(b"secret wifi", setupcrypto.WIFI))
    sealed[flip] ^= 1

    with pytest.raises(setupcrypto.BadSeal):
        pi.open(bytes(sealed), setupcrypto.WIFI)


@pytest.mark.parametrize("sealed", [b"", b"short", b"\x00" * 27])
def test_a_truncated_message_is_refused(sealed):
    _app, pi = _paired()

    with pytest.raises(setupcrypto.BadSeal):
        pi.open(sealed, setupcrypto.WIFI)


@pytest.mark.parametrize(
    "message",
    [b"", b"A", b"B" + b"\x00" * 32, b"A" + b"\xff" * 32, b"A" + b"\x01" * 10],
    ids=["empty", "side-only", "wrong-side", "not-in-group", "too-short"],
)
def test_something_that_isnt_a_key_exchange_is_refused(message):
    with pytest.raises(setupcrypto.BadHandshake):
        setupcrypto.pi_handshake(CODE, message)


def test_each_exchange_has_its_own_key():
    """Something recorded in one setup session is no use in the next."""
    app_one, pi_one = _paired()
    _app_two, pi_two = _paired()
    sealed = app_one.seal(b"secret wifi", setupcrypto.WIFI)

    with pytest.raises(setupcrypto.BadSeal):
        pi_two.open(sealed, setupcrypto.WIFI)
    assert pi_one.open(sealed, setupcrypto.WIFI) == b"secret wifi"


@pytest.mark.parametrize("typed", ["482 913", "482-913", " 482913 "])
def test_the_code_is_the_same_however_it_is_typed(typed):
    """The panel shows "482 913". Keying the exchange by the spacing would
    make the right code look wrong -- and count against the session."""
    app, pi = _paired(app_code=typed)

    assert pi.open(app.seal(b"secret wifi", setupcrypto.WIFI), setupcrypto.WIFI) == b"secret wifi"
