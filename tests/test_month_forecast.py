"""People needed month by month, against people we have and an 85% line
(Ahmed, 2026-10-12). Synthetic data only."""

from __future__ import annotations

import datetime as dt

import pytest

from workload_app import needs
from workload_app import tasks as task_sheet

TODAY = dt.date(2026, 10, 12)
ROSTER = [{"name": "Eng A", "grade": "engineer"}, {"name": "Eng B", "grade": "engineer"},
          {"name": "Draft C", "grade": "drafter"}]


def _config():
    config = task_sheet.settings(None)
    config["holidays"] = set()
    return config


def _prep(job, start, end, hours_a_day, who="Eng A"):
    config = _config()
    return [(who, job, day, hours_a_day)
            for day in task_sheet.working_days(start, end, config)]


def test_each_month_counts_its_own_submission_work_in_engineers():
    config = _config()
    prep = _prep("J-1", dt.date(2026, 11, 1), dt.date(2026, 11, 30), 8.5) \
        + _prep("J-1", dt.date(2026, 11, 1), dt.date(2026, 11, 30), 8.5, who="Eng B") \
        + _prep("J-2", dt.date(2026, 11, 1), dt.date(2026, 11, 30), 8.5, who="")
    data = needs.monthly(prep=prep, roster=ROSTER, config=config, today=TODAY)
    months = {m["month"]: m for m in data["months"]}
    assert len(data["months"]) == needs.MONTHS_AHEAD and data["engineers"] == 2
    nov = months["2026-11"]
    # three people's full days of work in November, two engineers to do it
    assert nov["needed"] == pytest.approx(3.0, abs=0.01)
    assert nov["have"] == pytest.approx(2.0, abs=0.01)
    assert nov["well_used"] == pytest.approx(1.7, abs=0.01)
    assert nov["jobs"][0]["number"] == "J-1" and not nov["nothing_planned"]
    # October starts today, not on the 1st, and has no work
    assert months["2026-10"]["from"] == "2026-10-12" and months["2026-10"]["needed"] == 0
    # December is past the last submission: not planned, rather than free
    assert months["2026-12"]["nothing_planned"]
    assert data["planned_until"] == "2026-11-30"


def test_a_draftsman_s_work_is_not_counted_against_engineers():
    prep = _prep("J-1", dt.date(2026, 11, 2), dt.date(2026, 11, 6), 8.5, who="Draft C")
    data = needs.monthly(prep=prep, roster=ROSTER, config=_config(), today=TODAY)
    assert all(m["hours"] == 0 for m in data["months"])


def test_leading_people_takes_from_the_hours_we_have():
    plain = needs.monthly(prep=[], roster=ROSTER, config=_config(), today=TODAY)
    led = needs.monthly(prep=[], roster=ROSTER, config=_config(), today=TODAY,
                        management={"Eng A": 4.25})
    assert led["months"][1]["have"] == pytest.approx(plain["months"][1]["have"] - 0.5, abs=0.01)


def test_the_chart_is_on_people_needed():
    import pathlib
    static = pathlib.Path(needs.__file__).parent / "static"
    planner_js = (static / "planner.js").read_text(encoding="utf-8")
    assert "needsByMonth(needs)" in planner_js and "charts.monthForecast(" in planner_js
    assert "monthForecast" in (static / "charts.js").read_text(encoding="utf-8")
    service = (static.parent / "service.py").read_text(encoding="utf-8")
    assert 'data["by_month"] = needs_module.monthly(' in service
