from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from textwrap import wrap

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT_DIR = Path(__file__).resolve().parent
RAW_DIR = ROOT_DIR / "data" / "raw"
CONFIG_DIR = ROOT_DIR / "data" / "config"
OUTPUT_DATA_DIR = ROOT_DIR / "output" / "data"
OUTPUT_CHART_DIR = ROOT_DIR / "output" / "charts"

HISTORICAL_START_YEAR = 2019
HISTORICAL_END_YEAR = 2025
BACKFILL_YEAR = 2023
BACKFILL_SOURCE_YEAR = 2022
PROJECTION_START_YEAR = 2026
PROJECTION_END_YEAR = 2035
ACORN_START_YEAR = 2028
ACORN_TARGET_YEAR = 2030
ACORN_TRIGGER_SCORE = 60
ACORN_TARGET_SCORE = 70
P2G_START_YEAR = 2030
P2G_LINE_START_YEAR = 2030
P2G_CONSTRUCTION_END_YEAR = 2033
FIGSIZE = (13.333, 7.5)
DPI = 300
SUBPLOT_ADJUST = {
    "left": 0.08,
    "right": 0.92,
    "top": 0.92,
    "bottom": 0.22,
}

COLOR_MAP = {
    "cultural": "teal",
    "disaster": "orange",
    "economic": "black",
    "environment": "green",
    "governance": "blue",
    "social": "purple",
}

OVERVIEW_COLOR_MAP = {
    "Economic": "#DAA520",
    "Environment": "#2E8B57",
    "Cultural": "#6A0DAD",
    "Disaster": "#FF4500",
    "Governance": "#0057FF",
    "Subjective Wellbeing": "#FF66CC",
    "Other Social": "#7B68EE",
}

INDICATOR_COLOR_OVERRIDES = {
    "trust_nz_government": "#0057FF",
    "trust_local_council": "#0033AA",
    "trust_nz_police": "#FF7A00",
}

INDICATOR_PALETTE = [
    "#0057FF",
    "#FF7A00",
    "#00A676",
    "#C000FF",
    "#E0002A",
    "#008CFF",
    "#FFC400",
    "#111111",
    "#7A3E00",
    "#00B8C8",
    "#7F00FF",
    "#5A8F00",
]

GROUP_ORDER = [
    "Economic",
    "Environment",
    "Cultural",
    "Disaster",
    "Governance",
    "Subjective Wellbeing",
    "Other Social",
]

OVERVIEW_GROUP_ORDER = GROUP_ORDER

AREA_ORDER = [
    "economic",
    "environment",
    "cultural",
    "disaster",
    "governance",
    "social",
]


@dataclass(frozen=True)
class InputFiles:
    historical_long: Path = RAW_DIR / "Newlands_baseline_02072026_long.csv"
    mapping: Path = CONFIG_DIR / "scoring_mapping_adjusted.csv"
    subjective_wellbeing: Path = CONFIG_DIR / "Subjective Wellbeing.tsv"
    other_social: Path = CONFIG_DIR / "Other Social.tsv"
    p2g_indicators: Path = CONFIG_DIR / "Linked indicators to P2G.csv"


def require_columns(df: pd.DataFrame, required: set[str], file_name: str) -> None:
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(
            f"{file_name} is missing required column(s): {', '.join(missing)}"
        )


def load_data(files: InputFiles = InputFiles()) -> dict[str, pd.DataFrame]:
    """Load project inputs and fail early if an expected file or column is missing."""
    for path in [
        files.historical_long,
        files.mapping,
        files.subjective_wellbeing,
        files.other_social,
        files.p2g_indicators,
    ]:
        if not path.exists():
            raise FileNotFoundError(f"Required input file not found: {path}")

    historical = pd.read_csv(files.historical_long, encoding="utf-8-sig")
    mapping = pd.read_csv(files.mapping, encoding="utf-8-sig")
    subjective = pd.read_csv(files.subjective_wellbeing, sep="\t", encoding="utf-8-sig")
    other_social = pd.read_csv(files.other_social, sep="\t", encoding="utf-8-sig")
    p2g_indicators = pd.read_csv(files.p2g_indicators, encoding="utf-8-sig")

    require_columns(
        historical,
        {"date", "Question", "CleanScore"},
        str(files.historical_long),
    )
    require_columns(
        mapping,
        {"Question", "Resilience_ID", "resilience_description", "subdomain"},
        str(files.mapping),
    )
    require_columns(subjective, {"Question"}, str(files.subjective_wellbeing))
    require_columns(other_social, {"Question"}, str(files.other_social))
    require_columns(
        p2g_indicators,
        {"Question", "2030 - 2033", "After 2033"},
        str(files.p2g_indicators),
    )
    if p2g_indicators["Question"].duplicated().any():
        duplicates = sorted(
            p2g_indicators.loc[p2g_indicators["Question"].duplicated(False), "Question"]
            .astype(str)
            .unique()
        )
        raise ValueError("Duplicate P2G indicators: " + ", ".join(duplicates))
    for column in ["2030 - 2033", "After 2033"]:
        p2g_indicators[column] = pd.to_numeric(p2g_indicators[column], errors="raise")

    return {
        "historical": historical,
        "mapping": mapping,
        "subjective": subjective,
        "other_social": other_social,
        "p2g_indicators": p2g_indicators,
    }


def build_group_lookup(
    mapping: pd.DataFrame, subjective: pd.DataFrame, other_social: pd.DataFrame
) -> dict[str, str]:
    subjective_questions = set(subjective["Question"].dropna().astype(str))
    other_social_questions = set(other_social["Question"].dropna().astype(str))
    overlap = subjective_questions & other_social_questions
    if overlap:
        raise ValueError(
            "Subjective Wellbeing and Other Social contain overlapping questions: "
            + ", ".join(sorted(overlap))
        )

    social_questions = set(
        mapping.loc[
            mapping["resilience_description"].str.lower().eq("social"), "Question"
        ].dropna()
    )
    unassigned_social = social_questions - subjective_questions - other_social_questions
    if unassigned_social:
        raise ValueError(
            "These social questions are missing from the social split files: "
            + ", ".join(sorted(unassigned_social))
        )

    group_lookup: dict[str, str] = {}
    for _, row in mapping.iterrows():
        question = str(row["Question"])
        area = str(row["resilience_description"]).strip().lower()
        if question in subjective_questions:
            group_lookup[question] = "Subjective Wellbeing"
        elif question in other_social_questions:
            group_lookup[question] = "Other Social"
        else:
            group_lookup[question] = area.title()
    return group_lookup


