"""Offline only: weekly completeness guard (one campaign per ISO week, loud delays)."""
import copy
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tm_collection_queue as q
import tm_queue_completeness as c
from scripts import collection_queue as runner

try:
    import yaml
except ImportError:                      # optional: the text checks below still run
    yaml = None

HOUR = 3600
CODES = ["fr1", "l1", "es1"]
CATALOGUE = [{"code_tm": code.upper(), "slug": code} for code in CODES]


def paris(day, hour=0, minute=0, month=11, year=2026):
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Europe/Paris")).timestamp()


MON = paris(9, 5, 30)            # Monday 9 Nov 2026, week 2026-W46, window open
LAST_MON = paris(2, 5, 30)       # week 2026-W45


def campaign(name="run-1", born=MON, status="active", full=True, leagues=CODES):
    state = q.new_campaign(name, list(leagues), now=born, full=full)
    state["status"] = status
    return state


def finish(state, codes=None, when=MON + HOUR):
    for code in codes or list(state["leagues"]):
        state["leagues"][code].update(state="done", attempts=1, reason="success",
                                      started=when - 600, publication_started=when - 300,
                                      verified_at=when)
    return state


def queues(*states):
    return [(index + 1, state) for index, state in enumerate(states)]


class WeekMathTests(unittest.TestCase):
    def test_weeks_are_paris_iso_weeks_and_open_monday_at_five(self):
        self.assertEqual(c.week_label(paris(8, 23, 30)), "2026-W45")        # Sunday night
        self.assertEqual(c.week_label(paris(9, 0, 30)), "2026-W46")         # Monday 00:30 Paris
        self.assertEqual(c.week_label(paris(31, 12, month=12)), "2026-W53")
        self.assertEqual(c.week_label(paris(4, 12, month=1, year=2027)), "2027-W01")
        for now in (paris(9, 5), paris(11, 12), paris(15, 23, 59)):
            self.assertEqual(c.week_opening(now), paris(9, 5))

    def test_the_window_opens_at_five_paris_in_winter_and_in_summer(self):
        # Mondays: 9 Nov 2026 (UTC+1) and 6 Jul 2026 (UTC+2).
        for before, opening in ((paris(9, 4, 59), paris(9, 5)),
                                (paris(6, 4, 59, month=7), paris(6, 5, month=7))):
            self.assertLess(before, c.week_opening(before))
            self.assertEqual(c.week_opening(opening), opening)
        self.assertEqual(c.local(paris(9, 5)).utcoffset().total_seconds(), 3600)
        self.assertEqual(c.local(paris(6, 5, month=7)).utcoffset().total_seconds(), 7200)


class CreationRuleTests(unittest.TestCase):
    def due(self, states, now):
        return c.creation_due(queues(*states), CODES, now)

    def test_a_week_without_campaign_gets_one_at_the_first_tick_after_opening(self):
        self.assertFalse(self.due([], paris(9, 4, 59)))         # Monday before 05:00
        self.assertTrue(self.due([], paris(9, 5)))
        self.assertTrue(self.due([], paris(12, 14)))            # the slot was missed: Thursday

    def test_any_campaign_of_the_week_blocks_a_second_one(self):
        for status in ("active", "suspended", "complete", "closed"):
            with self.subTest(status=status):
                self.assertFalse(self.due([campaign(status=status)], paris(13, 10)))

    def test_previous_week_or_partial_campaigns_do_not_count(self):
        self.assertTrue(self.due([finish(campaign(born=LAST_MON, status="complete"))], MON))
        self.assertTrue(self.due([campaign(full=False, leagues=["fr1"])], MON + 6 * HOUR))

    def test_a_league_added_to_the_catalogue_later_never_duplicates_the_week(self):
        existing = finish(campaign(), codes=None)
        self.assertTrue(c.covers(existing, CODES + ["new1"], "2026-W46"))
        self.assertFalse(c.creation_due(queues(existing), CODES + ["new1"], paris(10, 9)))

    def test_legacy_campaigns_are_judged_on_attempts_and_league_list(self):
        legacy = q.new_campaign("run-old", CODES)                 # no created_at / full
        self.assertFalse(c.covers(legacy, CODES, "2026-W46"))     # nothing known: no claim
        legacy["leagues"]["fr1"]["started"] = LAST_MON
        self.assertEqual(c.birth(legacy), LAST_MON)
        self.assertFalse(c.covers(legacy, CODES, "2026-W46"))
        self.assertTrue(c.covers(legacy, CODES, "2026-W45"))
        legacy["leagues"]["fr1"]["started"] = MON
        self.assertTrue(c.covers(legacy, CODES, "2026-W46"))
        self.assertFalse(c.covers(legacy, CODES + ["new1"], "2026-W46"))   # subset by league list


