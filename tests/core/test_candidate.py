from __future__ import annotations

import pytest

from opic.core.candidate import (
    CandidateError,
    describe_candidate_error_ko,
    validate_candidate,
)


def test_a_name_and_a_plausible_address_pass():
    assert validate_candidate("김민준", "minjun@example.com") == ()


@pytest.mark.parametrize(
    "name, email, expected",
    [
        ("", "a@b.com", CandidateError.EMPTY_NAME),
        ("   ", "a@b.com", CandidateError.EMPTY_NAME),
        ("김" * 201, "a@b.com", CandidateError.LONG_NAME),
        ("김민준", "", CandidateError.BAD_EMAIL),
        ("김민준", "minjun", CandidateError.BAD_EMAIL),
        ("김민준", "min jun@example.com", CandidateError.BAD_EMAIL),
        ("김민준", "a@b@example.com", CandidateError.BAD_EMAIL),
        ("김민준", "@example.com", CandidateError.BAD_EMAIL),
        ("김민준", "minjun@", CandidateError.BAD_EMAIL),
        ("김민준", "minjun@example", CandidateError.BAD_EMAIL),
        ("김민준", "a" * 195 + "@b.com", CandidateError.LONG_EMAIL),
    ],
)
def test_what_is_refused(name, email, expected):
    assert expected in validate_candidate(name, email)


def test_every_error_has_korean_to_show():
    for error in CandidateError:
        assert describe_candidate_error_ko(error).strip()
