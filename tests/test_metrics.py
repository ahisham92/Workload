"""The figures the app shows must agree with the ones the workbook computes.

The workbook caches the result of every formula, so the values Excel last wrote
are available to compare against.  The app deliberately recomputes rather than
reading those caches -- they go stale the moment anything is edited -- which
makes them an independent check on the arithmetic here.
"""

import pytest

from workload_app import metrics


@pytest.fixture(scope="session")
def index(readonly_wb):
    return metrics.TimesheetIndex(readonly_wb)


@pytest.fixture(scope="session")
def projects(readonly_wb, index):
    return {row["number"]: row for row in metrics.project_rows(readonly_wb, index)}


class TestTimesheetIndex:
    def test_it_reads_all_three_sheets(self, index):
        assert len(index.rows) == 7682
        assert {row["engineer"] for row in index.rows} == {"Ahmed", "Osama", "Kirolos"}

    def test_hours_can_be_narrowed_by_phase_and_person(self, index):
        total = index.hours_for_job("N25185-0100D")
        by_person = sum(index.hours_for_job("N25185-0100D", engineer=name)
                        for name in ("Ahmed", "Osama", "Kirolos"))
        assert total == pytest.approx(by_person)
        assert index.hours_for_job("N25185-0100D", phase=4) < total

    def test_a_job_nobody_charged_is_zero_not_an_error(self, index):
        assert index.hours_for_job("NOT-A-JOB") == 0.0


class TestAgainstTheWorkbooksOwnFigures:
    """Cross-checks against the values Excel last calculated."""

    def test_total_actual_mm_matches_inputs_p86(self, projects):
        total = sum(row["actual_mm"] for row in projects.values())
        assert total == pytest.approx(70.5418918918919, abs=0.01)

    def test_total_earned_mm_matches_inputs_s86(self, projects):
        total = sum(row["earned_mm"] for row in projects.values() if row["earned_mm"])
        assert total == pytest.approx(114.341, abs=0.01)

    @pytest.mark.parametrize("number,progress,actual_mm,earned_mm", [
        ("N25178-0100D", 0.65, 0.0, 1.56),
        ("N25185-0100D", 0.316, 18.516, 8.216),
        ("S24014-0101D", 1.0, 2.442, 21.27),
    ])
    def test_per_project_figures_match(self, projects, number, progress,
                                       actual_mm, earned_mm):
        row = projects[number]
        assert row["progress"] == pytest.approx(progress, abs=0.001)
        assert row["actual_mm"] == pytest.approx(actual_mm, abs=0.01)
        assert row["earned_mm"] == pytest.approx(earned_mm, abs=0.01)

    def test_cpi_matches_inputs_column_u(self, projects):
        assert projects["N25185-0100D"]["cpi"] == pytest.approx(0.4437, abs=0.001)
        assert projects["S24014-0101D"]["cpi"] == pytest.approx(8.7105, abs=0.01)

    def test_the_engineer_split_matches_inputs_columns_i_to_k(self, projects):
        shares = projects["N25185-0100D"]["share_by_engineer"]
        assert shares["Ahmed"] == pytest.approx(0.4158, abs=0.001)
        assert shares["Osama"] == pytest.approx(0.5127, abs=0.001)
        assert shares["Kirolos"] == pytest.approx(0.0715, abs=0.001)


