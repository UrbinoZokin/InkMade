"""A setup session's rules: the one-time code, the cap on wrong codes, the clock.

Six digits are only safe because guessing is capped, so these pin down what
counts as a guess: each key exchange is one, shown up by its first message
failing to open -- and nothing else is.
"""
import pytest

pytest.importorskip("spake2")

from inkycal.provisioning import session as s  # noqa: E402
from inkycal.provisioning import setupcrypto  # noqa: E402
from inkycal.provisioning.session import CLOSED, OK, UNPAIRED, WRONG, SessionClosed, SetupSession  # noqa: E402

CODE = "482913"
WIFI = setupcrypto.WIFI


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _try(session: SetupSession, code: str, payload: bytes = b'{"ssid": "Home"}'):
    """What the companion app does: pair with `code`, then send one sealed message."""
    app = setupcrypto.AppHandshake(code)
    pairing, answer = session.pair(app.message)
    channel = app.finish(answer)
    return session.open(pairing, channel.seal(payload, WIFI), WIFI), pairing, channel


def test_codes_are_six_digits():
    for _ in range(50):
        code = s.new_code()
        assert len(code) == 6 and code.isdigit()


def test_the_right_code_opens_the_message():
    session = SetupSession(CODE)

    (verdict, plaintext, channel), _pairing, _channel = _try(session, CODE)

    assert verdict == OK
    assert plaintext == b'{"ssid": "Home"}'
    assert channel is not None


def test_a_wrong_code_counts_as_one_guess():
    session = SetupSession(CODE, max_wrong=5)

    (verdict, plaintext, _channel), _pairing, _app = _try(session, "000000")

    assert verdict == WRONG
    assert plaintext is None
    assert session.wrong_codes_left == 4


def test_a_wrong_code_spends_its_exchange():
    """One guess per exchange: the same exchange can't be tried again."""
    session = SetupSession(CODE, max_wrong=5)
    (_verdict, _plaintext, _c), pairing, channel = _try(session, "000000")

    verdict, _plaintext, _c = session.open(pairing, channel.seal(b"again", WIFI), WIFI)

    assert verdict == UNPAIRED
    assert session.wrong_codes_left == 4, "a spent exchange is not another guess"


def test_wrong_codes_count_down_and_then_end_the_session():
    session = SetupSession(CODE, max_wrong=5)

    for left in (4, 3, 2, 1):
        assert _try(session, "000000")[0][0] == WRONG
        assert session.wrong_codes_left == left
        assert not session.ended

    assert _try(session, "111111")[0][0] == WRONG
    assert session.ended
    assert session.end_reason == "too many wrong setup codes"
    # Once it's over, not even the right code gets in.
    with pytest.raises(SessionClosed):
        _try(session, CODE)


def test_pairing_alone_is_not_a_guess():
    """An exchange proves nothing until a message is sent over it."""
    session = SetupSession(CODE, max_wrong=2)

    for _ in range(10):
        session.pair(setupcrypto.AppHandshake("000000").message)

    assert session.wrong_codes_left == 2
    assert not session.ended


def test_a_message_for_an_unknown_exchange_is_not_a_guess():
    session = SetupSession(CODE, max_wrong=2)

    for pairing in ("made-up", "", None):
        assert session.open(pairing, b"\x00" * 40, WIFI)[0] == UNPAIRED

    assert session.wrong_codes_left == 2


def test_a_malformed_exchange_is_refused_without_counting():
    session = SetupSession(CODE, max_wrong=2)

    with pytest.raises(setupcrypto.BadHandshake):
        session.pair(b"not a key exchange")

    assert session.wrong_codes_left == 2


def test_old_exchanges_make_way_for_new_ones():
    """Someone flooding the agent with exchanges can't make it hoard keys."""
    session = SetupSession(CODE)
    app = setupcrypto.AppHandshake(CODE)
    first, answer = session.pair(app.message)
    channel = app.finish(answer)

    for _ in range(s.MAX_PAIRINGS):
        session.pair(setupcrypto.AppHandshake(CODE).message)

    assert session.open(first, channel.seal(b"late", WIFI), WIFI)[0] == UNPAIRED


def test_it_times_out():
    clock = _Clock()
    session = SetupSession(CODE, seconds=600, clock=clock)

    clock.now += 599
    assert not session.ended

    clock.now += 1
    assert session.ended
    assert session.end_reason == "timed out"
    assert session.open("anything", b"", WIFI)[0] == CLOSED


def test_button_c_restarts_the_clock():
    clock = _Clock()
    session = SetupSession(CODE, seconds=600, clock=clock)

    clock.now += 500
    assert session.extend() is True
    assert session.seconds_left() == 600

    clock.now += 599
    assert not session.ended


def test_nothing_reopens_a_finished_session():
    session = SetupSession(CODE)
    session.finish("Google token delivered")

    assert session.extend() is False
    with pytest.raises(SessionClosed):
        _try(session, CODE)
    assert session.end_reason == "Google token delivered"


def test_the_first_reason_to_end_is_the_one_kept():
    session = SetupSession(CODE, max_wrong=1)
    _try(session, "000000")
    session.finish("Google token delivered")

    assert session.end_reason == "too many wrong setup codes"


@pytest.mark.parametrize(
    "setup, verdict, expected",
    [
        pytest.param(lambda ses: _try(ses, "000000"), WRONG, "4 tries left", id="wrong"),
        pytest.param(lambda ses: [_try(ses, "000000") for _ in range(4)], WRONG, "1 try left", id="last-try"),
        pytest.param(lambda ses: [_try(ses, "000000") for _ in range(5)], WRONG, "Too many wrong", id="locked-out"),
        pytest.param(lambda ses: None, UNPAIRED, "Start again", id="unpaired"),
        pytest.param(lambda ses: ses.finish("timed out"), CLOSED, "Press button C", id="ended"),
    ],
)
def test_refusals_say_what_to_do_next(setup, verdict, expected):
    session = SetupSession(CODE, max_wrong=5)
    setup(session)

    assert expected in s.refusal(verdict, session)
