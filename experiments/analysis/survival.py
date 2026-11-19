"""Kaplan--Meier and restricted-mean survival summaries."""

from __future__ import annotations

if __package__:
    from . import core as _core
else:  # direct script execution
    import core as _core  # type: ignore[no-redef]

ARM_ORDER = _core.ARM_ORDER
EFFICACY_SCENARIOS = _core.EFFICACY_SCENARIOS
METRICS = _core.METRICS
POPULATIONS = _core.POPULATIONS
_excluded_count = _core._excluded_count
_number = _core._number
_require = _core._require


def kaplan_meier(events: list, censored: list, horizon: float) -> dict:
    """Kaplan--Meier curve and restricted mean survival to `horizon`.

    Events beyond the horizon are administratively censored at the horizon.
    Censored observations contribute risk time but never an event or a zero.
    """
    _require(_number(horizon) and horizon > 0, "horizon must be positive")
    _require(
        all(_number(value) and value >= 0 for value in events),
        "event times must be finite and non-negative",
    )
    _require(
        all(_number(value) and value >= 0 for value in censored),
        "censor times must be finite and non-negative",
    )
    n = len(events) + len(censored)
    if n == 0:
        return {
            "n": 0,
            "events": 0,
            "censored": 0,
            "horizon_seconds": horizon,
            "median_seconds": None,
            "median_reached": False,
            "rmst_seconds": None,
            "survival_at_horizon": None,
        }
    timeline: dict[float, list[int]] = {}
    observed = 0
    for value in events:
        if value > horizon:
            timeline[horizon] = timeline.get(horizon, [0, 0])
            timeline[horizon][1] += 1
        else:
            timeline.setdefault(value, [0, 0])[0] += 1
            observed += 1
    for value in censored:
        at = min(value, horizon)
        timeline.setdefault(at, [0, 0])[1] += 1
    at_risk = n
    survival = 1.0
    previous = 0.0
    rmst = 0.0
    median_time = None
    for time in sorted(timeline):
        deaths, stopped = timeline[time]
        rmst += survival * (time - previous)
        previous = time
        if at_risk > 0 and deaths:
            survival *= 1.0 - deaths / at_risk
            if median_time is None and survival <= 0.5:
                median_time = time
        at_risk -= deaths + stopped
    rmst += survival * max(0.0, horizon - previous)
    return {
        "n": n,
        "events": observed,
        "censored": n - observed,
        "horizon_seconds": horizon,
        "median_seconds": median_time,
        "median_reached": median_time is not None,
        "rmst_seconds": rmst,
        "survival_at_horizon": survival,
    }


def _survival_entries(rows: list, exclusions: dict | None = None) -> list:
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["scenario"], row["env"]), []).append(row)
    entries = []
    for (scenario, arm), group in sorted(
        groups.items(), key=lambda item: (item[0][0], ARM_ORDER[item[0][1]])
    ):
        for metric in METRICS:
            events = [
                row[metric + "_seconds"] for row in group if row[metric + "_status"] == "observed"
            ]
            censored = [
                row["censor_seconds"]
                for row in group
                if row[metric + "_status"] == "right_censored"
            ]
            missing = sum(1 for row in group if row[metric + "_status"] == "unobserved_before_stop")
            excluded = _excluded_count(exclusions, scenario, arm)
            horizon = min(row["censor_seconds"] for row in group)
            curve = kaplan_meier(events, censored, horizon)
            administrative = sum(1 for value in events if value > horizon)
            estimable = bool(events or censored)
            note = None
            if not estimable:
                note = (
                    "not estimable: all endpoints are missing before stop; "
                    "they are not censored observations"
                )
            elif administrative:
                note = "observed events beyond the RMST horizon are administratively censored"
            elif curve["events"] == 0:
                note = "all observations censored"
            elif missing:
                note = "missing endpoints excluded from survival, not censored"
            elif not curve["median_reached"]:
                note = "median not reached within horizon"
            entries.append(
                {
                    "scenario": scenario,
                    "arm": arm,
                    "metric": metric,
                    "population": POPULATIONS[scenario],
                    "included_in_efficacy": scenario in EFFICACY_SCENARIOS,
                    **curve,
                    "observed": len(events),
                    "right_censored": len(censored),
                    "missing": missing,
                    "excluded_runs": excluded,
                    "estimable": estimable,
                    "censor_limits_seconds": sorted({row["censor_seconds"] for row in group}),
                    "administratively_censored": administrative,
                    "median_estimable": curve["median_reached"],
                    "note": note,
                }
            )
    return entries


__all__ = [
    "_survival_entries",
    "kaplan_meier",
]
