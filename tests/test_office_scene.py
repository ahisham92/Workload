"""Who needs help shows the next two weeks as an office: a desk each, paper
piled for the work lined up, the manager's desk bigger (Ahmed, 2026-10-12)."""

from workload_app.app import STATIC_DIR

OFFICE = (STATIC_DIR / "office3d.js").read_text(encoding="utf-8")
SHOWCASE = (STATIC_DIR / "showcase.js").read_text(encoding="utf-8")


def test_the_office_replaces_the_towers():
    assert "import('./office3d.js')" in SHOWCASE
    assert "team3d" not in SHOWCASE and not (STATIC_DIR / "team3d.js").exists()


def test_more_work_is_a_taller_pile_and_the_manager_has_the_big_desk():
    # Ahmed (2026-10-12): a big workload is a tall tower of paper.
    assert "const FULL = 0.55;" in OFFICE and "const MAX_LOAD = 3;" in OFFICE
    assert "Math.min(load || 0, MAX_LOAD)) * FULL" in OFFICE
    assert "const width = big ? 2.3 : 1.6;" in OFFICE
    assert "x.manager" in OFFICE and "manager: Boolean(" in SHOWCASE


def test_a_lighter_week_from_the_timesheets_shows_on_the_desk():
    # The piles are the plan ahead; the flag is the weeks behind, so the two
    # can disagree and the screen says why.
    assert "rest: ((seen.get(p.name) || {}).signal || {}).key === 'rest'" in SHOWCASE
    assert "needs a lighter week" in OFFICE
    assert "even if their pile ahead is small" in SHOWCASE