class AlertTests(unittest.TestCase):
    def alerts(self, states, now, codes=CODES):
        return c.assess(queues(*states), codes, now)

    def test_a_campaign_is_quiet_for_72_hours_then_names_the_missing_leagues(self):
        state = campaign()
        finish(state, ["fr1"])
        state["leagues"]["l1"].update(state="retry")
        self.assertEqual(self.alerts([state], MON + 71 * HOUR), [])
        (alert,) = self.alerts([state], MON + 72 * HOUR)
        self.assertIn("run-1 (2026-W46) non terminée après 3 j 0 h", alert)
        self.assertIn("1/3 ligues à jour", alert)
        self.assertIn("l1 (à reprendre)", alert)
        self.assertIn("es1 (en attente)", alert)
        self.assertNotIn("fr1 (", alert)

    def test_a_long_list_is_cut_but_counted(self):
        codes = [f"l{i:02d}" for i in range(20)]
        state = campaign(leagues=codes)
        (alert,) = self.alerts([state], MON + 80 * HOUR, codes)
        self.assertIn("l00 (en attente)", alert)
        self.assertIn(f"… (+{20 - c.LISTED})", alert)
        self.assertNotIn("l19", alert)

    def test_a_suspended_campaign_is_a_reminder_after_12_hours_not_72(self):
        state = campaign(status="suspended")
        state["reason"] = "checkpoint_storage"
        state["leagues"]["fr1"].update(state="suspended", started=MON + HOUR)
        self.assertEqual(self.alerts([state], MON + 12 * HOUR), [])        # 11 h idle
        (alert,) = self.alerts([state], MON + 13 * HOUR)                  # 12 h idle
        self.assertIn("bloquée depuis 12 h", alert)
        self.assertIn("checkpoint_storage", alert)
        self.assertIn("0/3 ligues à jour", alert)

    def test_a_suspension_without_any_recorded_time_is_never_silent(self):
        state = q.new_campaign("run-old", CODES)
        q.suspend(state, "access_blocked")
        (alert,) = self.alerts([state], MON)
        self.assertIn("depuis une date inconnue", alert)

    def test_a_held_complete_campaign_still_blocks_next_weeks(self):
        state = finish(campaign(status="complete"))
        state["access_hold"] = True
        self.assertEqual(self.alerts([state], MON + 2 * HOUR), [])
        (alert,) = self.alerts([state], MON + 14 * HOUR)
        self.assertIn("Toutes les ligues sont à jour", alert)
        self.assertIn("restent bloquées", alert)

    def test_nothing_left_to_do_is_never_reported_as_late(self):
        state = finish(campaign())                     # every league done, status not yet updated
        self.assertEqual(self.alerts([state], MON + 100 * HOUR), [])

    def test_finished_and_closed_campaigns_raise_nothing(self):
        done = finish(campaign(status="complete"))
        closed = campaign(name="run-2", status="closed")
        for now in (MON + 90 * HOUR, MON + 140 * HOUR):                # still week 46
            self.assertEqual(self.alerts([done], now), [])
            self.assertEqual(self.alerts([closed], now), [])

    def test_an_opened_week_without_campaign_alerts_after_24_hours(self):
        self.assertEqual(self.alerts([], paris(9, 4)), [])                 # not open yet
        self.assertEqual(self.alerts([], paris(10, 4)), [])                # 23 h after opening
        (alert,) = self.alerts([], paris(10, 5))
        self.assertIn("Semaine 2026-W46 sans campagne depuis 1 j 0 h", alert)
        self.assertIn("Aucune campagne ne la bloque", alert)

    def test_the_blocking_campaign_is_named_next_to_the_missing_week(self):
        previous = campaign(name="run-prev", born=LAST_MON)
        finish(previous, ["fr1"], when=LAST_MON + HOUR)
        overdue, week = self.alerts([previous], paris(10, 6))
        self.assertIn("run-prev (2026-W45) non terminée après 8 j 0 h", overdue)
        self.assertIn("Semaine 2026-W46 sans campagne", week)
        self.assertIn("Bloquée par : run-prev (active)", week)

    def test_a_campaign_created_in_the_week_silences_the_missing_week_alert(self):
        for status in ("active", "complete", "closed"):
            with self.subTest(status=status):
                state = campaign(status=status)
                self.assertEqual(self.alerts([state], MON + 30 * HOUR), [])


