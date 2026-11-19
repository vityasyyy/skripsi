"""Inferential statistics and effect sizes for the live analysis."""

from __future__ import annotations

import itertools
import math
import random
from statistics import median

if __package__:
    from . import core as _core
else:  # direct script execution
    import core as _core  # type: ignore[no-redef]

MIN_GROUP = _core.MIN_GROUP
MIN_PAIRS = _core.MIN_PAIRS
_EndpointCounts = _core._EndpointCounts
_excluded_count = _core._excluded_count
_number = _core._number
_require = _core._require


def _average_ranks(values: list) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[order[position]] = rank
        start = end
    return ranks


def cliffs_delta(first: list, second: list) -> float | None:
    """P(first > second) - P(first < second), in [-1, 1]."""
    if not first or not second:
        return None
    greater = sum(1 for left in first for right in second if left > right)
    less = sum(1 for left in first for right in second if left < right)
    return (greater - less) / (len(first) * len(second))


def mann_whitney_u(first: list, second: list) -> dict:
    """Two-sided Mann--Whitney U via the tie-corrected normal approximation."""
    n1, n2 = len(first), len(second)
    if n1 < MIN_GROUP or n2 < MIN_GROUP:
        return {
            "statistic": None,
            "p_value": None,
            "method": "not_estimable",
            "n_manual": n1,
            "n_gitops": n2,
            "note": "fewer than 3 per arm",
        }
    combined = list(first) + list(second)
    ranks = _average_ranks(combined)
    rank_sum = sum(ranks[:n1])
    u1 = rank_sum - n1 * (n1 + 1) / 2.0
    u2 = n1 * n2 - u1
    total = n1 + n2
    tie_sum = 0
    for value in set(combined):
        count = combined.count(value)
        tie_sum += count**3 - count
    variance = (n1 * n2 / 12.0) * ((total + 1) - tie_sum / (total * (total - 1)))
    if variance <= 0:
        return {
            "statistic": min(u1, u2),
            "p_value": 1.0,
            "method": "normal_approximation_tie_corrected",
            "n_manual": n1,
            "n_gitops": n2,
            "note": "all observations tied",
        }
    z = (abs(u1 - n1 * n2 / 2.0) - 0.5) / math.sqrt(variance)
    p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
    p_value = min(1.0, max(0.0, p_value))
    return {
        "statistic": min(u1, u2),
        "p_value": p_value,
        "method": "normal_approximation_tie_corrected",
        "n_manual": n1,
        "n_gitops": n2,
        "note": None,
    }


def wilcoxon_signed_rank(differences: list) -> dict:
    """Two-sided Wilcoxon signed-rank test with exact p for n <= 16."""
    nonzero = [value for value in differences if value != 0]
    n = len(nonzero)
    if n == 0:
        return {
            "statistic": 0.0,
            "w_plus": 0.0,
            "w_minus": 0.0,
            "p_value": 1.0,
            "method": "all_zero",
            "n_nonzero": 0,
            "n_pairs": len(differences),
            "rank_biserial": 0.0,
        }
    ranks = _average_ranks([abs(value) for value in nonzero])
    w_plus = sum(rank for rank, value in zip(ranks, nonzero) if value > 0)
    w_minus = sum(rank for rank, value in zip(ranks, nonzero) if value < 0)
    if n <= 16:
        observed = round(w_plus, 9)
        lower = upper = 0
        for signs in itertools.product((1, -1), repeat=n):
            total = round(sum(rank for rank, sign in zip(ranks, signs) if sign > 0), 9)
            if total <= observed + 1e-9:
                lower += 1
            if total >= observed - 1e-9:
                upper += 1
        p_value = min(1.0, 2.0 * min(lower, upper) / (2**n))
        method = "exact_sign_flip"
    else:
        mean = n * (n + 1) / 4.0
        tie_sum = 0
        for value in {abs(item) for item in nonzero}:
            count = sum(1 for item in nonzero if abs(item) == value)
            tie_sum += count**3 - count
        variance = n * (n + 1) * (2 * n + 1) / 24.0 - tie_sum / 48.0
        z = (abs(w_plus - mean) - 0.5) / math.sqrt(variance)
        p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
        p_value = min(1.0, max(0.0, p_value))
        method = "normal_approximation_tie_corrected"
    total_rank = w_plus + w_minus
    rank_biserial = ((w_plus - w_minus) / total_rank) if total_rank else 0.0
    return {
        "statistic": w_plus,
        "w_plus": w_plus,
        "w_minus": w_minus,
        "p_value": p_value,
        "method": method,
        "n_nonzero": n,
        "n_pairs": len(differences),
        "rank_biserial": rank_biserial,
    }


