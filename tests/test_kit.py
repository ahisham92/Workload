"""The control kit (static/kit.css, kit.js) and what it adds to pick.js and tables.js."""
import re

from workload_app.app import STATIC_DIR

INDEX = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
MEMBER = (STATIC_DIR / "member.html").read_text(encoding="utf-8")
KIT_CSS = (STATIC_DIR / "kit.css").read_text(encoding="utf-8")
KIT_JS = (STATIC_DIR / "kit.js").read_text(encoding="utf-8")
PICK = (STATIC_DIR / "pick.js").read_text(encoding="utf-8")
TABLES = (STATIC_DIR / "tables.js").read_text(encoding="utf-8")


def _order(html, pattern):
    return re.findall(pattern, html)


class TestLoadOrder:
    def test_kit_styles_load_just_before_polish(self):
        links = _order(INDEX, r'<link rel="stylesheet" href="([^"]+)"')
        assert links.index("video.css") < links.index("kit.css") < links.index("polish.css")
        assert links[-1] == "polish.css"

    def test_kit_script_loads_after_pocket_and_before_the_picker(self):
        scripts = _order(INDEX, r'<script src="([^"]+)"></script>')
        assert scripts.index("pocket.js") < scripts.index("kit.js") < scripts.index("pick.js")
        assert scripts[-1] == "pick.js"

    def test_the_engineers_page_has_the_kit_too(self):
        assert 'href="kit.css"' in MEMBER and 'src="kit.js"' in MEMBER


class TestColours:
    def test_dark_mode_is_defined_both_ways(self):
        assert "@media (prefers-color-scheme: dark)" in KIT_CSS
        assert ':root:not([data-theme="light"])' in KIT_CSS
        assert ':root[data-theme="dark"]' in KIT_CSS

    def test_status_is_a_word_and_an_icon_not_colour_alone(self):
        assert "WORD = { ok: 'Done', warn: 'Note', bad: 'Problem'" in KIT_JS
        assert "infobar-word" in KIT_JS and "infobar-ico" in KIT_JS


class TestNumberBoxes:
    def test_a_half_typed_sum_is_never_sent(self):
        assert "e.stopImmediatePropagation()" in KIT_JS
        assert "document.addEventListener('change'" in KIT_JS

    def test_spreadsheet_cells_keep_their_own(self):
        assert "table.gsheet" in KIT_JS


class TestDropDownSearch:
    def test_long_lists_open_with_a_search_and_recents(self):
        assert "const SEARCH_FROM = 8;" in PICK
        assert "heading('Recent')" in PICK
        assert "localStorage" in PICK


class TestTableFilters:
    def test_long_tables_get_a_filter_on_each_heading(self):
        assert "const FILTER_FROM = 8;" in TABLES
        assert "Showing ${showing} of ${rows.length} rows." in TABLES
        assert "edit-table" in TABLES

    def test_the_filter_does_not_sort_the_column(self):
        assert "e.stopPropagation(); openFilter(" in TABLES