class TestProgress:
    def test_progress_is_credit_weighted_by_phase_weight(self, readonly_wb):
        lookup = readonly_wb.credit_for
        from workload_app.workbook import Deliverable
        items = [
            Deliverable(row=1, type_code="DD", step_no=5, phase_weight=0.25),  # 100%
            Deliverable(row=2, type_code="DD", step_no=1, phase_weight=0.75),  # 10%
        ]
        progress, total, earned = metrics.project_progress(items, lookup, None)
        assert total == pytest.approx(1.0)
        assert earned == pytest.approx(0.25 * 1.0 + 0.75 * 0.1)
        assert progress == pytest.approx(0.325)

    def test_a_project_without_deliverables_falls_back_to_the_manual_figure(self, readonly_wb):
        progress, total, _ = metrics.project_progress([], readonly_wb.credit_for, 0.4)
        assert progress == 0.4
        assert total == 0.0

    def test_shares_fall_back_to_scope_weight_before_anything_is_earned(self, readonly_wb):
        from workload_app.workbook import Deliverable
        items = [
            Deliverable(row=1, type_code="DD", step_no=None, phase_weight=0.75,
                        shares={"Ahmed": 1.0}),
            Deliverable(row=2, type_code="DD", step_no=None, phase_weight=0.25,
                        shares={"Osama": 1.0}),
        ]
        shares = metrics.engineer_shares(
            items, readonly_wb.credit_for, ["Ahmed", "Osama", "Kirolos"])
        assert shares["Ahmed"] == pytest.approx(0.75)
        assert shares["Osama"] == pytest.approx(0.25)


class TestDeliverableRows:
    def test_hours_are_shared_between_deliverables_on_the_same_phase(self, readonly_wb, index):
        rows = {row["row"]: row for row in metrics.deliverable_rows(readonly_wb, index)}
        berths = [r for r in rows.values()
                  if r["project_number"] == "N25185-0100D" and r["ts_phase"] == 4]
        assert len(berths) > 1
        # each sharer gets an equal slice, and the slices add back up
        assert len({round(r["actual_hours"], 3) for r in berths}) == 1
        # Each row is rounded to two places for display, so the slices add back
        # up to the phase total only within half a rounding step per row.
        assert sum(r["actual_hours"] for r in berths) == pytest.approx(
            index.hours_for_job("N25185-0100D", phase=4), abs=0.005 * len(berths))

    def test_a_deliverable_without_a_ts_phase_earns_no_hours(self, readonly_wb, index):
        rows = metrics.deliverable_rows(readonly_wb, index)
        for row in rows:
            if row["ts_phase"] is None:
                assert row["actual_hours"] == 0.0


class TestWorkload:
    def test_hours_are_split_into_the_right_buckets(self, readonly_wb, index):
        workload = metrics.engineer_workload(readonly_wb, index, 2026)
        ahmed = workload["Ahmed"]
        assert ahmed["total_hours"] == pytest.approx(
            ahmed["project_hours"] + ahmed["proposal_hours"]
            + ahmed["absence_hours"] + ahmed["other_hours"], abs=0.01)

    def test_monthly_totals_add_up_to_the_year(self, readonly_wb, index):
        workload = metrics.engineer_workload(readonly_wb, index, 2026)
        for name, engineer in workload.items():
            assert sum(m["total"] for m in engineer["months"]) == pytest.approx(
                engineer["total_hours"], abs=0.01), name

    def test_capacity_follows_the_availability_factor(self, readonly_wb, index):
        workload = metrics.engineer_workload(readonly_wb, index, 2024)
        kirolos = workload["Kirolos"]
        assert kirolos["availability"][2024] == 0.35
        for month in kirolos["months"]:
            assert month["capacity"] == pytest.approx(185.0 * 0.35)

    def test_filtering_by_year_narrows_the_months(self, readonly_wb, index):
        assert all(m["month"].startswith("2026")
                   for m in metrics.engineer_workload(
                       readonly_wb, index, 2026)["Ahmed"]["months"])


class TestOverview:
    def test_it_returns_the_whole_front_page(self, readonly_wb):
        data = metrics.overview(readonly_wb, 2026)
        assert set(data) >= {"portfolio", "engineers", "data_check", "issues"}
        assert data["portfolio"]["projects"] == 40
        assert data["portfolio"]["deliverables"] == 64

    def test_in_hand_covers_only_active_and_not_started(self, readonly_wb):
        data = metrics.overview(readonly_wb, 2026)
        in_scope = [p for p in readonly_wb.projects()
                    if p.status in {"Active", "Not Started"}]
        assert data["portfolio"]["in_scope_projects"] == len(in_scope)

    def test_available_years_come_from_the_timesheet(self, readonly_wb):
        years = metrics.available_years(readonly_wb)
        assert 2026 in years
        assert years == sorted(years)
