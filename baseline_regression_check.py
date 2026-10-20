"""Verify regenerated historical scores against the supplied previous baseline."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from newlands_integrated_pipeline import run_pipeline


def main() -> int:
    root = Path(__file__).resolve().parent
    baseline_dir = root / "reference" / "previous_baseline"
    if not baseline_dir.exists():
        raise FileNotFoundError(f"Previous baseline folder was not found: {baseline_dir}")
    baseline_wide = pd.read_csv(baseline_dir / "Newlands_baseline_07062026_wide.csv")
    baseline_long = pd.read_csv(baseline_dir / "Newlands_baseline_02072026_long.csv")
    baseline_long["year"] = pd.to_datetime(
        baseline_long["date"], errors="coerce", dayfirst=True
    ).dt.year

    with TemporaryDirectory(prefix="newlands_regression_") as temp:
        output = Path(temp) / "output"
        run_pipeline(root / "data" / "raw", output, skip_charts=True)
        current_wide = pd.read_csv(output / "data" / "Newlands_baseline_wide.csv")
        current_long = pd.read_csv(output / "data" / "Newlands_analysis_ready_long.csv")

    baseline_scores = (
        baseline_long.dropna(subset=["CleanScore"])
        .groupby(["year", "Question"])["CleanScore"]
        .agg(["count", "sum", "mean"])
        .sort_index()
    )
    current_scores = (
        current_long.dropna(subset=["CleanScore"])
        .groupby(["survey_year", "Question"])["CleanScore"]
        .agg(["count", "sum", "mean"])
        .sort_index()
    )
    current_scores.index.names = ["year", "Question"]

    problems: list[str] = []
    if list(baseline_wide.columns) != list(current_wide.columns):
        problems.append("wide schemas differ")
    if len(baseline_wide) != len(current_wide):
        problems.append(
            f"wide row count differs: {len(current_wide)} vs {len(baseline_wide)}"
        )
    if not baseline_scores.equals(current_scores):
        comparison = baseline_scores.join(
            current_scores, lsuffix="_baseline", rsuffix="_current", how="outer"
        )
        mismatched = comparison[
            comparison["count_baseline"].ne(comparison["count_current"])
            | comparison["sum_baseline"].ne(comparison["sum_current"])
            | comparison["mean_baseline"].ne(comparison["mean_current"])
        ]
        problems.append(f"{len(mismatched)} year-question score aggregates differ")

    if problems:
        print("BASELINE REGRESSION FAILED")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("BASELINE REGRESSION PASSED")
    print(f"- wide respondents: {len(current_wide)}")
    print(f"- scored long rows: {int(current_scores['count'].sum())}")
    print(f"- exact year-question aggregates: {len(current_scores)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
