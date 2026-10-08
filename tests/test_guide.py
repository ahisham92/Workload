"""The How to use guide only sends people to places that exist."""
import re

from workload_app.app import STATIC_DIR

GUIDE = (STATIC_DIR / "guide.js").read_text(encoding="utf-8")
INDEX = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
MEMBER = (STATIC_DIR / "member.html").read_text(encoding="utf-8")
PLANNER = (STATIC_DIR / "planner.js").read_text(encoding="utf-8")


def _manager_part():
    return GUIDE[GUIDE.index("const MANAGER"):GUIDE.index("const MEMBER")]


def _member_part():
    return GUIDE[GUIDE.index("const MEMBER"):GUIDE.index("/* -- small helpers")]


def test_the_tab_and_its_files_are_on_the_page():
    assert 'data-view="guide"' in INDEX
    assert 'id="view-guide"' in INDEX and 'id="guide-body"' in INDEX
    assert 'src="guide.js"' in INDEX and 'href="guide.css"' in INDEX
    assert 'id="member-guide"' in MEMBER and 'src="guide.js"' in MEMBER


def test_every_manager_target_is_a_tab_or_a_planner_view():
    views = set(re.findall(r'data-view="([a-z]+)"', INDEX))
    subviews = set(re.findall(r"\['([a-z]+)', '[^']+'\]",
                              PLANNER[PLANNER.index("const PLANNER_VIEWS"):]
                              [:400]))
    targets = re.findall(r"\['([a-z]+)'(?:, '([a-z]+)')?\]", _manager_part())
    assert len(targets) > 20
    for view, sub in targets:
        assert view in views, view
        if sub:
            assert view == "planner" and sub in subviews, sub


def test_every_member_target_is_a_panel_on_their_page():
    ids = set(re.findall(r'id="([a-z-]+)"', MEMBER))
    targets = re.findall(r"go: '([a-z-]+)'", _member_part())
    assert targets
    for target in targets:
        assert target in ids, target


def test_no_email_intake_or_outlook_step():
    words = GUIDE.lower()
    assert "outlook" not in words
    assert "email" not in words
