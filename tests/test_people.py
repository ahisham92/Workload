"""Teams, grades, and the resourcing question a head of department asks.

The findings are the point of this module, so most of these tests are worked
situations: a team drowning while another idles, a team drowning with nobody
to spare, one person carrying a team, a team that would be overloaded by
lending somebody. Each says what a person would say looking at the numbers.
"""

import datetime as dt

import pytest

from workload_app import people as ppl
from workload_app.timesheet_store import TimesheetStore

CAPACITY = 185.0


@pytest.fixture
def store(tmp_path):
    return TimesheetStore(tmp_path / "unit.timesheets.db")


def staff(store, *rows):
    """(name, team id, grade) — teams are created as they are first named."""
    made = set()
    for name, team, grade in rows:
        if team and team not in made:
            store.add_team(team, team.title(), lead="")
            made.add(team)
        store.save_person(name, team_id=team, grade=grade)


def book(store, person, months, hours, job="20-1"):
    store.append(person, [{"job_number": job, "hours": hours,
                           "date": dt.date(2026, month, 10)} for month in months])


def headlines(result):
    return [f["headline"] for f in result["findings"]]


class TestGrades:
    def test_the_four_a_unit_uses(self):
        assert ppl.GRADE_KEYS == ["senior", "engineer", "junior", "bim"]
        assert ppl.grade_label("bim") == "BIM modeller"

    def test_an_unknown_grade_is_refused_by_name(self):
        with pytest.raises(ppl.PeopleError) as caught:
            ppl.clean_grade("architect")
        assert "senior" in str(caught.value) and "BIM modeller" in str(caught.value)

    def test_nothing_given_means_engineer(self):
        assert ppl.clean_grade("") == ppl.DEFAULT_GRADE
        assert ppl.clean_grade(" Senior ") == "senior"


class TestTheRoster:
    def test_somebody_in_the_timesheets_is_a_person_even_without_a_team(self, store):
        book(store, "Ahmed", [5], 100)
        names = [p["name"] for p in ppl.roster(store)["people"]]
        assert names == ["Ahmed"]
        assert ppl.roster(store)["people"][0]["on_the_establishment"] is False

    def test_and_so_is_somebody_the_workbook_knows(self, store):
        names = [p["name"] for p in
                 ppl.roster(store, known=["Osama"])["people"]]
        assert names == ["Osama"]

    def test_a_person_given_a_team_carries_its_name(self, store):
        staff(store, ("Ahmed", "quay", "senior"))
        person = ppl.roster(store)["people"][0]
        assert person["team_name"] == "Quay" and person["grade_label"] == "Senior"


class TestWhoIsOverAndSince:
    def test_a_team_inside_its_capacity_raises_nothing(self, store):
        staff(store, ("Ahmed", "quay", "engineer"), ("Osama", "quay", "senior"))
        book(store, "Ahmed", [5, 6, 7], 150)
        book(store, "Osama", [5, 6, 7], 150)
        assert headlines(ppl.balance(store, monthly_capacity=CAPACITY)) == []

    def test_it_says_which_month_the_team_went_over(self, store):
        staff(store, ("Ahmed", "quay", "engineer"))
        book(store, "Ahmed", [3, 4], 100)          # inside
        book(store, "Ahmed", [5, 6, 7], 260)       # over, from May
        team = ppl.balance(store, monthly_capacity=CAPACITY)["teams"][0]
        assert team["over_since"] == "2026-05"

    def test_a_month_back_under_capacity_ends_the_run(self, store):
        """'Since when' means the run that is still going, not the first time ever."""
        staff(store, ("Ahmed", "quay", "engineer"))
        book(store, "Ahmed", [1, 2], 260)          # an old spike
        book(store, "Ahmed", [3], 100)             # back under: run broken
        book(store, "Ahmed", [6, 7], 260)          # and over again
        team = ppl.balance(store, monthly_capacity=CAPACITY)["teams"][0]
        assert team["over_since"] == "2026-06"

    def test_only_the_recent_months_decide(self, store):
        """A bad quarter last year is not this quarter's problem."""
        staff(store, ("Ahmed", "quay", "engineer"))
        book(store, "Ahmed", [1, 2, 3], 400)
        book(store, "Ahmed", [6, 7, 8], 120)
        result = ppl.balance(store, monthly_capacity=CAPACITY)
        assert result["teams"][0]["recent_utilisation"] < 1
        assert not [f for f in result["findings"] if f["kind"] == "hire"]


