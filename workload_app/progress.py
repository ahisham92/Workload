"""How far along a task is, and what a review code does to that number.

A task is measured one of two ways, and which one it is says something real
about the work:

**Pro rata** -- the progress is whatever fraction of the effort has been done.
Fine for work with no gate in it: a study, a calculation, a model to build.

**Workflow** -- the progress is the stage the deliverable has reached, because
that is what a client and a project manager both recognise:

    Design started                10%
    IDC sent                      40%
    Internal comments addressed   60%
    Submitted                     80%

The remaining twenty points are not withheld to be pessimistic.  They are the
review: until the comments come back, a submitted deliverable is not finished
work, it is work waiting to find out.  What comes back decides where it lands:

    Code A   approved                        100%
    Code B   approved with comments           90%, +1% a resubmission, to 99%
    Code C   revise and resubmit              80%, +1% a resubmission, to 89%

The 1% a resubmission is deliberately small.  It is not progress in any real
sense -- nothing new is being designed -- but a deliverable on its fourth
resubmission is not in the same place as one that has just come back, and a
number that never moves hides that.  The cap keeps a resubmission from ever
being worth as much as an approval: 89 and 99 are asymptotes, not milestones.

Revisions are counted rather than averaged away because they are the honest
measure of how much rework a person's submissions cause, which is exactly what
the KPI wants and what hours alone never show.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

#: How a task's progress is arrived at.
MODE_PRO_RATA = "pro_rata"
MODE_WORKFLOW = "workflow"
MODES = [(MODE_PRO_RATA, "Pro rata — by effort done"),
         (MODE_WORKFLOW, "Workflow — by stage reached")]

#: ``(key, label, progress)``, in the order the work goes through them.
STAGES: List[Tuple[str, str, float]] = [
    ("not_started", "Not started", 0.0),
    ("design_started", "Design started", 0.10),
    ("idc_sent", "IDC sent", 0.40),
    ("comments_addressed", "Internal comments addressed", 0.60),
    ("submitted", "Submitted", 0.80),
]
STAGE_KEYS = [key for key, _label, _value in STAGES]
STAGE_VALUE = {key: value for key, _label, value in STAGES}
STAGE_LABEL = {key: label for key, label, _value in STAGES}
SUBMITTED = "submitted"

#: What a review can come back as, and where it puts a submitted deliverable.
#: ``floor`` is the first resubmission's worth; ``cap`` is where +1% stops.
REVIEW_CODES: Dict[str, Dict[str, Any]] = {
    "": {"label": "Awaiting review", "floor": 0.80, "cap": 0.80},
    "A": {"label": "Code A — approved", "floor": 1.00, "cap": 1.00},
    "B": {"label": "Code B — approved with comments", "floor": 0.90, "cap": 0.99},
    "C": {"label": "Code C — revise and resubmit", "floor": 0.80, "cap": 0.89},
}
CODE_KEYS = list(REVIEW_CODES)

#: What one resubmission is worth once a code has come back.
PER_RESUBMISSION = 0.01


class ProgressError(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.errors = [message]


def clean_mode(value: Any) -> str:
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not key:
        return MODE_PRO_RATA
    if key in {"pro_rata", "prorata", "rata"}:
        return MODE_PRO_RATA
    if key in {"workflow", "flow", "stages"}:
        return MODE_WORKFLOW
    raise ProgressError(
        f"{value!r} is not a way of measuring progress. Use 'pro_rata' or "
        f"'workflow'.")


def clean_stage(value: Any) -> str:
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not key:
        return STAGE_KEYS[0]
    if key not in STAGE_VALUE:
        raise ProgressError(
            f"{value!r} is not a stage. Use one of: " + ", ".join(STAGE_KEYS))
    return key


def clean_code(value: Any) -> str:
    key = str(value or "").strip().upper()
    if key not in REVIEW_CODES:
        raise ProgressError(
            f"{value!r} is not a review code. Use A, B or C, or leave it "
            f"empty until the review comes back.")
    return key


def clean_revisions(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        raise ProgressError(f"{value!r} is not a number of revisions.")
    if number < 0:
        raise ProgressError("A number of revisions cannot be negative.")
    if number > 99:
        raise ProgressError("99 revisions is as many as this will count.")
    return number


def of(mode: str, *, stage: str = "", code: str = "", revisions: int = 0,
       pro_rata: Optional[float] = None, done: bool = False) -> float:
    """How far along, as a fraction.

    ``done`` wins over everything: a task somebody has marked finished is
    finished, whatever the stage says, because the person pressing the button
    knows something the stage does not.
    """
    if done:
        return 1.0
    if mode != MODE_WORKFLOW:
        return _bounded(pro_rata)
    base = STAGE_VALUE.get(stage, 0.0)
    if stage != SUBMITTED:
        return base
    rule = REVIEW_CODES.get(str(code or "").upper(), REVIEW_CODES[""])
    return round(min(rule["cap"],
                     rule["floor"] + PER_RESUBMISSION * max(0, revisions)), 4)


def _bounded(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def explain(mode: str, *, stage: str = "", code: str = "",
            revisions: int = 0) -> str:
    """One line saying why the number is what it is."""
    if mode != MODE_WORKFLOW:
        return "Pro rata: the share of the effort that is done."
    if stage != SUBMITTED:
        return f"{STAGE_LABEL.get(stage, stage)}: {STAGE_VALUE.get(stage, 0):.0%}."
    rule = REVIEW_CODES.get(str(code or "").upper(), REVIEW_CODES[""])
    if not code:
        return ("Submitted, and the review has not come back. The last 20% is "
                "the review, not work left to do.")
    if code == "A":
        return "Code A: approved, and finished."
    return (f"{rule['label']}: {rule['floor']:.0%}"
            + (f", plus {revisions}% for {revisions} resubmission(s)"
               if revisions else "")
            + f", capped at {rule['cap']:.0%}.")


# --------------------------------------------------------------------------
# what the rework costs, per person
# --------------------------------------------------------------------------

def rework(tasks: Sequence[Any], engineers: Sequence[str]) -> Dict[str, Any]:
    """Revisions per submission, per person, for the engineer KPIs.

    A submission is a workflow task that has reached Submitted.  A shared task
    counts for each of the people on it: they submitted it together, and a
    resubmission is a cost they carry together.

    A person with no submissions has ``None`` rather than a perfect score --
    the absence of rework is not the same as the absence of submitting, and
    scoring the two alike would reward staying out of the way.
    """
    counts: Dict[str, Dict[str, float]] = {
        name: {"submissions": 0, "revisions": 0, "first_time_right": 0}
        for name in engineers}
    for task in tasks:
        if getattr(task, "progress_mode", MODE_PRO_RATA) != MODE_WORKFLOW:
            continue
        if getattr(task, "stage", "") != SUBMITTED:
            continue
        revisions = int(getattr(task, "revisions", 0) or 0)
        code = str(getattr(task, "review_code", "") or "").upper()
        for name in getattr(task, "assignees", ()) or ():
            entry = counts.setdefault(
                name, {"submissions": 0, "revisions": 0, "first_time_right": 0})
            entry["submissions"] += 1
            entry["revisions"] += revisions
            if revisions == 0 and code in {"A", "B"}:
                entry["first_time_right"] += 1

    out: Dict[str, Any] = {}
    for name, entry in counts.items():
        submissions = entry["submissions"]
        out[name] = {
            "submissions": submissions,
            "revisions": entry["revisions"],
            "revisions_per_submission": (
                round(entry["revisions"] / submissions, 2) if submissions else None),
            "first_time_right": (
                round(entry["first_time_right"] / submissions, 3)
                if submissions else None),
        }
    return out
