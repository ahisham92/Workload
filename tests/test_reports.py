"""The five report views, checked against the workbook's own figures.

Every number here also exists on a sheet in the workbook, calculated by Excel
the last time the file was opened.  Those cached results are an independent
check on the arithmetic, and this is where the two are held together.
"""

import datetime as dt

import pytest

from workload_app import reports


@pytest.fixture(scope="session")
def report(readonly_wb):
    return reports.build(readonly_wb, "year", 2026)


class TestPeriods:
    def test_the_quarter_grid_comes_from_phasing(self, readonly_wb):
        quarters = reports.read_quarters(readonly_wb)
        assert quarters[0].opening is True
        labelled = [q for q in quarters if not q.opening]
        assert labelled[0].label == "Q1-24"
        assert labelled[0].year == 2024
        assert labelled[0].start == dt.date(2024, 1, 1)
        assert labelled[0].end == dt.date(2024, 3, 31)

    def test_a_year_selects_its_four_quarters(self, readonly_wb):
        quarters = reports.read_quarters(readonly_wb)
        period = reports.resolve_period(quarters, "year", 2026)
        assert len(period.quarters) == 4
        assert period.start == dt.date(2026, 1, 1)
        assert period.end == dt.date(2026, 12, 31)
        assert period.label == "Full year 2026"

    def test_a_quarter_selects_one(self, readonly_wb):
        quarters = reports.read_quarters(readonly_wb)
        period = reports.resolve_period(quarters, "quarter", 2026, "Q2")
        assert len(period.quarters) == 1
        assert period.quarters[0].label == "Q2-26"
        assert period.start == dt.date(2026, 4, 1)

    def test_all_time_reaches_back_past_every_project(self, readonly_wb):
        quarters = reports.read_quarters(readonly_wb)
        period = reports.resolve_period(quarters, "all")
        # The opening column's start is the workbook's "beginning of time"
        # sentinel; only that it precedes everything matters.
        assert period.start < dt.date(1900, 2, 1)
        assert period.end > dt.date(2027, 1, 1)

    def test_elapsed_fraction_is_bounded(self, readonly_wb):
        quarter = [q for q in reports.read_quarters(readonly_wb) if not q.opening][0]
        assert quarter.elapsed_fraction(dt.date(2020, 1, 1)) == 0.0
        assert quarter.elapsed_fraction(dt.date(2030, 1, 1)) == 1.0
        assert 0 < quarter.elapsed_fraction(dt.date(2024, 2, 15)) < 1


class TestAgainstTheWorkbook:
    """Cross-checks against what Excel last calculated for full-year 2026."""

    @pytest.mark.parametrize("key,expected", [
        ("planned_mm", 44.83),
        ("actual_mm", 17.91),
        ("earned_mm", 14.19),
        ("profit_mm", -3.72),
        ("planned_to_date_mm", 32.72),
        ("capacity_to_date_mm", 24.16),
        ("utilisation", 0.7411),
        ("plan_adherence", 0.5473),
    ])
    def test_team_totals_match(self, report, key, expected):
        assert report.team[key] == pytest.approx(expected, abs=0.01)

    @pytest.mark.parametrize("engineer,actual,planned,earned", [
        ("Ahmed", 5.7216, 12.2282, 5.1198),
        ("Osama", 5.9946, 9.3574, 3.7813),
        ("Kirolos", 6.1919, 11.1366, 5.2850),
    ])
    def test_per_engineer_allocation_matches(self, report, engineer, actual,
                                             planned, earned):
        person = report.per_engineer[engineer]
        assert person["actual_mm"] == pytest.approx(actual, abs=0.01)
        assert person["planned_to_date_mm"] == pytest.approx(planned, abs=0.01)
        assert person["earned_mm"] == pytest.approx(earned, abs=0.01)

    @pytest.mark.parametrize("engineer,cpi", [
        ("Ahmed", 0.8372), ("Osama", 0.6402), ("Kirolos", 0.7319),
    ])
    def test_type_weighted_cpi_matches(self, report, engineer, cpi):
        assert report.per_engineer[engineer]["type_weighted_cpi"] == pytest.approx(
            cpi, abs=0.001)

    @pytest.mark.parametrize("engineer,remaining", [
        ("Ahmed", 22.9617), ("Osama", 24.4405), ("Kirolos", 6.1659),
    ])
    def test_remaining_on_hand_matches(self, report, engineer, remaining):
        """Only in-scope work live in the period counts as still to do."""
        assert report.per_engineer[engineer]["remaining_mm"] == pytest.approx(
            remaining, abs=0.01)

    def test_share_of_team_time_matches(self, report):
        shares = {n: e["share_of_team_time"]
                  for n, e in report.per_engineer.items()}
        assert shares["Ahmed"] == pytest.approx(0.3195, abs=0.001)
        assert shares["Osama"] == pytest.approx(0.3347, abs=0.001)
        assert shares["Kirolos"] == pytest.approx(0.3458, abs=0.001)
        assert sum(shares.values()) == pytest.approx(1.0, abs=0.001)

    def test_projects_worked_matches(self, report):
        worked = {n: e["projects_worked"] for n, e in report.per_engineer.items()}
        assert worked == {"Ahmed": 6, "Osama": 4, "Kirolos": 7}