class TestWhatToDoAboutIt:
    def test_it_names_who_to_move_and_where(self, store):
        staff(store, ("Osama", "quay", "senior"), ("Ahmed", "quay", "engineer"),
              ("Mina", "quay", "bim"),
              ("Kirolos", "jetty", "senior"), ("Peter", "jetty", "junior"),
              ("Sara", "jetty", "engineer"), ("Nader", "jetty", "junior"))
        for name in ("Osama", "Ahmed", "Mina"):
            book(store, name, [5, 6, 7], 245)
        for name in ("Kirolos", "Peter", "Sara", "Nader"):
            book(store, name, [5, 6, 7], 60)

        finding = ppl.balance(store, monthly_capacity=CAPACITY)["findings"][0]
        assert finding["kind"] == "move"
        assert finding["team"] == "Quay" and finding["from_team"] == "Jetty"
        assert finding["person"] in {"Peter", "Sara", "Nader"}
        assert "since 2026-05" in finding["detail"]

    def test_on_a_tie_it_moves_the_junior_not_the_senior(self, store):
        """A quiet team is quiet all through, so the tie-break does the choosing."""
        staff(store, ("Ahmed", "quay", "engineer"),
              ("Kirolos", "jetty", "senior"), ("Adel", "jetty", "engineer"),
              ("Peter", "jetty", "junior"), ("Sara", "jetty", "junior"))
        book(store, "Ahmed", [5, 6, 7], 400)
        for name in ("Kirolos", "Adel", "Peter", "Sara"):
            book(store, name, [5, 6, 7], 30)
        finding = ppl.balance(store, monthly_capacity=CAPACITY)["findings"][0]
        assert finding["person"] == "Peter"          # a junior, alphabetically
        assert finding["grade"] == "Junior"

    def test_it_never_moves_the_lead(self, store):
        staff(store, ("Ahmed", "quay", "engineer"),
              ("Kirolos", "jetty", "senior"), ("Peter", "jetty", "junior"),
              ("Sara", "jetty", "junior"))
        store.update_team("jetty", lead="Kirolos")
        book(store, "Ahmed", [5, 6, 7], 400)
        for name in ("Kirolos", "Peter", "Sara"):
            book(store, name, [5, 6, 7], 20)
        finding = ppl.balance(store, monthly_capacity=CAPACITY)["findings"][0]
        assert finding["person"] != "Kirolos"

    def test_a_move_that_would_overload_the_lender_is_a_hire_instead(self, store):
        """Two people at 54% cannot spare one: the one left would be at 108%."""
        staff(store, ("Osama", "quay", "senior"), ("Ahmed", "quay", "engineer"),
              ("Mina", "quay", "bim"),
              ("Kirolos", "jetty", "senior"), ("Peter", "jetty", "junior"))
        for name in ("Osama", "Ahmed", "Mina"):
            book(store, name, [5, 6, 7], 245)
        for name in ("Kirolos", "Peter"):
            book(store, name, [5, 6, 7], 100)

        findings = ppl.balance(store, monthly_capacity=CAPACITY)["findings"]
        hire = next(f for f in findings if f["kind"] == "hire")
        assert hire["team"] == "Quay"
        # and it says why the obvious move is not the answer
        assert "Jetty" in hire["detail"] and "108%" in hire["detail"]

    def test_a_team_a_fraction_over_is_not_a_hire(self, store):
        staff(store, ("Ahmed", "quay", "engineer"), ("Osama", "quay", "senior"))
        book(store, "Ahmed", [5, 6, 7], 200)
        book(store, "Osama", [5, 6, 7], 190)
        assert not [f for f in ppl.balance(store, monthly_capacity=CAPACITY)
                    ["findings"] if f["kind"] == "hire"]

    def test_one_person_carrying_a_team_is_named(self, store):
        staff(store, ("Ahmed", "quay", "engineer"), ("Osama", "quay", "senior"),
              ("Mina", "quay", "bim"))
        book(store, "Ahmed", [5, 6, 7], 300)
        book(store, "Osama", [5, 6, 7], 150)
        book(store, "Mina", [5, 6, 7], 150)
        person = next(f for f in ppl.balance(store, monthly_capacity=CAPACITY)
                      ["findings"] if f["kind"] == "person")
        assert person["person"] == "Ahmed"
        assert "for the team around them" in person["detail"]

    def test_a_whole_team_over_is_said_once_not_once_per_member(self, store):
        """Otherwise three identical lines bury the person who is worse off."""
        staff(store, ("Ahmed", "quay", "engineer"), ("Osama", "quay", "senior"),
              ("Mina", "quay", "bim"))
        for name in ("Ahmed", "Osama", "Mina"):
            book(store, name, [5, 6, 7], 245)
        findings = ppl.balance(store, monthly_capacity=CAPACITY)["findings"]
        assert [f["kind"] for f in findings] == ["hire"]

    def test_a_quiet_team_is_offered_as_having_room(self, store):
        staff(store, ("Kirolos", "jetty", "senior"), ("Peter", "jetty", "junior"),
              ("Sara", "jetty", "junior"))
        for name in ("Kirolos", "Peter", "Sara"):
            book(store, name, [5, 6, 7], 40)
        finding = ppl.balance(store, monthly_capacity=CAPACITY)["findings"][0]
        assert finding["kind"] == "spare" and finding["level"] == "ok"