class LedgerTests(unittest.TestCase):
    def test_complete_campaign_reads_78_of_78_style_with_paris_dates(self):
        state = finish(campaign(status="complete"), when=paris(9, 19, 22))
        text = c.summary(queues(state), CODES, paris(10, 9), [])
        self.assertIn("Campagne de la semaine : run-1.", text)
        self.assertIn("### Campagne run-1 — 2026-W46, terminée", text)
        self.assertIn("**3/3 ligues à jour**", text)
        self.assertIn("dernière publication vérifiée le 09/11 19:22", text)
        self.assertIn("| fr1 | à jour | 09/11 19:12 | 09/11 19:22 | 1 | success |", text)
        self.assertNotIn("Alertes", text)

    def test_unfinished_campaign_lists_what_remains_and_the_alerts(self):
        state = finish(campaign(), ["fr1"])
        alerts = ["exemple d'alerte"]
        text = c.summary(queues(state), CODES, MON + 80 * HOUR, alerts)
        self.assertIn("**1/3 ligues à jour** — restent : l1 (en attente), es1 (en attente)", text)
        self.assertIn("### Alertes\n- exemple d'alerte", text)

    def test_catalogue_leagues_missing_from_the_campaign_are_reported(self):
        state = finish(campaign(leagues=["fr1", "l1"]))
        text = c.ledger(state, CODES)
        self.assertIn("Ligues du catalogue absentes de cette campagne : es1.", text)

    def test_no_campaign_yet_and_legacy_campaign_do_not_crash(self):
        self.assertIn("la semaine s'ouvre le lundi à 05:00", c.summary([], CODES, paris(9, 3), []))
        self.assertIn("Aucune campagne créée pour cette semaine",
                      c.summary([], CODES, paris(10, 9), []))
        legacy = q.new_campaign("run-old", CODES)
        self.assertIn("semaine inconnue", c.summary(queues(legacy), CODES, MON, []))


