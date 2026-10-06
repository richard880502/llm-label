"""Annotation-tendency summary computed from existing review records.

No extra labelling is needed: it compares each reviewer's final results with
the AI prediction. Pure functions so they can be unit tested without a database.
"""

import math
from collections import Counter
from itertools import combinations
from typing import Any, Mapping, Sequence

REVIEWED = ("approved", "corrected", "uncertain")


def _labels(result: Mapping[str, Any] | None) -> set[str]:
    return {str(x) for x in ((result or {}).get("labels") or [])}


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion; sound for small n and extreme rates."""
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def chi_square_2x2(a: int, b: int, c: int, d: int) -> tuple[float, float, float] | None:
    """Pearson chi-square (no continuity correction) for [[a, b], [c, d]].

    Returns (statistic, p_value, phi). None when a margin is empty.
    """
    n = a + b + c + d
    r1, r2, c1, c2 = a + b, c + d, a + c, b + d
    if 0 in (r1, r2, c1, c2):
        return None
    statistic = n * (a * d - b * c) ** 2 / (r1 * r2 * c1 * c2)
    return statistic, math.erfc(math.sqrt(statistic / 2)), math.sqrt(statistic / n)


def mcnemar_exact_p(only_a: int, only_b: int) -> float | None:
    """Two-sided exact McNemar test from the two discordant counts."""
    n = only_a + only_b
    if n == 0:
        return None
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def holm_adjust(p_values: Sequence[float | None]) -> list[float | None]:
    """Holm-Bonferroni adjusted p-values; None entries are left untouched."""
    indexed = sorted((p, i) for i, p in enumerate(p_values) if p is not None)
    adjusted: list[float | None] = [None] * len(p_values)
    running = 0.0
    m = len(indexed)
    for rank, (p, i) in enumerate(indexed):
        running = max(running, min(1.0, (m - rank) * p))
        adjusted[i] = round(running, 4)
    return adjusted


def is_model_written(result: Mapping[str, Any] | None) -> bool:
    """True when a stored result carries an AI-model provenance marker."""
    metadata = (result or {}).get("metadata") or {}
    return bool(metadata.get("method") or metadata.get("model"))


COVERAGE_BINS = 24
SHARED_BIN_SHARE = 0.05  # a reviewer "covers" a bin when they reviewed >= 5% of its rows


def coverage_bins(rows: Sequence[Mapping[str, Any]], bins: int = COVERAGE_BINS) -> list[dict[str, Any]]:
    """Reviewed counts per reviewer across equal-width spans of source row numbers."""
    numbered = [r for r in rows if r.get("source_row_number") is not None]
    if not numbered:
        return []
    low = min(r["source_row_number"] for r in numbered)
    high = max(r["source_row_number"] for r in numbered)
    width = max(1, math.ceil((high - low + 1) / bins))
    out = [
        {"start": low + i * width, "end": min(high, low + (i + 1) * width - 1), "total": 0, "pending": 0, "by": {}}
        for i in range(math.ceil((high - low + 1) / width))
    ]
    for r in numbered:
        cell = out[(r["source_row_number"] - low) // width]
        cell["total"] += 1
        if r["status"] == "pending":
            cell["pending"] += 1
        elif r["status"] in REVIEWED:
            name = r.get("reviewer") or "（未知）"
            cell["by"][name] = cell["by"].get(name, 0) + 1
    return out


def shared_share(bins: Sequence[Mapping[str, Any]], a: str, b: str) -> float:
    """Of the bins either reviewer covers, the share both cover."""
    def covers(cell: Mapping[str, Any], name: str) -> bool:
        return cell["total"] > 0 and cell["by"].get(name, 0) / cell["total"] >= SHARED_BIN_SHARE

    either = [c for c in bins if covers(c, a) or covers(c, b)]
    both = [c for c in either if covers(c, a) and covers(c, b)]
    return len(both) / len(either) if either else 0.0


def tendency_report(rows: Sequence[Mapping[str, Any]], label_ids: Sequence[str]) -> dict[str, Any]:
    """``rows``: dicts with reviewer, status, source_row_number, prediction, corrected_result."""
    reviewed_rows = [r for r in rows if r["status"] in REVIEWED]

    by_reviewer: dict[str, list[Mapping[str, Any]]] = {}
    for row in reviewed_rows:
        by_reviewer.setdefault(row.get("reviewer") or "（未知）", []).append(row)

    reviewers = []
    for name, items in sorted(by_reviewer.items()):
        statuses = Counter(r["status"] for r in items)
        final_counts: Counter[str] = Counter()
        for r in items:
            final_counts.update(_labels(r.get("corrected_result") or r.get("prediction")))
        numbers = [r["source_row_number"] for r in items if r.get("source_row_number") is not None]
        decided = statuses["approved"] + statuses["corrected"]
        reviewers.append(
            {
                "name": name,
                "reviewed": len(items),
                "approved": statuses["approved"],
                "corrected": statuses["corrected"],
                "uncertain": statuses["uncertain"],
                "approve_rate": _rate(statuses["approved"], decided),
                "approve_ci": wilson_interval(statuses["approved"], decided),
                "correction_rate": _rate(statuses["corrected"], decided),
                "model_written": sum(1 for r in items if is_model_written(r.get("corrected_result"))),
                "human_edited": sum(
                    1 for r in items
                    if r.get("corrected_result") and not is_model_written(r["corrected_result"])
                ),
                "first_row": min(numbers) if numbers else None,
                "last_row": max(numbers) if numbers else None,
                "top_labels": [
                    {"label_id": label, "rate": _rate(count, len(items))}
                    for label, count in final_counts.most_common(5)
                ],
            }
        )

    bins = coverage_bins(rows)
    names = [r["name"] for r in reviewers]
    overlap = any(shared_share(bins, a, b) >= 0.25 for a, b in combinations(names, 2))

    comparisons = []
    for first, second in combinations(reviewers, 2):
        test = chi_square_2x2(
            first["approved"], first["corrected"], second["approved"], second["corrected"]
        )
        comparisons.append(
            {
                "a": first["name"],
                "b": second["name"],
                "p_value": None if test is None else test[1],
                "effect_phi": None if test is None else round(test[2], 4),
                "shared_share": round(shared_share(bins, first["name"], second["name"]), 4),
                "confounded": shared_share(bins, first["name"], second["name"]) < 0.25,
            }
        )
    for item, adjusted in zip(comparisons, holm_adjust([c["p_value"] for c in comparisons])):
        item["p_adjusted"] = adjusted
        if item["p_value"] is not None:
            item["p_value"] = round(item["p_value"], 6)

    decided_rows = [r for r in reviewed_rows if r["status"] in ("approved", "corrected") and r.get("prediction")]
    added: Counter[str] = Counter()
    removed: Counter[str] = Counter()
    ai_count: Counter[str] = Counter()
    final_count: Counter[str] = Counter()
    relevance_flips = 0
    for r in decided_rows:
        predicted = _labels(r["prediction"])
        final_result = r.get("corrected_result") or r["prediction"]
        final = _labels(final_result)
        ai_count.update(predicted)
        final_count.update(final)
        added.update(final - predicted)
        removed.update(predicted - final)
        if final_result.get("relevance") != r["prediction"].get("relevance"):
            relevance_flips += 1

    label_p = holm_adjust(
        [mcnemar_exact_p(removed[label], added[label]) for label in label_ids]
    )
    labels = [
        {
            "label_id": label,
            "p_adjusted": label_p[index],
            "direction": (
                None if added[label] == removed[label]
                else "added" if added[label] > removed[label] else "removed"
            ),
            "ai_rate": _rate(ai_count[label], len(decided_rows)),
            "final_rate": _rate(final_count[label], len(decided_rows)),
            "added_by_review": added[label],
            "removed_by_review": removed[label],
        }
        for index, label in enumerate(label_ids)
    ]

    return {
        "reviewed_total": len(reviewed_rows),
        "pending_total": sum(1 for r in rows if r["status"] == "pending"),
        "reviewers": reviewers,
        "reviewer_ranges_overlap": overlap,
        "coverage": bins,
        "reviewer_comparisons": comparisons,
        "compared_rows": len(decided_rows),
        "relevance_flips": relevance_flips,
        "labels": labels,
    }
