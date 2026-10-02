"""A setup session's rules: the one-time code, the cap on wrong codes, the clock.

Six digits are only safe because guessing is capped. These pin down the cap
and everything that decides whether a supplied code counts as a guess.
"""
import pytest

from inkycal.provisioning import session as s
from inkycal.provisioning.session import CLOSED, MISSING, OK, WRONG, SetupSession


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_codes_are_six_digits():
    for _ in range(50):
        code = s.new_code()
        assert len(code) == 6 and code.isdigit()


def test_the_right_code_is_accepted_however_it_is_spaced():
    session = SetupSession("482913")

    assert session.check("482913") == OK
    assert session.check("482 913") == OK
    assert session.check(" 482-913 ") == OK


def test_no_code_is_not_a_guess():
    session = SetupSession("482913", max_wrong=2)

    for _ in range(10):
        assert session.check("") == MISSING
    assert session.wrong_codes_left == 2
    assert not session.ended


def test_wrong_codes_count_down_and_then_end_the_session():
    session = SetupSession("482913", max_wrong=5)

    for left in (4, 3, 2, 1):
        assert session.check("000000") == WRONG
        assert session.wrong_codes_left == left
        assert not session.ended

    assert session.check("111111") == WRONG
    assert session.ended
    assert session.end_reason == "too many wrong setup codes"
    # Once it's over, not even the right code gets in.
    assert session.check("482913") == CLOSED


def test_a_code_of_the_wrong_length_is_still_a_guess():
    session = SetupSession("482913", max_wrong=5)

    assert session.check("4829130") == WRONG
    assert session.wrong_codes_left == 4


def test_it_times_out():
    clock = _Clock()
    session = SetupSession("482913", seconds=600, clock=clock)

    clock.now += 599
    assert session.check("482913") == OK

    clock.now += 1
    assert session.ended
    assert session.end_reason == "timed out"
    assert session.check("482913") == CLOSED


def test_button_c_restarts_the_clock():
    clock = _Clock()
    session = SetupSession("482913", seconds=600, clock=clock)

    clock.now += 500
    assert session.extend() is True
    assert session.seconds_left() == 600

    clock.now += 599
    assert not session.ended


def test_nothing_reopens_a_finished_session():
    session = SetupSession("482913")
    session.finish("Google token delivered")

    assert session.extend() is False
    assert session.check("482913") == CLOSED
    assert session.end_reason == "Google token delivered"


def test_the_first_reason_to_end_is_the_one_kept():
    session = SetupSession("482913", max_wrong=1)
    session.check("000000")
    session.finish("Google token delivered")

    assert session.end_reason == "too many wrong setup codes"


@pytest.mark.parametrize(
    "setup, verdict, expected",
    [
        pytest.param(lambda ses: None, MISSING, "setup code shown", id="missing"),
        pytest.param(lambda ses: ses.check("000000"), WRONG, "4 tries left", id="wrong"),
        pytest.param(
            lambda ses: [ses.check("000000") for _ in range(4)], WRONG, "1 try left", id="last-try"
        ),
        pytest.param(
            lambda ses: [ses.check("000000") for _ in range(5)], WRONG, "Too many wrong", id="locked-out"
        ),
        pytest.param(lambda ses: ses.finish("timed out"), CLOSED, "Press button C", id="ended"),
    ],
)
def test_refusals_say_what_to_do_next(setup, verdict, expected):
    session = SetupSession("482913", max_wrong=5)
    setup(session)

    assert expected in s.refusal(verdict, session)
