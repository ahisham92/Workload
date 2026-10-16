"""The finishing pass on the look (static/polish.css and static/pick.js)."""
import re

from workload_app.app import STATIC_DIR

INDEX = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
POLISH = (STATIC_DIR / "polish.css").read_text(encoding="utf-8")
PICK = (STATIC_DIR / "pick.js").read_text(encoding="utf-8")
SCRIPTS = {p.name: p.read_text(encoding="utf-8") for p in STATIC_DIR.glob("*.js")}

# Pictures drawn as characters, which each phone draws its own way.
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-⛿⭐▶]")


def _code(text):
    """The lines of a script that are not comments."""
    return [line for line in text.splitlines()
            if not line.strip().startswith(("//", "*", "/*"))]


class TestFiles:
    def test_polish_is_the_last_stylesheet(self):
        links = re.findall(r'<link rel="stylesheet" href="([^"]+)"', INDEX)
        assert links[-1] == "polish.css"
        assert links.index("video.css") < links.index("polish.css")

    def test_the_picker_loads_after_every_other_script(self):
        scripts = re.findall(r'<script src="([^"]+)"></script>', INDEX)
        assert scripts[-1] == "pick.js"
        assert scripts.index("pocket.js") < scripts.index("pick.js")


class TestPicker:
    def test_the_real_drop_down_stays_the_source_of_truth(self):
        # Choosing sets the <select> and tells the page, as a tap on it would.
        assert "dispatchEvent(new Event('change', { bubbles: true }))" in PICK
        # A value set in code shows on the button too.
        assert "watchSetter(HTMLSelectElement.prototype, 'value'" in PICK
        assert "watchSetter(HTMLSelectElement.prototype, 'selectedIndex'" in PICK

    def test_spreadsheet_cells_keep_their_own(self):
        assert "table.gsheet" in PICK

    def test_it_is_a_listbox_people_can_use_by_keyboard(self):
        for word in ("'listbox'", "'option'", "aria-expanded", "aria-activedescendant",
                     "'ArrowDown'", "'ArrowUp'", "'Escape'", "'Home'", "'End'"):
            assert word in PICK

    def test_the_hidden_drop_down_is_out_of_reach_not_gone(self):
        rule = re.search(r"select\.pick-native \{([^}]*)\}", POLISH).group(1)
        assert "opacity: 0" in rule and "pointer-events: none" in rule
        assert "display: none" not in rule


class TestLook:
    def test_no_coloured_edge_on_one_side(self):
        # Polish draws every state box with a line all round, never one side.
        assert not re.search(r"border-(left|right|top|bottom)\s*:\s*[2-9]px", POLISH)
        assert "border: 1px solid color-mix(in srgb, var(--edge) 42%, var(--border)) !important" in POLISH

    def test_focus_hover_and_press_are_drawn(self):
        assert ":focus-visible" in POLISH and ":active" in POLISH and ":hover" in POLISH

    def test_less_motion_when_asked(self):
        assert "@media (prefers-reduced-motion: reduce)" in POLISH

    def test_no_emoji_on_screen(self):
        for name, text in SCRIPTS.items():
            for line in _code(text):
                assert not EMOJI.search(line), f"{name}: {line.strip()}"
        body = re.sub(r"<!--.*?-->", "", INDEX, flags=re.S)
        assert not EMOJI.search(body)