class TestScorecard:
    def test_the_ranking_matches_the_workbook(self, report):
        ranking = [(r["rank"], r["engineer"]) for r in report.scorecard["ranking"]]
        assert ranking == [(1, "Ahmed"), (2, "Kirolos"), (3, "Osama")]

    @pytest.mark.parametrize("engineer,score", [
        ("Ahmed", 84.75), ("Kirolos", 83.86), ("Osama", 75.99),
    ])
    def test_the_weighted_scores_match(self, report, engineer, score):
        assert report.scorecard["totals"][engineer] == pytest.approx(score, abs=0.1)

    def test_higher_is_better_scores_against_the_best(self, report):
        factor = next(f for f in report.scorecard["factors"]
                      if f["direction"] == "higher")
        assert max(factor["scores"].values()) == pytest.approx(100.0, abs=0.1)

    def test_a_target_factor_peaks_on_target(self, report):
        factor = next(f for f in report.scorecard["factors"]
                      if f["direction"] == "target")
        for name, value in factor["values"].items():
            expected = max(0.0, (1 - min(1.0, abs(value - factor["target"])
                                         / factor["target"])) * 100)
            assert factor["scores"][name] == pytest.approx(expected, abs=0.1)

    def test_the_weights_add_up(self, report):
        assert sum(f["weight"] for f in report.scorecard["factors"]) == pytest.approx(1.0)

    def test_every_engineer_has_a_strongest_and_weakest_factor(self, report):
        for row in report.scorecard["ranking"]:
            assert row["strongest"] and row["weakest"]


class TestProjectRows:
    def test_planned_is_the_budget_spread_across_the_dates(self, readonly_wb, report):
        """Each project's budget is spread across the days it runs."""
        total = sum(p["planned_mm"] or 0 for p in report.projects)
        assert total == pytest.approx(report.team["planned_mm"], abs=0.01)
        assert all(p["planned_mm"] >= 0 for p in report.projects)

    def test_a_period_earns_in_proportion_to_the_effort_spent_in_it(self, report):
        for row in report.projects:
            if row["lifetime_actual_mm"]:
                ratio = row["actual_mm"] / row["lifetime_actual_mm"]
                assert row["earned_mm"] == pytest.approx(
                    ratio * row["lifetime_earned_mm"], abs=0.01)
            else:
                assert row["earned_mm"] == 0

    def test_projects_outside_the_period_are_not_live(self, report):
        for row in report.projects:
            if row["end"] and row["end"] < "2026-01-01":
                assert row["live"] is False

    def test_the_status_split_only_counts_live_projects(self, report):
        live = sum(1 for p in report.projects if p["live"])
        assert sum(s["projects"] for s in report.by_status) == live


class TestOtherBlocks:
    def test_quarterly_effort_adds_up_to_the_engineers(self, readonly_wb):
        whole = reports.build(readonly_wb, "all")
        for row in whole.quarterly:
            assert row["total"] == pytest.approx(
                sum(row[n] for n in whole.engineers), abs=0.01)

    def test_quarterly_only_lists_quarters_with_effort(self, report):
        assert all(row["total"] > 0 for row in report.quarterly)

    def test_delivery_mix_shares_sum_to_one(self, report):
        total = sum(row["share"] or 0 for row in report.delivery_mix)
        assert total == pytest.approx(1.0, abs=0.001)

    def test_the_whole_set_serialises(self, report):
        import json
        payload = json.loads(json.dumps(report.to_dict(), default=str))
        assert set(payload) >= {"period", "team", "per_engineer", "scorecard",
                                "by_status", "quarterly", "projects"}


