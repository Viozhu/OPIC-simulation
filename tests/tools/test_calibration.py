from __future__ import annotations

import re

import pytest

from opic.core.rubric import ActflLevel

from rater_calibration import HUMAN_EXACT, actfl_band, report


def test_the_three_opic_mid_bands_collapse_to_one_actfl_band():
    """OPIc splits ACTFL's single Intermediate Mid three ways for Korea.

    Counting agreement on the split scale and comparing it to a figure ACTFL
    computed on the unsplit one would hold this rater to a finer resolution
    than the humans it is being measured against.
    """
    assert {actfl_band(level) for level in (ActflLevel.IM1, ActflLevel.IM2, ActflLevel.IM3)} == {"IM"}


@pytest.mark.parametrize("level", [ActflLevel.IL, ActflLevel.IH, ActflLevel.AL, ActflLevel.NH])
def test_every_other_band_survives_the_collapse_unchanged(level):
    assert actfl_band(level) == level.name


def test_a_rater_that_grades_low_reports_a_negative_gap():
    """The whole point of the tool: which direction, and by how much."""
    rows = [(f"s{i}", ActflLevel.IH, ActflLevel.IM2) for i in range(3)]
    text = report(rows)
    assert "-2.00 bands" in text
    assert "grades BELOW the real exam" in text


def test_a_rater_that_grades_high_reports_a_positive_gap():
    rows = [(f"s{i}", ActflLevel.IM1, ActflLevel.IM3) for i in range(3)]
    text = report(rows)
    assert "+2.00 bands" in text
    assert "grades ABOVE the real exam" in text


def test_a_rater_that_agrees_reports_no_direction():
    rows = [(f"s{i}", ActflLevel.IM2, ActflLevel.IM2) for i in range(3)]
    text = report(rows)
    assert "+0.00 bands" in text
    assert "sits on the real exam" in text


def test_agreement_on_the_actfl_scale_is_the_looser_of_the_two():
    """IM1 against IM2 is a miss on our scale and a hit on ACTFL's."""
    rows = [(f"s{i}", ActflLevel.IM1, ActflLevel.IM2) for i in range(4)]
    first_percentage = {
        line.split("  ")[0].strip(): re.search(r"\d+%", line).group(0)
        for line in report(rows).splitlines()
        if line.startswith("exact (")
    }
    assert first_percentage["exact (OPIc scale)"] == "0%"
    assert first_percentage["exact (ACTFL scale)"] == "100%"


def test_the_human_ceiling_is_shown_beside_every_run():
    """A rater at 74% is not failing — it is where two trained humans sit."""
    rows = [("s0", ActflLevel.IM2, ActflLevel.IM2)]
    text = report(rows)
    assert f"{HUMAN_EXACT:.0%}" in text
    assert "AAR/OPIc/ACE/R-2015-001" in text


def test_a_small_sample_says_so_rather_than_reporting_a_percentage_straight():
    rows = [("s0", ActflLevel.IM2, ActflLevel.IM2)]
    assert "too few to read a percentage from" in report(rows)


def test_ten_sessions_stops_warning():
    rows = [(f"s{i}", ActflLevel.IM2, ActflLevel.IM2) for i in range(10)]
    assert "too few" not in report(rows)


def test_no_labelled_sessions_is_said_plainly():
    assert report([]) == "No labelled sessions to compare."