def clean_data(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Prepare annual historical data and backfill 2023 from 2022 survey values."""
    historical = data["historical"].copy()
    mapping = data["mapping"].copy()
    group_lookup = build_group_lookup(mapping, data["subjective"], data["other_social"])

    historical["date"] = pd.to_datetime(
        historical["date"], dayfirst=True, errors="coerce"
    )
    historical["year"] = historical["date"].dt.year
    historical["CleanScore"] = pd.to_numeric(historical["CleanScore"], errors="coerce")
    historical = historical.dropna(subset=["year", "Question", "CleanScore"])
    historical["year"] = historical["year"].astype(int)
    historical = historical[
        historical["year"].between(HISTORICAL_START_YEAR, HISTORICAL_END_YEAR)
    ].copy()
    historical["is_backfilled"] = False

    if BACKFILL_YEAR not in set(historical["year"]):
        source = historical[historical["year"] == BACKFILL_SOURCE_YEAR].copy()
        if source.empty:
            raise ValueError(
                f"Cannot backfill {BACKFILL_YEAR}: no rows found for "
                f"{BACKFILL_SOURCE_YEAR}."
            )
        source["year"] = BACKFILL_YEAR
        source["date"] = pd.to_datetime(f"{BACKFILL_YEAR}-07-01")
        source["is_backfilled"] = True
        historical = pd.concat([historical, source], ignore_index=True)

    mapping_cols = [
        "Question",
        "Resilience_ID",
        "resilience_description",
        "subdomain",
    ]
    cleaned = historical.merge(mapping[mapping_cols], on="Question", how="left")
    missing_mapping = sorted(
        cleaned.loc[cleaned["resilience_description"].isna(), "Question"].unique()
    )
    if missing_mapping:
        raise ValueError(
            "These historical questions are missing from scoring_mapping_adjusted.csv: "
            + ", ".join(missing_mapping)
        )

    cleaned["resilience_description"] = (
        cleaned["resilience_description"].astype(str).str.strip().str.lower()
    )
    cleaned["group"] = cleaned["Question"].map(group_lookup)
    cleaned["area_color_key"] = cleaned["resilience_description"]
    return cleaned


def annual_question_scores(cleaned: pd.DataFrame) -> pd.DataFrame:
    yearly = (
        cleaned.groupby(
            [
                "Question",
                "year",
                "Resilience_ID",
                "resilience_description",
                "subdomain",
                "group",
                "area_color_key",
            ],
            dropna=False,
        )
        .agg(score=("CleanScore", "mean"), is_backfilled=("is_backfilled", "max"))
        .reset_index()
    )
    yearly["level"] = "question"
    return yearly


def projection_years_after_observations(observed: pd.DataFrame) -> np.ndarray:
    """Return forecast years strictly after the latest imported actual year."""
    years = pd.to_numeric(observed["year"], errors="coerce").dropna()
    if years.empty:
        projection_start_year = PROJECTION_START_YEAR
    else:
        projection_start_year = max(PROJECTION_START_YEAR, int(years.max()) + 1)
    return np.arange(projection_start_year, PROJECTION_END_YEAR + 1)


def fit_linear_projection(
    yearly: pd.DataFrame, entity_cols: list[str], score_col: str = "score"
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    projection_years = projection_years_after_observations(yearly)

    for keys, group_df in yearly.groupby(entity_cols, dropna=False):
        group_df = group_df.sort_values("year").copy()
        group_df["source"] = np.where(
            group_df["is_backfilled"], "backfilled", "historical"
        )
        group_df["scenario"] = "BAU"

        x = group_df["year"].to_numpy(dtype=float)
        y = group_df[score_col].to_numpy(dtype=float)
        if group_df["year"].nunique() < 2:
            slope = 0.0
            intercept = float(y[0])
        else:
            slope, intercept = np.polyfit(x, y, deg=1)
        group_df["trend_score"] = np.clip(slope * x + intercept, 0, 100)
        group_df["display_score"] = group_df[score_col]

        projection = pd.DataFrame({"year": projection_years})
        if not isinstance(keys, tuple):
            keys = (keys,)
        for col, value in zip(entity_cols, keys):
            projection[col] = value
        projection["score"] = np.nan
        projection["is_backfilled"] = False
        projection["source"] = "projected"
        projection["scenario"] = "BAU"
        projection["trend_score"] = np.clip(
            slope * projection["year"].to_numpy(dtype=float) + intercept, 0, 100
        )
        projection["display_score"] = projection["trend_score"]

        rows.append(pd.concat([group_df, projection], ignore_index=True))

    return pd.concat(rows, ignore_index=True)


def calculate_bau_trend(cleaned: pd.DataFrame) -> pd.DataFrame:
    question_yearly = annual_question_scores(cleaned)

    question_cols = [
        "Question",
        "Resilience_ID",
        "resilience_description",
        "subdomain",
        "group",
        "area_color_key",
        "level",
    ]
    question_bau = fit_linear_projection(question_yearly, question_cols)

    area_yearly = (
        question_yearly.groupby(["group", "area_color_key", "year"], dropna=False)
        .agg(score=("score", "mean"), is_backfilled=("is_backfilled", "max"))
        .reset_index()
    )
    area_yearly["Question"] = ""
    area_yearly["Resilience_ID"] = ""
    area_yearly["resilience_description"] = area_yearly["area_color_key"]
    area_yearly["subdomain"] = ""
    area_yearly["level"] = "area"
    area_cols = [
        "Question",
        "Resilience_ID",
        "resilience_description",
        "subdomain",
        "group",
        "area_color_key",
        "level",
    ]
    area_bau = fit_linear_projection(area_yearly, area_cols)

    output = pd.concat([area_bau, question_bau], ignore_index=True, sort=False)
    output["year"] = output["year"].astype(int)
    output["score"] = output["score"].clip(0, 100)
    output["trend_score"] = output["trend_score"].clip(0, 100)
    output["display_score"] = output["display_score"].clip(0, 100)
    output = output[
        [
            "scenario",
            "level",
            "source",
            "year",
            "group",
            "area_color_key",
            "resilience_description",
            "Resilience_ID",
            "subdomain",
            "Question",
            "score",
            "trend_score",
            "display_score",
            "is_backfilled",
        ]
    ].sort_values(["level", "group", "Question", "year"])
    duplicate_identity = ["scenario", "level", "group", "Question", "year"]
    duplicates = output.duplicated(duplicate_identity, keep=False)
    if duplicates.any():
        sample = output.loc[duplicates, duplicate_identity + ["source"]].head(10)
        raise ValueError(
            "BAU output contains overlapping actual and projected rows:\n"
            + sample.to_string(index=False)
        )
    return output


def monte_carlo_simulation(
    years: np.ndarray,
    trend: np.ndarray,
    sigma: float,
    n_sim: int = 1000,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    simulations = trend + rng.normal(0, sigma, size=(n_sim, len(years)))
    return pd.DataFrame(
        {
            "year": years,
            "trend": trend,
            "median": np.median(simulations, axis=0),
            "p25": np.percentile(simulations, 25, axis=0),
            "p75": np.percentile(simulations, 75, axis=0),
            "p05": np.percentile(simulations, 5, axis=0),
            "p95": np.percentile(simulations, 95, axis=0),
        }
    )


def calculate_bau_projection_per_question(cleaned: pd.DataFrame) -> pd.DataFrame:
    """Export BAU in the same shape as the team's legacy per-question file."""
    yearly = (
        cleaned.groupby(["Question", "year"], dropna=False)["CleanScore"]
        .mean()
        .reset_index()
        .sort_values(["Question", "year"])
    )
    future_years = projection_years_after_observations(yearly)
    outputs: list[pd.DataFrame] = []

    for question, question_df in yearly.groupby("Question", sort=True):
        question_df = question_df.sort_values("year").copy()
        x = question_df["year"].to_numpy(dtype=float)
        y = question_df["CleanScore"].to_numpy(dtype=float)

        if question_df["year"].nunique() < 2:
            historical = question_df.copy()
            historical["trend"] = np.nan
            historical["median"] = np.nan
            historical["p25"] = np.nan
            historical["p75"] = np.nan
            historical["p05"] = np.nan
            historical["p95"] = np.nan
            historical["domain"] = question
            historical["type"] = "historical"
            outputs.append(historical)
            continue

        slope, intercept = np.polyfit(x, y, deg=1)
        historical = question_df.copy()
        historical["trend"] = slope * x + intercept
        historical["median"] = np.nan
        historical["p25"] = np.nan
        historical["p75"] = np.nan
        historical["p05"] = np.nan
        historical["p95"] = np.nan
        historical["domain"] = question
        historical["type"] = "historical"

        sigma = question_df["CleanScore"].diff().std()
        future_trend = slope * future_years + intercept
        if pd.isna(sigma):
            future = pd.DataFrame(
                {
                    "year": future_years,
                    "trend": future_trend,
                    "median": np.nan,
                    "p25": np.nan,
                    "p75": np.nan,
                    "p05": np.nan,
                    "p95": np.nan,
                    "CleanScore": np.nan,
                    "domain": question,
                    "Question": question,
                    "type": "future",
                }
            )
            outputs.append(future)
            outputs.append(historical)
            continue

        future = monte_carlo_simulation(
            years=future_years,
            trend=future_trend,
            sigma=float(sigma),
            n_sim=1000,
            seed=stable_seed(str(question)),
        )
        future["CleanScore"] = np.nan
        future["domain"] = question
        future["Question"] = question
        future["type"] = "future"

        outputs.append(future)
        outputs.append(historical)

    output = pd.concat(outputs, ignore_index=True, sort=False)
    output = output[
        [
            "year",
            "trend",
            "median",
            "p25",
            "p75",
            "p05",
            "p95",
            "CleanScore",
            "domain",
            "Question",
            "type",
        ]
    ].sort_values(["Question", "type", "year"], ascending=[True, True, True])
    return output


def add_score_bands(ax: plt.Axes) -> None:
    bands = [
        (80, 100, "#FFFFFF", "very high"),
        (60, 80, "#F5F5F5", "high"),
        (40, 60, "#E6E6E6", "moderate"),
        (20, 40, "#CFCFCF", "low"),
        (0, 20, "#A6A6A6", "very low"),
    ]
    for low, high, color, label in bands:
        ax.axhspan(low, high, facecolor=color, alpha=1.0, zorder=0)
        ax.text(
            -0.0175,
            (low + high) / 2,
            label,
            transform=ax.get_yaxis_transform(),
            va="center",
            ha="right",
            fontsize=7.2,
            color="black",
            zorder=1,
            clip_on=False,
        )


def add_vertical_markers(ax: plt.Axes) -> None:
    markers = [
        (2020.0, "COVID start", "--"),
        (2022.0, "COVID end", "--"),
        (2024.0, "Govt cuts", "--"),
       
    ]
    for x, label, linestyle in markers:
        ax.axvline(x=x, linestyle=linestyle, color="grey", linewidth=1.2, zorder=2)
        ax.text(
            x,
            100.8,
            label,
            ha="center",
            va="bottom",
            fontsize=7,
            color="dimgray",
            clip_on=False,
        )


def safe_slug(value: str) -> str:
    return (
        value.lower()
        .replace("&", "and")
        .replace("/", "_")
        .replace(" ", "_")
        .replace("__", "_")
    )


def stable_seed(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def wrapped_label(value: str, width: int = 28) -> str:
    return "\n".join(wrap(value.replace("_", " "), width=width))


def single_line_label(value: str) -> str:
    return str(value).replace("_", " ")


def indicator_color(question: str, fallback: str) -> str:
    return INDICATOR_COLOR_OVERRIDES.get(str(question), fallback)


def is_voting_question(question: str) -> bool:
    text = str(question).lower()
    return text.startswith("vote_") or text.startswith("voted_")


def smoothstep(progress: float) -> float:
    progress = float(np.clip(progress, 0, 1))
    return progress * progress * (3 - 2 * progress)


def calculate_acorn_scenario(bau_output: pd.DataFrame) -> pd.DataFrame:
    question_df = bau_output[bau_output["level"] == "question"].copy()
    scenario_rows: list[pd.DataFrame] = []

    for question, question_data in question_df.groupby("Question", sort=False):
        question_data = question_data.sort_values("year").copy()
        anchor_rows = question_data[question_data["year"] == ACORN_START_YEAR]
        if anchor_rows.empty:
            continue
        anchor = float(anchor_rows["display_score"].iloc[0])
        triggered = anchor < ACORN_TRIGGER_SCORE
        target = ACORN_TARGET_SCORE if triggered else anchor

        acorn_scores = []
        for _, row in question_data.iterrows():
            year = int(row["year"])
            bau_score = float(row["display_score"])
            if year < ACORN_START_YEAR:
                acorn_score = bau_score
            elif not triggered:
                acorn_score = bau_score
            elif year <= ACORN_TARGET_YEAR:
                progress = (year - ACORN_START_YEAR) / (
                    ACORN_TARGET_YEAR - ACORN_START_YEAR
                )
                acorn_score = anchor + (target - anchor) * smoothstep(progress)
            else:
                acorn_score = target
            acorn_scores.append(float(np.clip(acorn_score, 0, 100)))

        question_data["scenario"] = "ACoRN"
        question_data["bau_score"] = question_data["display_score"]
        question_data["acorn_score"] = acorn_scores
        question_data["acorn_uplift"] = (
            question_data["acorn_score"] - question_data["bau_score"]
        )
        question_data["acorn_triggered"] = triggered
        scenario_rows.append(question_data)

    question_acorn = pd.concat(scenario_rows, ignore_index=True)
    area_acorn = (
        question_acorn.groupby(["group", "year"])
        .agg(
            bau_score=("bau_score", "mean"),
            acorn_score=("acorn_score", "mean"),
            acorn_uplift=("acorn_uplift", "mean"),
            triggered_questions=("acorn_triggered", "sum"),
            resilience_description=("resilience_description", "first"),
            area_color_key=("area_color_key", "first"),
            source=("source", "first"),
        )
        .reset_index()
    )
    area_acorn["level"] = "area"
    area_acorn["scenario"] = "ACoRN"
    area_acorn["Question"] = ""
    question_acorn["triggered_questions"] = question_acorn["acorn_triggered"].astype(int)
    return pd.concat([area_acorn, question_acorn], ignore_index=True, sort=False)


#Change the ACoRN period and text (IvI)

def add_acorn_period(ax: plt.Axes) -> None:
    # --- ACoRN start line ---
    ax.axvline(
        x=2027.6,
        linestyle=":",
        linewidth=1.8,
        color="grey",
        zorder=2
    )
    ax.text(
        2027.6,
        ax.get_ylim()[1] + 1,   # slightly above the top of the chart
        "ACoRN start",
        ha="center",
        va="bottom",
        fontsize=7,
        color="grey",
        rotation=0              # <-- horizontal text
    )

    # --- ACoRN end line ---
    ax.axvline(
        x=2029.0,
        linestyle=":",
        linewidth=1.8,
        color="grey",
        zorder=2
    )
    ax.text(
        2029.0,
        ax.get_ylim()[1] + 1,
        "ACoRN end",
        ha="center",
        va="bottom",
        fontsize=7,
        color="grey",
        rotation=0              # <-- horizontal text
    )

# Add P2G period
def add_p2g_period(ax: plt.Axes) -> None:
    # --- P2G start line ---
    ax.axvline(
        x=2030.0,
        linestyle=":",
        linewidth=1.8,
        color="grey",
        zorder=2
    )
    ax.text(
        2030.0,
        ax.get_ylim()[1] + 1,   # slightly above the chart
        "P2G start",
        ha="center",
        va="bottom",
        fontsize=7,
        color="grey",
        rotation=0
    )

    # --- P2G end line ---
    ax.axvline(
        x=2033.12,
        linestyle=":",
        linewidth=1.8,
        color="grey",
        zorder=2
    )
    ax.text(
        2033.12,
        ax.get_ylim()[1] + 1,
        "P2G end",
        ha="center",
        va="bottom",
        fontsize=7,
        color="grey",
        rotation=0
    )




def add_area_legend(ax: plt.Axes, area_keys: list[str], fontsize: int = 7) -> None:
    area_handles = [
        plt.Line2D(
            [0],
            [0],
            color=OVERVIEW_COLOR_MAP.get(area_key, "dimgray"),
            marker="o",
            linestyle="None",
            markersize=7,
            label=area_key,
        )
        for area_key in area_keys
    ]
    ax.legend(
        handles=area_handles,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
        ncol=len(area_handles),
        fontsize=fontsize,
        handlelength=0,
        handletextpad=0.75,
        columnspacing=1.8,
    )


def add_bottom_dot_legend(
    ax: plt.Axes,
    labels: list[str],
    colors: list[str],
    ncol: int | None = None,
    fontsize: int = 8,
) -> None:
    handles = [
        plt.Line2D(
            [0],
            [0],
            color=color,
            marker="o",
            linestyle="None",
            markersize=6,
            label=label,
        )
        for label, color in zip(labels, colors)
    ]
    if ncol is None:
        ncol = min(len(handles), 6)
    ax.legend(
        handles=handles,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
        ncol=ncol,
        fontsize=fontsize,
        handlelength=0,
        handletextpad=0.75,
        columnspacing=1.6,
    )


def plot_acorn_area_example(
    bau_output: pd.DataFrame,
    output_dir: Path = OUTPUT_CHART_DIR / "ACoRN",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    acorn_area = calculate_acorn_scenario(bau_output)
    acorn_area = acorn_area[acorn_area["level"] == "area"].copy()
    acorn_area["group"] = pd.Categorical(
        acorn_area["group"], OVERVIEW_GROUP_ORDER, ordered=True
    )
    acorn_area = acorn_area.sort_values(["group", "year"])

    fig, ax = plt.subplots(figsize=FIGSIZE)
    prepare_axes(ax, "")
    add_acorn_period(ax)

    for group_name, area_df in acorn_area.groupby("group", observed=True):
        color = OVERVIEW_COLOR_MAP.get(str(group_name), "dimgray")
        bau_before = area_df[area_df["year"] <= ACORN_START_YEAR]
        ax.plot(
            bau_before["year"],
            bau_before["bau_score"],
            color=color,
            linewidth=2.0,
            linestyle="-",
            alpha=1.0,
        )
        bau_after = area_df[area_df["year"] >= ACORN_START_YEAR]
        ax.plot(
            bau_after["year"],
            bau_after["bau_score"],
            color=color,
            linewidth=1.3,
            linestyle="-",
            alpha=0.28,
        )
        acorn_segment = area_df[area_df["year"] >= ACORN_START_YEAR]
        ax.plot(
            acorn_segment["year"],
            acorn_segment["acorn_score"],
            color=color,
            linewidth=2.5,
            linestyle=":",
        )
    add_area_legend(ax, OVERVIEW_GROUP_ORDER)
    fig.subplots_adjust(**SUBPLOT_ADJUST)
    path = output_dir / "ACoRN_example_display_group_trends_2019_2035.png"
    fig.savefig(path, dpi=DPI)
    plt.close(fig)

    OUTPUT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    acorn_area.to_csv(OUTPUT_DATA_DIR / "ACoRN_area_example_output.csv", index=False)
    return path


def plot_acorn_graphs(
    acorn_output: pd.DataFrame,
    output_dir: Path = OUTPUT_CHART_DIR / "ACoRN",
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_chart in output_dir.glob("*.png"):
        old_chart.unlink()
    chart_paths: list[Path] = []

    acorn_area = acorn_output[acorn_output["level"] == "area"].copy()
    acorn_area["group"] = pd.Categorical(
        acorn_area["group"], OVERVIEW_GROUP_ORDER, ordered=True
    )
    acorn_area = acorn_area.sort_values(["group", "year"])

    fig, ax = plt.subplots(figsize=FIGSIZE)
    prepare_axes(ax, "")
    add_acorn_period(ax)
    for group_name, area_df in acorn_area.groupby("group", observed=True):
        color = OVERVIEW_COLOR_MAP.get(str(group_name), "dimgray")
        bau_before = area_df[area_df["year"] <= ACORN_START_YEAR]
        ax.plot(
            bau_before["year"],
            bau_before["bau_score"],
            color=color,
            linewidth=2.0,
            linestyle="-",
            alpha=1.0,
        )
        bau_after = area_df[area_df["year"] >= ACORN_START_YEAR]
        ax.plot(
            bau_after["year"],
            bau_after["bau_score"],
            color=color,
            linewidth=1.3,
            linestyle="-",
            alpha=0.28,
        )
        acorn_segment = area_df[area_df["year"] >= ACORN_START_YEAR]
        ax.plot(
            acorn_segment["year"],
            acorn_segment["acorn_score"],
            color=color,
            linewidth=2.5,
            linestyle=":",
        )
    add_area_legend(ax, OVERVIEW_GROUP_ORDER)
    fig.subplots_adjust(**SUBPLOT_ADJUST)
    path = output_dir / "ACoRN_display_group_trends_2019_2035.png"
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    chart_paths.append(path)

    question_df = acorn_output[acorn_output["level"] == "question"].copy()
    question_df = question_df[~question_df["Question"].map(is_voting_question)].copy()
    for group_name in GROUP_ORDER:
        group_questions = question_df[question_df["group"] == group_name].copy()
        if group_questions.empty:
            continue
        color_key = str(group_questions["area_color_key"].iloc[0])
        questions = sorted(group_questions["Question"].unique())
        fig, ax = plt.subplots(figsize=FIGSIZE)
        prepare_axes(ax, "")
        add_acorn_period(ax)
        for idx, question in enumerate(questions):
            q_df = group_questions[group_questions["Question"] == question].sort_values(
                "year"
            )
            color = INDICATOR_PALETTE[idx % len(INDICATOR_PALETTE)]
            if len(questions) == 1:
                color = COLOR_MAP.get(color_key, "dimgray")
            color = indicator_color(question, color)
            bau_before = q_df[q_df["year"] <= ACORN_START_YEAR]
            ax.plot(
                bau_before["year"],
                bau_before["bau_score"],
                color=color,
                linewidth=1.5,
                linestyle="-",
                alpha=1.0,
                label=wrapped_label(question),
            )
            bau_after = q_df[q_df["year"] >= ACORN_START_YEAR]
            ax.plot(
                bau_after["year"],
                bau_after["bau_score"],
                color=color,
                linewidth=1.0,
                linestyle="-",
                alpha=0.28,
            )
            acorn_segment = q_df[q_df["year"] >= ACORN_START_YEAR]
            ax.plot(
                acorn_segment["year"],
                acorn_segment["acorn_score"],
                color=color,
                linewidth=2.0,
                linestyle=":",
            )
        legend_colors = [
            indicator_color(
                question,
                INDICATOR_PALETTE[idx % len(INDICATOR_PALETTE)],
            )
            for idx, question in enumerate(questions)
        ]
        add_bottom_dot_legend(
            ax,
            [single_line_label(question) for question in questions],
            legend_colors,
            ncol=len(questions),
            fontsize=7,
        )
        fig.subplots_adjust(**SUBPLOT_ADJUST)
        path = (
            output_dir
            / f"ACoRN_{safe_slug(group_name)}_indicator_trends_2019_2035.png"
        )
        fig.savefig(path, dpi=DPI)
        plt.close(fig)
        chart_paths.append(path)

    return chart_paths


def p2g_indicator_lookup(p2g_indicators: pd.DataFrame) -> dict[str, dict[str, float]]:
    indicators = p2g_indicators.copy()
    return {
        str(row["Question"]): {
            "construction": float(row["2030 - 2033"]),
            "after": float(row["After 2033"]),
        }
        for _, row in indicators.iterrows()
    }

 
def p2g_impact_for_year(year: int, construction_impact: float, after_impact: float) -> float:
    if year < P2G_START_YEAR:
        return 0.0
    if year <= P2G_CONSTRUCTION_END_YEAR:
        progress = (year - P2G_START_YEAR) / (
            P2G_CONSTRUCTION_END_YEAR - P2G_START_YEAR
        )
        return construction_impact * smoothstep(progress)

    transition_end = PROJECTION_END_YEAR
    if transition_end == P2G_CONSTRUCTION_END_YEAR + 1:
        return after_impact
    progress = (year - P2G_CONSTRUCTION_END_YEAR) / (
        transition_end - P2G_CONSTRUCTION_END_YEAR
    )
    return construction_impact + (after_impact - construction_impact) * smoothstep(
        progress
    )


def calculate_p2g_scenario(
    acorn_output: pd.DataFrame, p2g_indicators: pd.DataFrame
) -> pd.DataFrame:
    assumptions = p2g_indicator_lookup(p2g_indicators)

    question_df = acorn_output[acorn_output["level"] == "question"].copy()
    impacts = []
    periods = []
    for _, row in question_df.iterrows():
        question = str(row["Question"])
        year = int(row["year"])
        assumption = assumptions.get(question, {"construction": 0.0, "after": 0.0})
        impact = p2g_impact_for_year(
            year, assumption["construction"], assumption["after"]
        )
        impacts.append(impact)
        if year < P2G_START_YEAR:
            periods.append("pre_p2g")
        elif year <= P2G_CONSTRUCTION_END_YEAR:
            periods.append("2030_2033")
        else:
            periods.append("after_2033")

    question_df["scenario"] = "P2G"
    question_df["p2g_construction_assumption"] = question_df["Question"].map(
        lambda question: assumptions.get(str(question), {}).get("construction", 0.0)
    )
    question_df["p2g_after_assumption"] = question_df["Question"].map(
        lambda question: assumptions.get(str(question), {}).get("after", 0.0)
    )
    question_df["p2g_impact"] = impacts
    question_df["p2g_period"] = periods
    question_df["p2g_score"] = (
        question_df["acorn_score"] + question_df["p2g_impact"]
    ).clip(0, 100)

    area_p2g = (
        question_df.groupby(["group", "year"])
        .agg(
            bau_score=("bau_score", "mean"),
            acorn_score=("acorn_score", "mean"),
            p2g_score=("p2g_score", "mean"),
            p2g_impact=("p2g_impact", "mean"),
            p2g_construction_assumption=("p2g_construction_assumption", "mean"),
            p2g_after_assumption=("p2g_after_assumption", "mean"),
            resilience_description=("resilience_description", "first"),
            area_color_key=("area_color_key", "first"),
            source=("source", "first"),
        )
        .reset_index()
    )
    area_p2g["level"] = "area"
    area_p2g["scenario"] = "P2G"
    area_p2g["Question"] = ""
    area_p2g["p2g_period"] = np.where(
        area_p2g["year"] < P2G_START_YEAR,
        "pre_p2g",
        np.where(area_p2g["year"] <= P2G_CONSTRUCTION_END_YEAR, "2030_2033", "after_2033"),
    )

    return pd.concat([area_p2g, question_df], ignore_index=True, sort=False)

# added the p2g based on bau data/scenario
def calculate_p2g_bau_scenario(
    bau_output: pd.DataFrame, p2g_indicators: pd.DataFrame
) -> pd.DataFrame:

    assumptions = p2g_indicator_lookup(p2g_indicators)

    # ------------------------------------------------------------
    # QUESTION LEVEL
    # ------------------------------------------------------------
    question_df = bau_output[bau_output["level"] == "question"].copy()

    # ⭐ FIX: BAU baseline = display_score
    question_df["bau_score"] = question_df["display_score"]

    impacts = []
    periods = []

    for _, row in question_df.iterrows():
        question = str(row["Question"])
        year = int(row["year"])

        assumption = assumptions.get(question, {"construction": 0.0, "after": 0.0})

        # ⭐ Use your existing uplift function
        impact = p2g_impact_for_year(
            year,
            assumption["construction"],
            assumption["after"]
        )
        impacts.append(impact)

        if year < P2G_START_YEAR:
            periods.append("pre_p2g")
        elif year <= P2G_CONSTRUCTION_END_YEAR:
            periods.append("2030_2033")
        else:
            periods.append("after_2033")

    question_df["scenario"] = "P2G_BAU"
    question_df["p2g_construction_assumption"] = question_df["Question"].map(
        lambda q: assumptions.get(str(q), {}).get("construction", 0.0)
    )
    question_df["p2g_after_assumption"] = question_df["Question"].map(
        lambda q: assumptions.get(str(q), {}).get("after", 0.0)
    )
    question_df["p2g_impact"] = impacts
    question_df["p2g_period"] = periods

    # ⭐ Uplift applied to BAU baseline
    question_df["p2g_score"] = (
        question_df["bau_score"] + question_df["p2g_impact"]
    ).clip(0, 100)

    # ------------------------------------------------------------
    # AREA LEVEL (same structure as P2G)
    # ------------------------------------------------------------
    area_p2g = (
        question_df.groupby(["group", "year"])
        .agg(
            bau_score=("bau_score", "mean"),
            p2g_score=("p2g_score", "mean"),
            p2g_impact=("p2g_impact", "mean"),
            p2g_construction_assumption=("p2g_construction_assumption", "mean"),
            p2g_after_assumption=("p2g_after_assumption", "mean"),
            resilience_description=("resilience_description", "first"),
            area_color_key=("area_color_key", "first"),
            source=("source", "first"),
        )
        .reset_index()
    )

    area_p2g["level"] = "area"
    area_p2g["scenario"] = "P2G_BAU"
    area_p2g["Question"] = ""
    area_p2g["p2g_period"] = np.where(
        area_p2g["year"] < P2G_START_YEAR,
        "pre_p2g",
        np.where(
            area_p2g["year"] <= P2G_CONSTRUCTION_END_YEAR,
            "2030_2033",
            "after_2033",
        ),
    )

    return pd.concat([area_p2g, question_df], ignore_index=True, sort=False)

def plot_p2g_graphs(
    p2g_output: pd.DataFrame,
    output_dir: Path = OUTPUT_CHART_DIR / "P2G",
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_chart in output_dir.glob("*.png"):
        old_chart.unlink()
    chart_paths: list[Path] = []

    p2g_area = p2g_output[p2g_output["level"] == "area"].copy()
    p2g_area["group"] = pd.Categorical(
        p2g_area["group"], OVERVIEW_GROUP_ORDER, ordered=True
    )
    p2g_area = p2g_area.sort_values(["group", "year"])

    fig, ax = plt.subplots(figsize=FIGSIZE)
    prepare_axes(ax, "")
    add_acorn_period(ax)
    for group_name, area_df in p2g_area.groupby("group", observed=True):
        color = OVERVIEW_COLOR_MAP.get(str(group_name), "dimgray")
        bau_before = area_df[area_df["year"] <= ACORN_START_YEAR]
        ax.plot(
            bau_before["year"],
            bau_before["bau_score"],
            color=color,
            linewidth=1.7,
            linestyle="-",
            alpha=1.0,
        )
        bau_after = area_df[area_df["year"] >= ACORN_START_YEAR]
        ax.plot(
            bau_after["year"],
            bau_after["bau_score"],
            color=color,
            linewidth=1.0,
            linestyle="-",
            alpha=0.22,
        )
        acorn_before = area_df[
            area_df["year"].between(ACORN_START_YEAR, P2G_LINE_START_YEAR)
        ]
        ax.plot(
            acorn_before["year"],
            acorn_before["acorn_score"],
            color=color,
            linewidth=2.0,
            linestyle="-",
            alpha=1.0,
        )
        acorn_after = area_df[area_df["year"] >= P2G_LINE_START_YEAR]
        ax.plot(
            acorn_after["year"],
            acorn_after["acorn_score"],
            color=color,
            linewidth=1.3,
            linestyle="-",
            alpha=0.45,
        )
        p2g_segment = area_df[area_df["year"] >= P2G_LINE_START_YEAR]
        ax.plot(
            p2g_segment["year"],
            p2g_segment["p2g_score"],
            color=color,
            linewidth=2.8,
            linestyle=":",
            alpha=1.0,
            zorder=5,
        )
    add_area_legend(ax, OVERVIEW_GROUP_ORDER)
    fig.subplots_adjust(**SUBPLOT_ADJUST)
    path = output_dir / "P2G_display_group_trends_2019_2035.png"
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    chart_paths.append(path)

    question_df = p2g_output[p2g_output["level"] == "question"].copy()
    question_df = question_df[~question_df["Question"].map(is_voting_question)].copy()
    for group_name in GROUP_ORDER:
        group_questions = question_df[question_df["group"] == group_name].copy()
        if group_questions.empty:
            continue
        color_key = str(group_questions["area_color_key"].iloc[0])
        questions = sorted(group_questions["Question"].unique())
        fig, ax = plt.subplots(figsize=FIGSIZE)
        prepare_axes(ax, "")
        add_acorn_period(ax)
        add_p2g_period(ax) # added the p2g period (IvI)
        for idx, question in enumerate(questions):
            q_df = group_questions[group_questions["Question"] == question].sort_values(
                "year"
            )
            color = INDICATOR_PALETTE[idx % len(INDICATOR_PALETTE)]
            if len(questions) == 1:
                color = COLOR_MAP.get(color_key, "dimgray")
            color = indicator_color(question, color)
            bau_before = q_df[q_df["year"] <= ACORN_START_YEAR]
            ax.plot(
                bau_before["year"],
                bau_before["bau_score"],
                color=color,
                linewidth=1.3,
                linestyle="-",
                alpha=1.0,
                label=wrapped_label(question),
            )
            bau_after = q_df[q_df["year"] >= ACORN_START_YEAR]
            ax.plot(
                bau_after["year"],
                bau_after["bau_score"],
                color=color,
                linewidth=0.9,
                linestyle="-",
                alpha=0.22,
            )
            acorn_before = q_df[
                q_df["year"].between(ACORN_START_YEAR, P2G_LINE_START_YEAR)
            ]
            ax.plot(
                acorn_before["year"],
                acorn_before["acorn_score"],
                color=color,
                linewidth=1.7,
                linestyle="-",
                alpha=1.0,
            )
            acorn_after = q_df[q_df["year"] >= P2G_LINE_START_YEAR]
            ax.plot(
                acorn_after["year"],
                acorn_after["acorn_score"],
                color=color,
                linewidth=1.1,
                linestyle="-",
                alpha=0.45,
            )
            p2g_segment = q_df[q_df["year"] >= P2G_LINE_START_YEAR]
            ax.plot(
                p2g_segment["year"],
                p2g_segment["p2g_score"],
                color=color,
                linewidth=2.4,
                linestyle=":",
                alpha=1.0,
                zorder=5,
            )
        legend_colors = [
            indicator_color(
                question,
                INDICATOR_PALETTE[idx % len(INDICATOR_PALETTE)],
            )
            for idx, question in enumerate(questions)
        ]
        add_bottom_dot_legend(
            ax,
            [single_line_label(question) for question in questions],
            legend_colors,
            ncol=len(questions),
            fontsize=7,
        )
        fig.subplots_adjust(**SUBPLOT_ADJUST)
        path = output_dir / f"P2G_{safe_slug(group_name)}_indicator_trends_2019_2035.png"
        fig.savefig(path, dpi=DPI)
        plt.close(fig)
        chart_paths.append(path)

    return chart_paths

# added the 4th scenario p2g based on bau (IvI)
def plot_p2g_bau_graphs(
    p2g_output: pd.DataFrame,
    output_dir: Path = OUTPUT_CHART_DIR / "P2G-BAU",
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_chart in output_dir.glob("*.png"):
        old_chart.unlink()
    chart_paths: list[Path] = []

    p2g_area = p2g_output[p2g_output["level"] == "area"].copy()
    p2g_area["group"] = pd.Categorical(
        p2g_area["group"],
        [g for g in OVERVIEW_GROUP_ORDER if g in p2g_area["group"].unique()],
        ordered=True,
    )
    p2g_area = p2g_area.sort_values(["group", "year"])

    fig, ax = plt.subplots(figsize=FIGSIZE)
    prepare_axes(ax, "")
    add_p2g_period(ax)

    for group_name, area_df in p2g_area.groupby("group", observed=True):
        color = OVERVIEW_COLOR_MAP.get(str(group_name), "dimgray")

        ax.plot(
            area_df["year"],
            area_df["bau_score"],
            color=color,
            linewidth=1.7,
            linestyle="-",
            alpha=1.0,
        )
        p2g_segment = area_df[area_df["year"] >= P2G_LINE_START_YEAR]
        ax.plot(
            p2g_segment["year"],
            p2g_segment["p2g_score"],
            color=color,
            linewidth=2.8,
            linestyle=":",
            alpha=1.0,
            zorder=5,
        )

    add_area_legend(ax, [g for g in OVERVIEW_GROUP_ORDER if g in p2g_area["group"].unique()])
    fig.subplots_adjust(**SUBPLOT_ADJUST)
    path = output_dir / "P2G_BAU_display_group_trends_2019_2035.png"
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    chart_paths.append(path)

    question_df = p2g_output[p2g_output["level"] == "question"].copy()
    question_df = question_df[~question_df["Question"].map(is_voting_question)].copy()

    for group_name in GROUP_ORDER:
        group_questions = question_df[question_df["group"] == group_name].copy()
        if group_questions.empty:
            continue

        questions = sorted(group_questions["Question"].unique())
        fig, ax = plt.subplots(figsize=FIGSIZE)
        prepare_axes(ax, "")
        add_p2g_period(ax)

        for idx, question in enumerate(questions):
            q_df = group_questions[group_questions["Question"] == question].sort_values("year")
            color = indicator_color(question, INDICATOR_PALETTE[idx % len(INDICATOR_PALETTE)])

            ax.plot(
                q_df["year"],
                q_df["bau_score"],
                color=color,
                linewidth=1.5,
                linestyle="-",
                alpha=1.0,
                label=wrapped_label(question),
            )
            p2g_segment = q_df[q_df["year"] >= P2G_LINE_START_YEAR]
            ax.plot(
                p2g_segment["year"],
                p2g_segment["p2g_score"],
                color=color,
                linewidth=2.4,
                linestyle=":",
                alpha=1.0,
                zorder=5,
            )

        legend_colors = [
            indicator_color(question, INDICATOR_PALETTE[idx % len(INDICATOR_PALETTE)])
            for idx, question in enumerate(questions)
        ]
        add_bottom_dot_legend(
            ax,
            [single_line_label(question) for question in questions],
            legend_colors,
            ncol=len(questions),
            fontsize=7,
        )

        fig.subplots_adjust(**SUBPLOT_ADJUST)
        path = output_dir / f"P2G_BAU_{safe_slug(group_name)}_indicator_trends_2019_2035.png"
        fig.savefig(path, dpi=DPI)
        plt.close(fig)
        chart_paths.append(path)

    return chart_paths

def prepare_axes(ax: plt.Axes, title: str) -> None:
    add_score_bands(ax)
    add_vertical_markers(ax)
    ax.set_xlim(2018.8, 2035.2)
    ax.set_ylim(0, 100)
    ax.set_xticks(range(2019, 2036, 1))
    ax.set_yticks(range(0, 101, 20))
    ax.set_xlabel("Year")
    ax.set_ylabel("")
    ax.grid(True, axis="y", alpha=0.25, color="white")

#for group_name, area_df in p2g_area.groupby("group", observed=True):
#    color_key = str(area_df["area_color_key"].iloc[0]).lower()
#    color = COLOR_MAP.get(color_key, "dimgray")

def plot_trend_graph(
    bau_output: pd.DataFrame,
    output_dir: Path = OUTPUT_CHART_DIR / "BAU",
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_chart in output_dir.glob("*.png"):
        old_chart.unlink()
    chart_paths: list[Path] = []

    question_df = bau_output[bau_output["level"] == "question"].copy()
    area_overview = (
        question_df.groupby(["group", "year"])
        .agg(
            display_score=("display_score", "mean"),
            resilience_description=("resilience_description", "first"),
            area_color_key=("area_color_key", "first"),
        )
        .reset_index()
    )
    area_overview["group"] = pd.Categorical(
        area_overview["group"], OVERVIEW_GROUP_ORDER, ordered=True
    )
    area_overview = area_overview.sort_values(["group", "year"])

    fig, ax = plt.subplots(figsize=FIGSIZE)
    prepare_axes(
        ax,
        "Newlands Resilience Group - Six resilience area trends to 2035 based on historic annual data from 2019",
    )
    for group_name, group_df in area_overview.groupby("group", observed=True):
        ax.plot(
            group_df["year"],
            group_df["display_score"],
            color=OVERVIEW_COLOR_MAP.get(str(group_name), "dimgray"),
            linewidth=2.4,
        )
    add_area_legend(ax, OVERVIEW_GROUP_ORDER)
    fig.subplots_adjust(**SUBPLOT_ADJUST)
    path = output_dir / "BAU_display_group_trends_2019_2035.png"
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    chart_paths.append(path)

    question_df = question_df[~question_df["Question"].map(is_voting_question)].copy()
    for group_name in GROUP_ORDER:
        group_questions = question_df[question_df["group"] == group_name].copy()
        if group_questions.empty:
            continue
        color_key = str(group_questions["area_color_key"].iloc[0])
        questions = sorted(group_questions["Question"].unique())
        fig, ax = plt.subplots(figsize=FIGSIZE)
        prepare_axes(
            ax,
            f"Newlands Resilience Group - {group_name} indicator BAU trends to 2035",
        )
        for idx, question in enumerate(questions):
            q_df = group_questions[group_questions["Question"] == question].sort_values(
                "year"
            )
            color = INDICATOR_PALETTE[idx % len(INDICATOR_PALETTE)]
            if len(questions) == 1:
                color = COLOR_MAP.get(color_key, "dimgray")
            color = indicator_color(question, color)
            ax.plot(
                q_df["year"],
                q_df["display_score"],
                color=color,
                linewidth=1.8,
                label=wrapped_label(question),
            )
        legend_colors = [
            indicator_color(
                question,
                INDICATOR_PALETTE[idx % len(INDICATOR_PALETTE)],
            )
            for idx, question in enumerate(questions)
        ]
        add_bottom_dot_legend(
            ax,
            [single_line_label(question) for question in questions],
            legend_colors,
            ncol=len(questions),
            fontsize=7,
        )
        fig.subplots_adjust(**SUBPLOT_ADJUST)
        path = output_dir / f"BAU_{safe_slug(group_name)}_indicator_trends_2019_2035.png"
        fig.savefig(path, dpi=DPI)
        plt.close(fig)
        chart_paths.append(path)

    return chart_paths


def export_outputs(
    bau_output: pd.DataFrame,
    bau_projection_per_question: pd.DataFrame,
    p2g_indicators: pd.DataFrame,
):
    OUTPUT_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # BAU
    data_path = OUTPUT_DATA_DIR / "BAU_output.csv"
    
    bau_output.to_csv(data_path, index=False)

    legacy_data_path = OUTPUT_DATA_DIR / "BAU_projection_per_question.csv"
    bau_projection_per_question.to_csv(legacy_data_path, index=False)

    # ACoRN
    acorn_output = calculate_acorn_scenario(bau_output)
    acorn_data_path = OUTPUT_DATA_DIR / "ACoRN_output.csv"
    acorn_output.to_csv(acorn_data_path, index=False)

    # P2G (ACoRN-based)
    p2g_output = calculate_p2g_scenario(acorn_output, p2g_indicators)
    p2g_data_path = OUTPUT_DATA_DIR / "P2G_output.csv"
    p2g_output.to_csv(p2g_data_path, index=False)

    # Add missing structural columns required by scenario functions
    bau_projection_per_question["group"] = bau_projection_per_question["domain"]
    bau_projection_per_question["resilience_description"] = bau_projection_per_question["domain"]
    bau_projection_per_question["area_color_key"] = bau_projection_per_question["domain"]
    bau_projection_per_question["level"] = "question"
    
    # ⭐ FIX: Add BAU baseline column for P2G_BAU
    bau_projection_per_question["bau_score"] = bau_projection_per_question["CleanScore"]

    # P2G_BAU (BAU-based)
    p2g_bau_output = calculate_p2g_bau_scenario(bau_output, p2g_indicators)
    p2g_bau_data_path = OUTPUT_DATA_DIR / "P2G_bau_output.csv"
    p2g_bau_output.to_csv(p2g_bau_data_path, index=False)

    # Charts
    bau_chart_paths = plot_trend_graph(bau_output)
    acorn_chart_paths = plot_acorn_graphs(acorn_output)
    p2g_chart_paths = plot_p2g_graphs(p2g_output)
    p2g_bau_chart_paths = plot_p2g_bau_graphs(p2g_bau_output)

    return (
        data_path,
        legacy_data_path,
        acorn_data_path,
        p2g_data_path,
        bau_chart_paths,
        acorn_chart_paths,
        p2g_chart_paths,
        p2g_bau_chart_paths
    )
    # return (
    #     data_path,
    #     legacy_data_path,
    #     acorn_data_path,
    #     p2g_data_path,
    #     bau_chart_paths,
    #     acorn_chart_paths,
    #     p2g_chart_paths,
    # )


def main() -> None:
    data = load_data()
    cleaned = clean_data(data)
    bau_output = calculate_bau_trend(cleaned)
    bau_projection_per_question = calculate_bau_projection_per_question(cleaned)
    (
        data_path,
        legacy_data_path,
        acorn_data_path,
        p2g_data_path,
        bau_chart_paths,
        acorn_chart_paths,
        p2g_chart_paths,
        p2g_bau_chart_paths # add for 4th scenario (IvI)
    ) = export_outputs(
        bau_output,
        bau_projection_per_question,
        data["p2g_indicators"],
    )

    print(f"Generated data: {data_path.relative_to(ROOT_DIR)}")
    print(f"Generated team-format BAU data: {legacy_data_path.relative_to(ROOT_DIR)}")
    print(f"Generated ACoRN data: {acorn_data_path.relative_to(ROOT_DIR)}")
    print(f"Generated P2G data: {p2g_data_path.relative_to(ROOT_DIR)}")
    print("Generated BAU charts:")
    for path in bau_chart_paths:
        print(f"- {path.relative_to(ROOT_DIR)}")
    print("Generated ACoRN charts:")
    for path in acorn_chart_paths:
        print(f"- {path.relative_to(ROOT_DIR)}")
    print("Generated P2G charts:")
    for path in p2g_chart_paths:
        print(f"- {path.relative_to(ROOT_DIR)}")
    # Added for 4th scenario (Iv)
    print("Generated P2G based on BAU charts:")
    for path in p2g_bau_chart_paths:
        print(f"- {path.relative_to(ROOT_DIR)}")    


if __name__ == "__main__":
    main()