class TestAnotherPeriod:
    def test_a_quarter_is_a_subset_of_its_year(self, readonly_wb):
        year = reports.build(readonly_wb, "year", 2026)
        quarter = reports.build(readonly_wb, "quarter", 2026, "Q1")
        assert quarter.team["actual_mm"] <= year.team["actual_mm"]
        assert quarter.period.label == "Q1 2026"

    def test_the_four_quarters_add_up_to_the_year(self, readonly_wb):
        year = reports.build(readonly_wb, "year", 2026)
        total = sum(reports.build(readonly_wb, "quarter", 2026, q).team["actual_mm"]
                    for q in ("Q1", "Q2", "Q3", "Q4"))
        assert total == pytest.approx(year.team["actual_mm"], abs=0.02)

    def test_all_time_is_at_least_the_year(self, readonly_wb):
        whole = reports.build(readonly_wb, "all")
        year = reports.build(readonly_wb, "year", 2026)
        assert whole.team["actual_mm"] >= year.team["actual_mm"]


class TestScorecardFactorsComeFromTheWorkbook:
    def test_they_are_read_from_the_scorecard_sheet(self, readonly_wb):
        factors = readonly_wb.scorecard_factors()
        assert [f["factor"] for f in factors][:2] == [
            "Efficiency (CPI, type-weighted)", "Utilisation vs capacity"]
        assert factors[0]["direction"] == "higher"
        assert factors[1]["direction"] == "target"
        assert factors[1]["target"] == 1.0
        assert sum(f["weight"] for f in factors) == pytest.approx(1.0)

    def test_changing_a_weight_changes_the_ranking(self, wb):
        from workload_app import reports
        before = reports.build(wb, "year", 2026).scorecard["totals"]
        factors = wb.scorecard_factors()
        # Put everything on the one factor Osama leads on.
        for factor in factors:
            factor["weight"] = 1.0 if factor["key"] == "plan_adherence" else 0.0
        wb.save_scorecard_factors(factors)
        after = reports.build(wb, "year", 2026).scorecard
        assert after["totals"] != before
        assert after["ranking"][0]["engineer"] == "Osama"

    def test_weights_that_do_not_total_one_hundred_are_refused(self, wb):
        from workload_app.workbook import ValidationError
        factors = wb.scorecard_factors()
        factors[0]["weight"] = 0.9
        with pytest.raises(ValidationError, match="not 100%"):
            wb.save_scorecard_factors(factors)

    def test_a_target_factor_needs_a_target(self, wb):
        from workload_app.workbook import ValidationError
        factors = wb.scorecard_factors()
        for factor in factors:
            if factor["direction"] == "target":
                factor["target"] = 0
        with pytest.raises(ValidationError, match="needs one that is not zero"):
            wb.save_scorecard_factors(factors)

    def test_a_factor_can_be_renamed_and_comes_back(self, wb):
        factors = wb.scorecard_factors()
        factors[0]["factor"] = "Value per man-month"
        wb.save_scorecard_factors(factors)
        assert wb.scorecard_factors()[0]["factor"] == "Value per man-month"


class TestHeroes:
    def test_only_finished_months_are_scored(self, report, readonly_wb):
        """The as-at date is 1 September, so August is the last month scored."""
        assert [m["month"] for m in report.monthly][-1] == "2026-08"
        assert all(m["month"] < "2026-09" for m in report.monthly)

    def test_every_scored_month_has_a_winner(self, report):
        for month in report.monthly:
            if month["booked"]:
                assert month["hero"] in report.engineers
                assert 0 <= month["hero_score"] <= 100

    def test_the_hero_of_the_month_is_the_top_scorer(self, report):
        for month in report.monthly:
            if not month["booked"]:
                continue
            best = max(month["scores"], key=lambda name: month["scores"][name])
            assert month["hero"] == best

    def test_the_month_shown_is_the_most_recent_scored_one(self, report):
        assert report.heroes["month"]["month"] == "2026-08"
        assert report.heroes["month"]["label"] == "August 2026"

    def test_the_hero_of_the_year_tops_the_period_scorecard(self, report):
        assert report.heroes["year"]["engineer"] == (
            report.scorecard["ranking"][0]["engineer"])

    def test_months_won_adds_up_to_the_months_scored(self, report):
        assert sum(report.heroes["wins"].values()) == report.heroes["months_scored"]

    def test_a_period_with_no_finished_month_has_no_hero(self, readonly_wb):
        from workload_app import reports
        far = reports.build(readonly_wb, "year", 2028)
        assert far.monthly == []
        assert far.heroes["month"] is None
