"""Fewer tabs, each opening on the answer to its question (static/focus.js)."""
import re

from workload_app.app import STATIC_DIR

INDEX = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
FOCUS = (STATIC_DIR / "focus.js").read_text(encoding="utf-8")
PATHS = (STATIC_DIR / "paths.js").read_text(encoding="utf-8")
LOOK = (STATIC_DIR / "look.js").read_text(encoding="utf-8")
POCKET = (STATIC_DIR / "pocket.js").read_text(encoding="utf-8")
GUIDE = (STATIC_DIR / "guide.js").read_text(encoding="utf-8")


def _block(text, start):
    part = text[text.index(start):]
    return part[:part.index("};") if "{" in start else part.index("];")]


def _groups():
    part = _block(FOCUS, "const GROUPS = [")
    return [re.findall(r"'([a-z]+)'", g) for g in re.findall(r"\[([^\[\]]+)\]", part)]


VIEWS = set(re.findall(r'data-view="([a-z]+)"', INDEX))


def test_the_files_are_on_the_page_after_the_look():
    assert INDEX.index('src="look.js"') < INDEX.index('src="focus.js"') < INDEX.index('src="pocket.js"')
    assert INDEX.index('href="look.css"') < INDEX.index('href="focus.css"')


def test_every_page_in_a_group_is_a_tab_and_in_one_group_only():
    groups = _groups()
    assert len(groups) == 6
    pages = [v for g in groups for v in g]
    assert len(pages) == len(set(pages))
    assert set(pages) <= VIEWS


def test_the_groups_match_the_pages_the_paths_keep():
    shared = _block(PATHS, "const SHARED = {")
    for group in _groups():
        head, *rest = group
        found = re.search(rf"{head}: \[([^\]]*)\]", shared)
        assert found, head
        assert re.findall(r"'([a-z]+)'", found.group(1)) == rest


def test_the_bar_holds_eight_tabs_plus_help_and_admin():
    sharing = {v for g in _groups() for v in g[1:]}
    assert len(VIEWS - sharing - {"guide", "admin"}) == 8


def test_every_tab_asks_a_question_and_answers_it():
    questions = _block(FOCUS, "const QUESTION = {")
    asked = set(re.findall(r"^\s+([a-z]+): '", questions, re.M))
    assert VIEWS - {"admin"} <= asked
    answers = FOCUS[FOCUS.index("const ANSWER = {"):FOCUS.index("/* -- the answer card")]
    answered = set(re.findall(r"^    ([a-z]+)\(\) \{", answers, re.M))
    assert VIEWS - {"admin", "guide"} <= answered
    for question in re.findall(r": '([^']+)'", questions):
        assert question.endswith("?"), question


def test_every_tab_takes_its_paths_colour():
    tone = _block(LOOK, "const TONE = {")
    for view in VIEWS:
        assert re.search(rf"\b{view}: '", tone), view


def test_a_page_sharing_a_tab_is_not_on_the_phone_bar_twice():
    assert "in-group" in POCKET


def test_nothing_is_removed_only_folded():
    # Show more hides with a class; nothing is taken off the page.
    assert ".remove()" not in FOCUS.replace("more.remove()", "").replace("extra.remove()", "")
    assert "fold-extra" in FOCUS


def test_the_guide_says_where_shared_pages_now_live():
    for words in ("Projects › Budgets", "Reports › Growth", "Bring in data › Timesheets",
                  "Planner › Tasks", "Team › Reference", "Show more"):
        assert words in GUIDE, words
    assert "four paths" not in GUIDE