def holm_adjust(p_values: list, family_size: int) -> list[float | None]:
    """Holm step-down adjusted p-values, preserving input order."""
    _require(family_size >= len(p_values), "family size cannot be smaller than tested hypotheses")
    _require(
        all(_number(value) and 0 <= value <= 1 for value in p_values), "p-values must be in [0, 1]"
    )
    adjusted: list[float | None] = [None] * len(p_values)
    running = 0.0
    for rank, index in enumerate(sorted(range(len(p_values)), key=lambda item: p_values[item]), 1):
        candidate = min(1.0, (family_size - rank + 1) * p_values[index])
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def _percentile(sorted_values: list, fraction: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _bootstrap_cliff(
    first: list, second: list, resamples: int, seed: int, pairs: list | None = None
) -> list[float | None] | None:
    if not first or not second:
        return None
    rng = random.Random(f"{seed}:cliff")
    values = []
    if pairs:
        for _ in range(resamples):
            sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
            values.append(cliffs_delta([item[0] for item in sample], [item[1] for item in sample]))
    else:
        for _ in range(resamples):
            left = [rng.choice(first) for _ in first]
            right = [rng.choice(second) for _ in second]
            values.append(cliffs_delta(left, right))
    values.sort()
    return [_percentile(values, 0.025), _percentile(values, 0.975)]


def _bootstrap_median(values: list, resamples: int, seed: int) -> list[float | None] | None:
    if not values:
        return None
    rng = random.Random(f"{seed}:paired")
    draws = sorted(median([rng.choice(values) for _ in values]) for _ in range(resamples))
    return [_percentile(draws, 0.025), _percentile(draws, 0.975)]


def _pairing(rows: list, metric: str) -> dict:
    arms: dict[str, dict[int, dict]] = {"manual": {}, "gitops": {}}
    for row in rows:
        arms[row["env"]][row["rep"]] = row
    blocks = sorted(set(arms["manual"]) | set(arms["gitops"]))
    matched = [rep for rep in blocks if rep in arms["manual"] and rep in arms["gitops"]]
    complete = [
        rep
        for rep in matched
        if arms["manual"][rep][metric + "_status"] == "observed"
        and arms["gitops"][rep][metric + "_status"] == "observed"
    ]
    missing = [
        rep
        for rep in matched
        if "unobserved_before_stop"
        in (arms["manual"][rep][metric + "_status"], arms["gitops"][rep][metric + "_status"])
    ]
    censored = [
        rep
        for rep in matched
        if rep not in missing
        and "right_censored"
        in (arms["manual"][rep][metric + "_status"], arms["gitops"][rep][metric + "_status"])
    ]
    unmatched = len(blocks) - len(matched)
    if blocks and not unmatched and not missing and not censored and len(complete) >= MIN_PAIRS:
        return {
            "method": "paired",
            "reason": "complete_paired_blocks",
            "blocks": len(blocks),
            "complete_pairs": len(complete),
            "right_censored_blocks": 0,
            "missing_blocks": 0,
            "unmatched_blocks": 0,
            "censored_blocks": 0,
        }
    if not blocks:
        reason = "no_r2_rows"
    elif unmatched:
        reason = "unmatched_arm_blocks"
    elif missing:
        reason = "missing_blocks"
    elif censored:
        reason = "censored_blocks"
    else:
        reason = "fewer_than_2_pairs"
    return {
        "method": "unpaired",
        "reason": reason,
        "blocks": len(blocks),
        "complete_pairs": len(complete),
        "right_censored_blocks": len(censored),
        "missing_blocks": len(missing),
        "unmatched_blocks": unmatched,
        "censored_blocks": len(censored),
    }


def _comparison(
    rows: list,
    scenario: str,
    metric: str,
    bootstrap: int,
    seed: int,
    exclusions: dict | None = None,
) -> dict:
    pairing = _pairing(rows, metric)
    manual = {row["rep"]: row for row in rows if row["env"] == "manual"}
    gitops = {row["rep"]: row for row in rows if row["env"] == "gitops"}
    observed: dict[str, list[float]] = {"manual": [], "gitops": []}
    counts: dict[str, _EndpointCounts] = {}
    for arm, rows_by_rep in (("manual", manual), ("gitops", gitops)):
        counts[arm] = {
            "observed": 0,
            "right_censored": 0,
            "missing": 0,
            "excluded": _excluded_count(exclusions, scenario, arm),
        }
        for row in rows_by_rep.values():
            status = row[metric + "_status"]
            if status == "observed":
                observed[arm].append(row[metric + "_seconds"])
                counts[arm]["observed"] += 1
            elif status == "right_censored":
                counts[arm]["right_censored"] += 1
            else:
                counts[arm]["missing"] += 1
    differences: list[float] = []
    pairs: list[tuple[float, float]] = []
    if pairing["method"] == "paired":
        for rep in sorted(set(manual) & set(gitops)):
            left = manual[rep][metric + "_seconds"]
            right = gitops[rep][metric + "_seconds"]
            differences.append(left - right)
            pairs.append((left, right))
    effect = {
        "cliffs_delta": cliffs_delta(observed["manual"], observed["gitops"]),
        "cliffs_delta_ci": _bootstrap_cliff(
            observed["manual"], observed["gitops"], bootstrap, seed, pairs=pairs or None
        ),
        "cliffs_delta_bootstrap": ("paired_blocks" if pairs else "independent_arms"),
        "median_paired_difference": None,
        "median_paired_difference_ci": None,
        "rank_biserial": None,
    }
    if pairing["method"] == "paired":
        difference_median = median(differences)
        effect["median_paired_difference"] = difference_median
        effect["median_paired_difference_ci"] = _bootstrap_median(differences, bootstrap, seed)
        test = wilcoxon_signed_rank(differences)
        effect["rank_biserial"] = test["rank_biserial"]
        test_name = "wilcoxon_signed_rank"
        statistic = test["statistic"]
        p_value = test["p_value"]
        method = test["method"]
        size = {"n_pairs": len(differences), "n_nonzero": test["n_nonzero"]}
    elif len(observed["manual"]) >= MIN_GROUP and len(observed["gitops"]) >= MIN_GROUP:
        test = mann_whitney_u(observed["manual"], observed["gitops"])
        test_name = "mann_whitney_u"
        statistic = test["statistic"]
        p_value = test["p_value"]
        method = test["method"]
        size = {"n_manual": len(observed["manual"]), "n_gitops": len(observed["gitops"])}
    else:
        test_name, statistic, p_value = "not_estimable", None, None
        method = "not_estimable"
        size = {"n_manual": len(observed["manual"]), "n_gitops": len(observed["gitops"])}
    if pairing["method"] == "paired":
        analysis_set = "paired_complete_blocks"
        note = "Paired complete-case comparison; censored blocks are not used in the efficacy test."
    elif test_name == "not_estimable":
        analysis_set = "not_estimable"
        note = "Not estimable from the available observations."
    else:
        analysis_set = "observed_values_only"
        note = "Unpaired fallback uses observed values only; censoring is not adjusted."
    if pairing["missing_blocks"]:
        note += (
            " Missing endpoints are excluded from the numeric test and "
            "are not treated as censored observations."
        )
    return {
        "scenario": scenario,
        "metric": metric,
        "population": "managed_drift",
        "pairing": pairing,
        "analysis_set": analysis_set,
        "censoring_adjusted": False,
        "note": note,
        "endpoints": counts,
        "test": {
            "name": test_name,
            "statistic": statistic,
            "p_value": p_value,
            "method": method,
            **size,
        },
        "effect": effect,
    }


__all__ = [
    "_average_ranks",
    "_bootstrap_cliff",
    "_bootstrap_median",
    "_comparison",
    "_pairing",
    "_percentile",
    "cliffs_delta",
    "holm_adjust",
    "mann_whitney_u",
    "wilcoxon_signed_rank",
]