class TestProjectsAcrossTeams:
    def test_it_says_which_teams_carry_a_project(self, store):
        staff(store, ("Ahmed", "quay", "engineer"), ("Kirolos", "jetty", "senior"))
        book(store, "Ahmed", [5], 75, job="20-1")
        book(store, "Kirolos", [5], 25, job="20-1")
        project = ppl.balance(store, monthly_capacity=CAPACITY)["projects"][0]
        assert project["job_number"] == "20-1"
        assert [t["name"] for t in project["teams"]] == ["Quay", "Jetty"]
        assert [t["percent"] for t in project["teams"]] == [75, 25]

    def test_the_percentages_add_up(self, store):
        """68% and 33% side by side reads as a mistake, so they are made to sum."""
        staff(store, ("Ahmed", "quay", "engineer"), ("Kirolos", "jetty", "senior"))
        book(store, "Ahmed", [5], 67.5, job="20-1")
        book(store, "Kirolos", [5], 32.5, job="20-1")
        project = ppl.balance(store, monthly_capacity=CAPACITY)["projects"][0]
        assert sum(t["percent"] for t in project["teams"]) == 100


class TestCapacity:
    def test_a_person_can_have_their_own(self, store):
        staff(store, ("Ahmed", "quay", "engineer"))
        store.save_person("Ahmed", capacity_hours=92.5)      # half time
        book(store, "Ahmed", [5, 6, 7], 100)
        member = ppl.balance(store, monthly_capacity=CAPACITY)["members"][0]
        assert member["monthly_capacity"] == 92.5
        assert member["recent_utilisation"] > 1

    def test_somebody_inactive_is_not_counted_in_their_team(self, store):
        staff(store, ("Ahmed", "quay", "engineer"), ("Osama", "quay", "senior"))
        store.save_person("Osama", active=0)
        book(store, "Ahmed", [5, 6, 7], 100)
        team = ppl.balance(store, monthly_capacity=CAPACITY)["teams"][0]
        assert team["headcount"] == 1 and team["monthly_capacity"] == CAPACITY


class TestSmallTeams:
    """A team of one is where "a fraction of a person short" misleads."""

    def test_one_person_well_over_is_not_dismissed_as_a_fraction(self, store):
        staff(store, ("Ahmed", "quay", "senior"))
        store.save_person("Ahmed", capacity_hours=90)        # half time
        book(store, "Ahmed", [6, 7, 8], 134)                 # ~149%
        result = ppl.balance(store, monthly_capacity=CAPACITY)
        assert result["teams"][0]["recent_utilisation"] > 1.4
        assert [f["kind"] for f in result["findings"]] == ["hire"]

    def test_but_a_few_percent_over_still_is(self, store):
        staff(store, ("Ahmed", "quay", "senior"))
        book(store, "Ahmed", [6, 7, 8], 190)                 # 103%
        assert ppl.balance(store, monthly_capacity=CAPACITY)["findings"] == []
