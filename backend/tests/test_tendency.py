import pytest
from backend.annotation.tendency import is_model_written, tendency_report


def _r(reviewer, status, n, pred, final=None):
    return {
        "reviewer": reviewer, "status": status, "source_row_number": n,
        "prediction": {"relevance": "related", "labels": pred},
        "corrected_result": None if final is None else {"relevance": "related", "labels": final[0], **({"metadata": final[1]} if len(final) > 1 else {})},
    }


def test_reviewer_rates_label_changes_and_overlap():
    rows = [
        _r("smc", "approved", 1, ["a"]),
        _r("smc", "approved", 2, ["a"], ([ "a"], {"method": "model_semantic_review"})),
        _r("anna", "corrected", 10, ["a"], (["a", "b"],)),
        _r("anna", "corrected", 11, ["a", "c"], (["a"],)),
        _r("anna", "pending", 12, ["a"]),
    ]
    report = tendency_report(rows, ["a", "b", "c"])
    anna, smc = report["reviewers"]
    assert smc["approve_rate"] == 1.0 and smc["model_written"] == 1
    assert anna["correction_rate"] == 1.0 and anna["human_edited"] == 2
    assert report["pending_total"] == 1 and report["reviewed_total"] == 4
    assert report["reviewer_ranges_overlap"] is False
    assert report["coverage"][0]["by"] == {"smc": 1}
    by = {x["label_id"]: x for x in report["labels"]}
    assert by["b"]["added_by_review"] == 1 and by["c"]["removed_by_review"] == 1


def test_model_written_marker():
    assert is_model_written({"metadata": {"model": "x"}})
    assert not is_model_written({"metadata": {}}) and not is_model_written(None)


def test_statistics_helpers_match_known_values():
    from backend.annotation.tendency import chi_square_2x2, holm_adjust, mcnemar_exact_p, wilson_interval

    low, high = wilson_interval(8, 10)
    assert (low, high) == (0.4902, 0.9433)
    stat, p, phi = chi_square_2x2(20, 10, 10, 20)
    assert round(stat, 3) == 6.667 and round(p, 4) == 0.0098 and round(phi, 3) == 0.333
    assert chi_square_2x2(5, 0, 5, 0) is None
    assert mcnemar_exact_p(0, 10) == pytest.approx(2 / 1024)
    assert mcnemar_exact_p(0, 0) is None
    assert holm_adjust([0.01, 0.04, 0.03, None]) == [0.03, 0.06, 0.06, None]


def test_coverage_counts_actual_rows_not_min_max():
    from backend.annotation.tendency import coverage_bins, shared_share

    rows = [_r("a", "approved", n, ["x"]) for n in (1, 2, 3)] + [_r("b", "approved", n, ["x"]) for n in (98, 99, 100)]
    rows += [_r(None, "pending", n, ["x"]) for n in range(4, 98)]
    bins = coverage_bins(rows, bins=4)
    assert sum(c["total"] for c in bins) == 100
    assert bins[0]["by"] == {"a": 3} and bins[-1]["by"] == {"b": 3}
    assert bins[1]["by"] == {}  # the gap between them is not "covered"
    assert shared_share(bins, "a", "b") == 0.0
