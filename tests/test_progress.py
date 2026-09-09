"""Pro rata or workflow, and what a review code does to the number.

The numbers here are the ones the unit works to, so they are written out
rather than derived: 10 / 40 / 60 / 80, then A finishes it, B lands on 90 and
C stays at 80, each rising 1% a resubmission to a cap that a resubmission can
never reach.
"""

import pytest

from workload_app import progress as pr


class TestTheStages:
    @pytest.mark.parametrize("stage,expected", [
        ("not_started", 0.0),
        ("design_started", 0.10),
        ("idc_sent", 0.40),
        ("comments_addressed", 0.60),
        ("submitted", 0.80),
    ])
    def test_each_one_is_worth_what_the_unit_says(self, stage, expected):
        assert pr.of(pr.MODE_WORKFLOW, stage=stage) == expected

    def test_the_last_twenty_points_are_the_review(self):
        """Submitted is not finished: it is waiting to find out."""
        assert pr.of(pr.MODE_WORKFLOW, stage="submitted") == 0.80
        assert "not work left to do" in pr.explain(
            pr.MODE_WORKFLOW, stage="submitted")


class TestTheReviewCodes:
    def test_code_a_finishes_it(self):
        assert pr.of(pr.MODE_WORKFLOW, stage="submitted", code="A") == 1.0

    def test_code_b_lands_on_ninety(self):
        assert pr.of(pr.MODE_WORKFLOW, stage="submitted", code="B") == 0.90

    def test_code_c_stays_at_eighty(self):
        assert pr.of(pr.MODE_WORKFLOW, stage="submitted", code="C") == 0.80

    @pytest.mark.parametrize("revisions,expected", [
        (0, 0.80), (1, 0.81), (5, 0.85), (9, 0.89), (10, 0.89), (40, 0.89)])
    def test_c_rises_a_point_a_resubmission_and_stops_at_89(
            self, revisions, expected):
        assert pr.of(pr.MODE_WORKFLOW, stage="submitted", code="C",
                     revisions=revisions) == expected

    @pytest.mark.parametrize("revisions,expected", [
        (0, 0.90), (1, 0.91), (9, 0.99), (10, 0.99), (40, 0.99)])
    def test_b_does_the_same_from_90_to_99(self, revisions, expected):
        assert pr.of(pr.MODE_WORKFLOW, stage="submitted", code="B",
                     revisions=revisions) == expected

    def test_a_resubmission_never_reaches_an_approval(self):
        """89 and 99 are asymptotes, not milestones."""
        for code, approved in (("C", 0.90), ("B", 1.00)):
            assert pr.of(pr.MODE_WORKFLOW, stage="submitted", code=code,
                         revisions=999) < approved

    def test_a_code_before_submission_is_ignored_by_the_maths(self):
        """The form refuses it; the calculation simply does not use it."""
        assert pr.of(pr.MODE_WORKFLOW, stage="idc_sent", code="B",
                     revisions=5) == 0.40


class TestProRata:
    def test_it_is_whatever_fraction_was_typed(self):
        assert pr.of(pr.MODE_PRO_RATA, pro_rata=0.35) == 0.35

    def test_nothing_typed_is_nothing_done(self):
        assert pr.of(pr.MODE_PRO_RATA) == 0.0

    def test_it_is_held_between_none_and_all(self):
        assert pr.of(pr.MODE_PRO_RATA, pro_rata=1.4) == 1.0
        assert pr.of(pr.MODE_PRO_RATA, pro_rata=-2) == 0.0

    def test_a_stage_does_nothing_to_a_pro_rata_task(self):
        assert pr.of(pr.MODE_PRO_RATA, stage="submitted", pro_rata=0.2) == 0.2


class TestDone:
    def test_marking_it_done_beats_the_stage(self):
        """Whoever pressed the button knows something the stage does not."""
        assert pr.of(pr.MODE_WORKFLOW, stage="idc_sent", done=True) == 1.0
        assert pr.of(pr.MODE_PRO_RATA, pro_rata=0.1, done=True) == 1.0


class TestWhatIsAccepted:
    def test_a_grade_of_progress_that_is_not_one_is_named(self):
        with pytest.raises(pr.ProgressError) as caught:
            pr.clean_mode("guesswork")
        assert "pro_rata" in str(caught.value)

    def test_an_unknown_stage_lists_the_real_ones(self):
        with pytest.raises(pr.ProgressError) as caught:
            pr.clean_stage("nearly there")
        assert "idc_sent" in str(caught.value)

    def test_an_unknown_code(self):
        with pytest.raises(pr.ProgressError):
            pr.clean_code("D")

    def test_negative_revisions(self):
        with pytest.raises(pr.ProgressError):
            pr.clean_revisions(-1)

    def test_spelling_and_spacing_are_forgiven(self):
        assert pr.clean_mode(" Workflow ") == pr.MODE_WORKFLOW
        assert pr.clean_stage("IDC Sent") == "idc_sent"
        assert pr.clean_code(" c ") == "C"


class Task:
    def __init__(self, assignees, stage="submitted", code="", revisions=0,
                 mode=pr.MODE_WORKFLOW):
        self.assignees = assignees
        self.stage = stage
        self.review_code = code
        self.revisions = revisions
        self.progress_mode = mode


class TestRework:
    def test_it_counts_revisions_per_submission(self):
        stats = pr.rework([
            Task(["Ahmed"], code="C", revisions=3),
            Task(["Ahmed"], code="A"),
        ], ["Ahmed", "Osama"])
        assert stats["Ahmed"]["submissions"] == 2
        assert stats["Ahmed"]["revisions"] == 3
        assert stats["Ahmed"]["revisions_per_submission"] == 1.5

    def test_a_shared_submission_counts_for_everybody_on_it(self):
        """They submitted it together; the rework is a cost they both carry."""
        stats = pr.rework([Task(["Ahmed", "Osama"], code="C", revisions=2)],
                          ["Ahmed", "Osama"])
        assert stats["Ahmed"]["revisions"] == 2
        assert stats["Osama"]["revisions"] == 2

    def test_right_first_time_is_an_approval_with_no_resubmission(self):
        stats = pr.rework([
            Task(["Ahmed"], code="A"),
            Task(["Ahmed"], code="B", revisions=2),
            Task(["Ahmed"], code="C"),
        ], ["Ahmed"])
        assert stats["Ahmed"]["first_time_right"] == round(1 / 3, 3)

    def test_nothing_submitted_is_not_a_perfect_score(self):
        """Otherwise staying out of the way outscores doing the work."""
        stats = pr.rework([], ["Ahmed"])
        assert stats["Ahmed"]["submissions"] == 0
        assert stats["Ahmed"]["revisions_per_submission"] is None
        assert stats["Ahmed"]["first_time_right"] is None

    def test_work_not_yet_submitted_is_not_counted(self):
        stats = pr.rework([Task(["Ahmed"], stage="idc_sent")], ["Ahmed"])
        assert stats["Ahmed"]["submissions"] == 0

    def test_a_pro_rata_task_has_no_submissions_to_count(self):
        stats = pr.rework([Task(["Ahmed"], mode=pr.MODE_PRO_RATA)], ["Ahmed"])
        assert stats["Ahmed"]["submissions"] == 0