class PrepareCreationTests(unittest.TestCase):
    """The scheduled tick creates the week's campaign; nothing else may."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for target in (patch.object(runner, "require_access_clearance"),
                       patch.object(runner, "select_leagues", return_value=CATALOGUE)):
            target.start()
            self.addCleanup(target.stop)
        self.store = FakeStore()

    def test_scheduled_tick_creates_the_missing_week_even_days_after_the_slot(self):
        self.store.states = [finish(campaign(born=LAST_MON, status="complete"))]
        release_id, state = runner.prepare(self.store, "77", create=True, scheduled=True,
                                           now=paris(12, 14))
        self.assertEqual(state["campaign"], "run-77")
        self.assertEqual(state["created_at"], int(paris(12, 14)))
        self.assertTrue(state["full"])
        self.assertEqual(state["owner"], "77")
        self.assertEqual(len(self.store.created), 1)

    def test_the_next_tick_resumes_that_campaign_instead_of_creating_another(self):
        self.store.states = [finish(campaign(born=LAST_MON, status="complete"))]
        runner.prepare(self.store, "77", create=True, scheduled=True, now=paris(9, 5, 40))
        release_id, state = runner.prepare(self.store, "78", create=True, scheduled=True,
                                           now=paris(9, 6, 40))
        self.assertEqual(state["campaign"], "run-77")
        self.assertEqual(state["owner"], "78")
        self.assertEqual(len(self.store.created), 1)

    def test_a_week_that_already_has_its_campaign_creates_nothing(self):
        self.store.states = [finish(campaign(status="complete"))]
        for now in (paris(9, 6), paris(11, 3), paris(15, 22)):
            self.assertIsNone(runner.prepare(self.store, "77", create=True, scheduled=True,
                                             now=now))
        self.assertEqual(self.store.created, [])

    def test_monday_before_five_creates_nothing(self):
        self.store.states = [finish(campaign(born=LAST_MON, status="complete"))]
        self.assertIsNone(runner.prepare(self.store, "77", create=True, scheduled=True,
                                         now=paris(9, 4, 59)))
        self.assertEqual(self.store.created, [])

    def test_a_scheduled_tick_without_creation_permission_never_creates(self):
        self.assertIsNone(runner.prepare(self.store, "77", create=False, scheduled=True,
                                         now=MON))
        self.assertEqual(self.store.created, [])

    def test_a_manual_run_still_creates_on_request_and_marks_subsets(self):
        self.store.states = [finish(campaign(status="complete"))]       # week already covered
        _, state = runner.prepare(self.store, "88", create=True, now=MON + HOUR)
        self.assertEqual(state["campaign"], "run-88")
        self.assertTrue(state["full"])
        self.store.states = []
        with patch.object(runner, "select_leagues", return_value=CATALOGUE[:1]):
            _, subset = runner.prepare(self.store, "89", selection="FR1", create=True,
                                       now=MON + HOUR)
        self.assertFalse(subset["full"])
        self.assertEqual(list(subset["leagues"]), ["fr1"])

    def test_a_test_campaign_on_one_league_does_not_hide_the_weekly_one(self):
        self.store.states = [campaign(full=False, leagues=["fr1"], status="complete")]
        _, state = runner.prepare(self.store, "90", create=True, scheduled=True,
                                  now=MON + 2 * HOUR)
        self.assertEqual(state["campaign"], "run-90")
        self.assertEqual(sorted(state["leagues"]), sorted(CODES))

    def test_a_suspended_campaign_still_blocks_creation(self):
        suspended = campaign(born=LAST_MON)
        q.suspend(suspended, "access_blocked")
        self.store.states = [suspended]
        with self.assertRaises(runner.CampaignSuspended):
            runner.prepare(self.store, "77", create=True, scheduled=True, now=MON)
        self.assertEqual(self.store.created, [])

    def test_workflow_environment_drives_scheduled_creation(self):
        self.store.states = [finish(campaign(born=LAST_MON, status="complete"))]
        summary, output = Path(self.temp.name) / "summary", Path(self.temp.name) / "output"
        env = {"GITHUB_RUN_ID": "91", "GITHUB_EVENT_NAME": "schedule", "ALLOW_CREATE": "true",
               "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_OUTPUT": str(output)}
        with patch.dict(os.environ, env), \
             patch.object(sys, "argv", ["collection_queue.py", "prepare"]), \
             patch.object(runner, "GitHubStore", return_value=self.store), \
             patch.object(runner.time, "time", return_value=paris(10, 9)):
            runner.main()
        self.assertEqual(output.read_text(), "ready=true\ncampaign=run-91\n")
        self.assertEqual(len(self.store.created), 1)


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.summary = Path(self.temp.name) / "summary"

    def test_healthy_week_writes_the_ledger_and_returns_no_alert(self):
        self.store.states = [finish(campaign(status="complete"))]
        with patch("builtins.print") as printed:
            alerts = runner.watch(self.store, str(self.summary), now=MON + 10 * HOUR,
                                  codes=CODES)
        self.assertEqual(alerts, [])
        self.assertIn("**3/3 ligues à jour**", self.summary.read_text())
        printed.assert_not_called()

    def test_late_campaign_is_annotated_as_an_error_with_its_leagues(self):
        self.store.states = [campaign()]
        with patch("builtins.print") as printed:
            alerts = runner.watch(self.store, str(self.summary), now=MON + 80 * HOUR,
                                  codes=CODES)
        self.assertEqual(len(alerts), 1)
        message = printed.call_args.args[0]
        self.assertTrue(message.startswith("::error title=Complétude hebdomadaire::Campagne run-1"))
        self.assertIn("0/3 ligues à jour", message)
        self.assertIn("### Alertes", self.summary.read_text())

    def test_the_command_fails_the_run_only_when_there_is_an_alert(self):
        env = {"GITHUB_RUN_ID": "5", "GITHUB_STEP_SUMMARY": str(self.summary)}
        for states, now, expect_failure in (
                ([finish(campaign(status="complete"))], MON + 10 * HOUR, False),
                ([campaign()], MON + 80 * HOUR, True)):
            self.store.states = states
            with patch.dict(os.environ, env), \
                 patch.object(sys, "argv", ["collection_queue.py", "watch"]), \
                 patch.object(runner, "GitHubStore", return_value=self.store), \
                 patch.object(runner, "select_leagues", return_value=CATALOGUE), \
                 patch.object(runner.time, "time", return_value=now), \
                 patch("builtins.print"):
                if expect_failure:
                    with self.assertRaisesRegex(RuntimeError, "completeness"):
                        runner.main()
                else:
                    runner.main()

    def test_watch_never_writes_the_queue(self):
        self.store.states = [campaign()]
        before = copy.deepcopy(self.store.states)
        with patch("builtins.print"):
            runner.watch(self.store, None, now=MON + 80 * HOUR, codes=CODES)
        self.assertEqual(self.store.states, before)
        self.assertEqual((self.store.created, self.store.saved), ([], 0))


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[3]
        self.text = (root / ".github/workflows/scrape-weekly.yml").read_text()

    def test_the_watch_step_is_last_and_runs_even_after_a_failure(self):
        step = self.text.rsplit("      - name:", 1)[1]
        self.assertIn("collection_queue.py watch", step)
        self.assertIn("always()", step)
        self.assertIn("inputs.skip_scrape != 'true'", step)

    def test_creation_no_longer_depends_on_a_single_cron_slot(self):
        self.assertNotIn("steps.gate", self.text)
        self.assertNotIn("id: gate", self.text)
        self.assertIn('ALLOW_CREATE: "true"', self.text)

    def test_step_names_stay_valid_plain_yaml(self):
        # A ": " inside an unquoted name turns it into a mapping and breaks the whole
        # workflow ("mapping values are not allowed here"), which no other test notices.
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- name:"):
                name = stripped[len("- name:"):].strip()
                if not name.startswith(("'", '"')):
                    self.assertNotIn(": ", name, line)
                    self.assertNotIn(" #", name, line)

    @unittest.skipIf(yaml is None, "PyYAML not installed")
    def test_workflow_parses_and_keeps_its_steps_in_order(self):
        steps = yaml.safe_load(self.text)["jobs"]["scrape-and-publish"]["steps"]
        names = [step.get("id") or step.get("name") for step in steps]
        self.assertEqual(names[-1], "Contrôler la complétude hebdomadaire")
        self.assertLess(names.index("queue"), names.index("collect"))
        self.assertNotIn("gate", names)


class FakeStore:
    """In-memory queue store: no GitHub, creation and saves are recorded."""

    def __init__(self):
        self.states = []
        self.created = []
        self.saved = 0

    def inventory(self):
        return [(index + 1, copy.deepcopy(state)) for index, state in enumerate(self.states)]

    def create(self, state):
        self.states.append(copy.deepcopy(state))
        self.created.append(copy.deepcopy(state))
        return len(self.states)

    def save(self, release_id, state):
        self.saved += 1
        self.states[release_id - 1] = copy.deepcopy(state)

    def run(self, run_id):
        return {"id": int(run_id), "status": "completed", "conclusion": "success"}


class CampaignFieldsTests(unittest.TestCase):
    def test_created_at_and_full_are_recorded_only_when_given(self):
        plain = q.new_campaign("c1", ["fr1"])
        self.assertNotIn("created_at", plain)
        self.assertNotIn("full", plain)
        stamped = q.new_campaign("c2", ["fr1"], now=MON + 0.7, full=True)
        self.assertEqual((stamped["created_at"], stamped["full"]), (int(MON), True))
        q.validate(stamped)


if __name__ == "__main__":
    unittest.main()
