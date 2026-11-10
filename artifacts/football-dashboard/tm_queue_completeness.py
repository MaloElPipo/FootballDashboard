"""Weekly completeness of the durable queue: no league, no week, no silent delay.

Pure functions over queue states (no I/O); the caller injects the clock.

* One campaign per ISO week (Europe/Paris). From Monday 05:00 local time, the
  first scheduled tick that finds the week without a campaign creates it. The
  weekly cron slot used to be the only chance, and GitHub drops or delays
  scheduled runs: any later tick of the week now does the same job.
* ``assess`` lists the situations where a league risks missing its weekly
  update; the workflow turns them into a red run that names the leagues.
* ``summary`` is the readable ledger: how many leagues are up to date, and when.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
WEEK_OPENS_HOUR = 5          # Monday 05:00 Paris: the hour the weekly cron aims at
OVERDUE_AFTER = 72 * 3600    # an active campaign this old is late for its week
STALLED_AFTER = 12 * 3600    # a suspended/held campaign left this long undecided
UNSTARTED_AFTER = 24 * 3600  # an opened week this long without any campaign
LISTED = 12                  # leagues named in one alert

STATE_LABELS = {
    "done": "à jour", "publishing": "publication en cours",
    "collected": "collectée, non publiée", "running": "en cours",
    "pending": "en attente", "retry": "à reprendre",
    "suspended": "suspendue", "exhausted": "épuisée",
}
STATUS_LABELS = {"active": "active", "suspended": "suspendue",
                 "complete": "terminée", "closed": "fermée"}


def local(now):
    return datetime.fromtimestamp(now, PARIS)


def week_label(now):
    year, week, _ = local(now).isocalendar()
    return f"{year}-W{week:02d}"


def week_opening(now):
    """Monday 05:00 Paris of the ISO week holding ``now`` (epoch seconds)."""
    t = local(now)
    monday = t - timedelta(days=t.weekday())
    return monday.replace(hour=WEEK_OPENS_HOUR, minute=0, second=0,
                          microsecond=0).timestamp()


def birth(state):
    """Creation time. Campaigns created before ``created_at`` existed fall back
    to their earliest recorded attempt; ``None`` when nothing is known."""
    created = state.get("created_at")
    if created:
        return created
    starts = [i["started"] for i in state["leagues"].values() if i.get("started")]
    return min(starts) if starts else None


def covers(state, codes, week):
    """Whether this campaign is the whole-catalogue campaign of ISO week ``week``.

    A campaign restricted to some leagues (manual test run) never covers a week.
    ``full`` is recorded at creation, so a league added to the catalogue later in
    the week does not make the week look uncovered; older campaigns are judged
    on their league list."""
    born = birth(state)
    if born is None or week_label(born) != week:
        return False
    full = state.get("full")
    if full is None:
        full = set(codes) <= set(state["leagues"])
    return bool(full)


def creation_due(queues, codes, now):
    """May a scheduled tick create the weekly campaign now? The week's window must
    be open and no campaign created this week may cover every league. Closed,
    suspended and complete campaigns all count: the operator, not the clock,
    decides to start another one in the same week."""
    if now < week_opening(now):
        return False
    week = week_label(now)
    return not any(covers(state, codes, week) for _, state in queues)


def last_activity(state):
    times = [birth(state) or 0]
    for item in state["leagues"].values():
        times += [item.get("started") or 0, item.get("verified_at") or 0,
                  item.get("publication_started") or 0]
    return max(times)


def unfinished(state):
    return [(code, item) for code, item in state["leagues"].items()
            if item["state"] != "done"]


def describe(left):
    shown = ", ".join(f"{code} ({STATE_LABELS.get(item['state'], item['state'])})"
                      for code, item in left[:LISTED])
    return shown + (f" … (+{len(left) - LISTED})" if len(left) > LISTED else "")


def duration(seconds):
    days, hours = divmod(int(seconds // 3600), 24)
    return f"{days} j {hours} h" if days else f"{hours} h"


def stamp(epoch):
    return local(epoch).strftime("%d/%m %H:%M") if epoch else "—"


def assess(queues, codes, now):
    """Alerts for situations where a league may miss its weekly update unless
    somebody acts. Empty list = nothing to report."""
    alerts = []
    for _, state in queues:
        name, total = state["campaign"], len(state["leagues"])
        left = unfinished(state)
        born = birth(state)
        if state["status"] == "active" and left and born and now - born >= OVERDUE_AFTER:
            alerts.append(
                f"Campagne {name} ({week_label(born)}) non terminée après "
                f"{duration(now - born)} : {total - len(left)}/{total} ligues à jour. "
                f"À reprendre : {describe(left)}")
        active_at = last_activity(state)
        idle = now - active_at if active_at else None   # None: nothing was ever recorded
        if (state["status"] == "suspended" or state.get("access_hold")) \
                and (idle is None or idle >= STALLED_AFTER):
            since = f"depuis {duration(idle)}" if idle is not None else "depuis une date inconnue"
            rest = (f"{total - len(left)}/{total} ligues à jour. Restent : {describe(left)}"
                    if left else "Toutes les ligues sont à jour, mais les prochaines "
                                 "campagnes restent bloquées.")
            alerts.append(
                f"Campagne {name} bloquée {since} "
                f"(motif : {state.get('reason') or 'inconnu'}) : décision de l'opérateur "
                f"requise. {rest}")
    week, waited = week_label(now), now - week_opening(now)
    if waited >= UNSTARTED_AFTER and not any(covers(s, codes, week) for _, s in queues):
        blockers = [f"{s['campaign']} ({STATUS_LABELS.get(s['status'], s['status'])})"
                    for _, s in queues
                    if s["status"] in ("active", "suspended") or s.get("access_hold")]
        cause = (f" Bloquée par : {', '.join(blockers)}." if blockers else
                 " Aucune campagne ne la bloque : les passages planifiés n'ont pas pu la créer.")
        alerts.append(f"Semaine {week} sans campagne depuis {duration(waited)}.{cause}")
    return alerts


def ledger(state, codes=()):
    """Markdown: leagues up to date out of the total, then one row per league."""
    total, left = len(state["leagues"]), unfinished(state)
    born = birth(state)
    status = STATUS_LABELS.get(state["status"], state["status"])
    lines = [f"### Campagne {state['campaign']} — "
             f"{week_label(born) if born else 'semaine inconnue'}, {status}"]
    head = f"**{total - len(left)}/{total} ligues à jour**"
    if left:
        head += f" — restent : {describe(left)}"
    lines.append(head)
    missing = sorted(set(codes) - set(state["leagues"]))
    if missing:
        lines.append(f"Ligues du catalogue absentes de cette campagne : {', '.join(missing)}.")
    verified = [i["verified_at"] for i in state["leagues"].values() if i.get("verified_at")]
    if born:
        lines.append(f"Créée le {stamp(born)}"
                     + (f" ; dernière publication vérifiée le {stamp(max(verified))}."
                        if verified else "."))
    lines += ["", f"<details><summary>Détail des {total} ligues</summary>", "",
              "| Ligue | État | Collectée | Publication vérifiée | Tentatives | Motif |",
              "|---|---|---|---|---:|---|"]
    for code, item in state["leagues"].items():
        lines.append(f"| {code} | {STATE_LABELS.get(item['state'], item['state'])} | "
                     f"{stamp(item.get('started'))} | {stamp(item.get('verified_at'))} | "
                     f"{item['attempts']} | {item.get('reason', '')} |")
    lines += ["", "</details>"]
    return "\n".join(lines)


def summary(queues, codes, now, alerts):
    week = week_label(now)
    current = next((s for _, s in queues if covers(s, codes, week)), None)
    newest = max((s for _, s in queues), key=lambda s: birth(s) or 0, default=None)
    reference = current or newest
    lines = [f"## Complétude hebdomadaire — semaine {week}"]
    if current:
        lines.append(f"Campagne de la semaine : {current['campaign']}.")
    elif now < week_opening(now):
        lines.append("Pas encore de campagne : la semaine s'ouvre le lundi à 05:00 (Paris).")
    else:
        lines.append("Aucune campagne créée pour cette semaine pour l'instant.")
    if reference:
        lines += ["", ledger(reference, codes)]
    if alerts:
        lines += ["", "### Alertes"] + [f"- {alert}" for alert in alerts]
    return "\n".join(lines) + "\n"
