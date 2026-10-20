"""End-to-end Newlands survey cleaning, scoring, scenarios, and chart pipeline.


This module translates the supplied Power Query transformations into Python and
adds the import normalisation needed for the original 2019-2025 survey exports.
Raw input files are never modified.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xlsm"}
PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_P2G_PATH = PROJECT_DIR / "config" / "Linked indicators to P2G.csv"
DEFAULT_HISTORICAL_RAW_DIR = PROJECT_DIR / "data" / "raw"
DEFAULT_FUTURE_INPUT_DIR = PROJECT_DIR / "data" / "future"
DEFAULT_HISTORICAL_CORE_PATH = (
    PROJECT_DIR / "data" / "core" / "Newlands_historical_core_through_2025.csv"
)
HISTORICAL_CORE_MAX_YEAR = 2025

# Explicitly discarded at import. ``2025 For`` is an orphaned/truncated field
# in the supplied 2025 workbook and the project owner confirmed it should not
# be used. Raw workbooks remain untouched; the column is removed in memory.
DISCARDED_RAW_COLUMNS = {"2025 for"}
PII_COLUMNS = {
    "collector_id",
    "ip_address",
    "email_address",
    "first_name",
    "last_name",
    "contact_details",
}

ID_COLUMNS = ["date", "survey_year", "age_range", "gender", "responder_id"]

QUESTION_COLUMNS = [
    "satisfaction_income",
    "confident_in_finding_a_new_job",
    "confident_water_safety",
    "optimal_use_of_land",
    "personal_mental_health",
    "language",
    "belonging",
    "cultural_activities",
    "te_reo",
    "cultural_knowledge",
    "trust_nz_government",
    "trust_local_council",
    "trust_nz_police",
    "safety",
    "be_yourself_in_nz",
    "be_yourself_in_newlands",
    "discrimination",
    "loneliness",
    "independence",
    "support_in_crisis",
    "level_of_control",
    "volunteering_time",
    "paid_working_hours",
    "job_satisfaction",
    "work_life_balance",
    "leisure_time",
    "life_satisfaction",
    "meaning_and_purpose",
    "family_wellbeing",
    "access_to_natural_environment",
    "work_travel_time",
    "basic_life_skills",
    "newlands_resident",
    "home_disaster_ready",
    "neighbourhood_support_group",
    "out_of_newlands_during_day",
    "place_out_of_newlands_disaster_ready",
    "vote_local_elections_2019",
    "vote_general_election_2020",
    "voted_local_elections_2022",
    "voted_general_elections_2023",
    "vote_council_election_2025",
    "vote_general_election_2026",
]

BASELINE_WIDE_QUESTION_ORDER = [
    "language", "belonging", "cultural_activities", "te_reo", "cultural_knowledge",
    "trust_nz_government", "trust_local_council", "trust_nz_police", "safety",
    "discrimination", "loneliness", "independence", "support_in_crisis",
    "level_of_control", "volunteering_time", "paid_working_hours", "job_satisfaction",
    "work_life_balance", "leisure_time", "be_yourself_in_nz",
    "be_yourself_in_newlands", "life_satisfaction", "meaning_and_purpose",
    "family_wellbeing", "access_to_natural_environment", "work_travel_time",
    "basic_life_skills", "newlands_resident", "home_disaster_ready",
    "neighbourhood_support_group", "out_of_newlands_during_day",
    "place_out_of_newlands_disaster_ready", "satisfaction_income",
    "confident_in_finding_a_new_job", "confident_water_safety", "optimal_use_of_land",
    "personal_mental_health", "vote_local_elections_2019",
    "vote_general_election_2020", "voted_local_elections_2022",
    "voted_general_elections_2023",
]

# This is the exact subset counted by Number_null_values in the supplied M code.
POWER_BI_COMPLETENESS_COLUMNS = [
    "satisfaction_income",
    "confident_in_finding_a_new_job",
    "confident_water_safety",
    "optimal_use_of_land",
    "personal_mental_health",
    "language",
    "belonging",
    "cultural_activities",
    "te_reo",
    "cultural_knowledge",
    "trust_nz_government",
    "trust_local_council",
    "safety",
    "be_yourself_in_nz",
    "be_yourself_in_newlands",
    "discrimination",
    "loneliness",
    "support_in_crisis",
    "level_of_control",
    "volunteering_time",
    "job_satisfaction",
    "work_life_balance",
    "leisure_time",
    "life_satisfaction",
    "meaning_and_purpose",
    "family_wellbeing",
    "access_to_natural_environment",
    "basic_life_skills",
]

BACKFILL_QUESTIONS = [
    "satisfaction_income",
    "confident_in_finding_a_new_job",
    "confident_water_safety",
    "optimal_use_of_land",
    "personal_mental_health",
]

# Fixed three-year averages used by the existing Power BI average_questions
# lookup. Keeping these values explicit reproduces the supplied baselines and
# makes a future change to the approved assumptions auditable.
POWER_BI_BACKFILL_VALUES = {
    "satisfaction_income": 66.0,
    "confident_in_finding_a_new_job": 57.0,
    "confident_water_safety": 69.0,
    "optimal_use_of_land": 55.0,
    "personal_mental_health": 74.0,
}

BINARY_QUESTIONS = {
    "newlands_resident",
    "home_disaster_ready",
    "neighbourhood_support_group",
    "out_of_newlands_during_day",
    "place_out_of_newlands_disaster_ready",
    "vote_local_elections_2019",
    "vote_general_election_2020",
    "voted_local_elections_2022",
    "voted_general_elections_2023",
    "vote_council_election_2025",
    "vote_general_election_2026",
}

# Matches the attached Power Query. The email's reference to "democracy" needs
# business confirmation before it is added here.
REVERSED_QUESTIONS = {"loneliness", "discrimination"}

QUESTION_METADATA = {
    # Cultural
    "language": ("Cultural", "cultural", "language"),
    "belonging": ("Cultural", "cultural", "belonging"),
    "cultural_activities": ("Cultural", "cultural", "participation"),
    "te_reo": ("Cultural", "cultural", "language"),
    "cultural_knowledge": ("Cultural", "cultural", "knowledge"),
    # Governance
    "trust_nz_government": ("Governance", "governance", "trust"),
    "trust_local_council": ("Governance", "governance", "trust"),
    "trust_nz_police": ("Governance", "governance", "trust"),
    "vote_local_elections_2019": ("Governance", "governance", "voting"),
    "vote_general_election_2020": ("Governance", "governance", "voting"),
    "voted_local_elections_2022": ("Governance", "governance", "voting"),
    "voted_general_elections_2023": ("Governance", "governance", "voting"),
    "vote_council_election_2025": ("Governance", "governance", "voting"),
    "vote_general_election_2026": ("Governance", "governance", "voting"),
    # Disaster
    "home_disaster_ready": ("Disaster", "disaster", "preparedness"),
    "neighbourhood_support_group": ("Disaster", "disaster", "preparedness"),
    "out_of_newlands_during_day": ("Disaster", "disaster", "exposure"),
    "place_out_of_newlands_disaster_ready": ("Disaster", "disaster", "preparedness"),
    # Economic
    "satisfaction_income": ("Economic", "economic", "income"),
    "confident_in_finding_a_new_job": ("Economic", "economic", "employment"),
    "paid_working_hours": ("Economic", "economic", "employment"),
    "job_satisfaction": ("Economic", "economic", "employment"),
    "work_life_balance": ("Economic", "economic", "employment"),
    "work_travel_time": ("Economic", "economic", "access"),
    # Environment
    "confident_water_safety": ("Environment", "environment", "water"),
    "optimal_use_of_land": ("Environment", "environment", "land"),
    "access_to_natural_environment": ("Environment", "environment", "access"),
    # Subjective wellbeing
    "personal_mental_health": ("Subjective Wellbeing", "social", "wellbeing"),
    "life_satisfaction": ("Subjective Wellbeing", "social", "wellbeing"),
    "meaning_and_purpose": ("Subjective Wellbeing", "social", "wellbeing"),
    "family_wellbeing": ("Subjective Wellbeing", "social", "wellbeing"),
    "loneliness": ("Subjective Wellbeing", "social", "wellbeing"),
    # Other social
    "safety": ("Other Social", "social", "safety"),
    "be_yourself_in_nz": ("Other Social", "social", "identity"),
    "be_yourself_in_newlands": ("Other Social", "social", "identity"),
    "discrimination": ("Other Social", "social", "inclusion"),
    "independence": ("Other Social", "social", "agency"),
    "support_in_crisis": ("Other Social", "social", "support"),
    "level_of_control": ("Other Social", "social", "agency"),
    "volunteering_time": ("Other Social", "social", "participation"),
    "leisure_time": ("Other Social", "social", "time"),
    "basic_life_skills": ("Other Social", "social", "skills"),
    "newlands_resident": ("Other Social", "social", "residency"),
}


@dataclass
class QualityReport:
    files_loaded: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unmatched_columns: list[dict[str, str]] = field(default_factory=list)
    duplicate_rows: list[dict[str, Any]] = field(default_factory=list)
    rejected_rows: list[dict[str, Any]] = field(default_factory=list)
    backfill_values: dict[str, float] = field(default_factory=dict)
    p2g_config: dict[str, Any] = field(default_factory=dict)

    def save(self, output_dir: Path) -> None:
        report_dir = output_dir / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "quality_report.json").write_text(
            json.dumps(self.__dict__, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        pd.DataFrame(self.unmatched_columns, columns=["file", "column"]).to_csv(
            report_dir / "unmatched_columns.csv", index=False
        )
        pd.DataFrame(
            self.duplicate_rows,
            columns=["file", "source_row", "reason"],
        ).to_csv(
            report_dir / "duplicate_rows.csv", index=False
        )
        pd.DataFrame(
            self.rejected_rows,
            columns=["file", "source_row", "reason", "missing"],
        ).to_csv(
            report_dir / "rejected_rows.csv", index=False
        )


def normalise_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def blank_strings_to_nan(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.select_dtypes(include=["object"]).columns:
        result[column] = result[column].map(
            lambda value: np.nan
            if isinstance(value, str) and not value.strip()
            else value
        )
    return result


def infer_year(path: Path, frame: pd.DataFrame) -> int:
    match = re.search(r"(?:19|20)\d{2}", path.name)
    if match:
        return int(match.group())
    for candidate in ["Timestamp", "Start Date", "date"]:
        if candidate in frame:
            dates = pd.to_datetime(frame[candidate], errors="coerce", dayfirst=True)
            if dates.notna().any():
                return int(dates.dt.year.mode().iloc[0])
    raise ValueError(f"Cannot infer survey year from {path.name}")


def match_column(column: Any) -> str | None:
    c = normalise_text(column)
    if not c or c.startswith("unnamed") or c in {"score", "column1", "2025 for"}:
        return None

    exact_metadata = {
        "respondent id": "responder_id",
        "start date": "date",
        "timestamp": "date",
        "age range": "age_range",
        "2 age range": "age_range",
        "gender": "gender",
        "3 gender": "gender",
        "ip address": "ip_address",
        "email address": "email_address",
        "first name": "first_name",
        "last name": "last_name",
        "collector id": "collector_id",
    }
    if c in exact_metadata:
        return exact_metadata[c]
    if "pick the age range" in c:
        return "age_range"
    if "what is your gender" in c:
        return "gender"
    if "contact details" in c or "add your phone number" in c:
        return "contact_details"
    if "postcode" in c:
        return "postcode"

    rules: list[tuple[str, tuple[str, ...]]] = [
        # Match the year independently so both "2026 General Election" and
        # "General Election 2026" exports are accepted. Wellington's local
        # election is also described as either a local or council election.
        ("vote_general_election_2026", ("vote", "2026", "general election")),
        ("vote_council_election_2025", ("vote", "2025", "local election")),
        ("vote_council_election_2025", ("vote", "2025", "council election")),
        ("voted_general_elections_2023", ("vote", "2023 general election")),
        ("voted_local_elections_2022", ("vote", "2022 local election")),
        ("vote_general_election_2020", ("vote", "2020 general election")),
        ("vote_local_elections_2019", ("vote", "2019 local election")),
        ("satisfaction_income", ("satisfied", "income")),
        ("confident_in_finding_a_new_job", ("confident", "find", "job")),
        ("confident_water_safety", ("confident", "safety of water")),
        ("optimal_use_of_land", ("confident", "land", "optimal")),
        ("personal_mental_health", ("mental wellbeing",)),
        ("language", ("ability", "first language", "ethnic group")),
        ("belonging", ("sense of belonging",)),
        ("cultural_activities", ("cultural activities",)),
        ("te_reo", ("everyday things", "te reo")),
        ("cultural_knowledge", ("cultural knowledge",)),
        ("trust_nz_government", ("trust", "new zealand parliament")),
        ("trust_nz_government", ("trust nz government",)),
        ("trust_local_council", ("trust", "local council")),
        ("trust_nz_police", ("trust", "new zealand police")),
        ("trust_nz_police", ("trust nz police",)),
        ("safety", ("walking alone", "after dark")),
        ("discrimination", ("experienced discrimination",)),
        ("discrimination", ("disrimination",)),
        ("loneliness", ("feelings of loneliness",)),
        ("independence", ("level of independence",)),
        ("independence", ("independance",)),
        ("support_in_crisis", ("support", "times of crisis")),
        ("level_of_control", ("level of control",)),
        ("volunteering_time", ("give your time and skills",)),
        ("paid_working_hours", ("paid working hours",)),
        ("paid_working_hours", ("working hours",)),
        ("job_satisfaction", ("satisfaction", "main job")),
        ("work_life_balance", ("work life balance",)),
        ("leisure_time", ("hours in a week", "things you want to do")),
        ("be_yourself_in_nz", ("yourself in new zealand",)),
        ("be_yourself_in_newlands", ("yourself in newlands",)),
        ("be_yourself_in_newlands", ("yourself in your suburb",)),
        ("life_satisfaction", ("satisfaction", "with your life")),
        ("meaning_and_purpose", ("life worthwhile",)),
        ("family_wellbeing", ("immediate family",)),
        ("access_to_natural_environment", ("access", "natural environment")),
        ("work_travel_time", ("travel to work", "commute")),
        ("work_travel_time", ("work travel time",)),
        ("basic_life_skills", ("basic", "life skills")),
        ("home_disaster_ready", ("home prepared", "disaster")),
        ("neighbourhood_support_group", ("neighbourhood support group",)),
        ("neighbourhood_support_group", ("neigbourhood support group",)),
        ("neighbourhood_support_group", ("neighbouhood support group",)),
        ("out_of_newlands_during_day", ("out of newlands", "during day")),
        ("out_of_newlands_during_day", ("out of newlands", "during the day")),
        ("out_of_newlands_during_day", ("out of your suburb", "during the day")),
        ("place_out_of_newlands_disaster_ready", ("place you are normally in", "prepared")),
        ("newlands_resident", ("do you live in newlands",)),
        ("newlands_resident", ("do you live in either newlands",)),
        ("newlands_resident", ("do you live in", "select", "following")),
    ]
    for canonical, terms in rules:
        if all(term in c for term in terms):
            return canonical

    # Short numbered headers in the manually cleaned 2020 sheet.
    short = {
        "language": "language", "belonging": "belonging",
        "cultural activities": "cultural_activities", "te reo": "te_reo",
        "cultural knowledge": "cultural_knowledge", "safety": "safety",
        "loneliness": "loneliness", "support in crisis": "support_in_crisis",
        "level of control": "level_of_control", "volunteering time": "volunteering_time",
        "job satisfaction": "job_satisfaction", "work life balance": "work_life_balance",
        "leisure time": "leisure_time", "life satisfaction": "life_satisfaction",
        "be yourself in nz": "be_yourself_in_nz",
        "meaning and purpose": "meaning_and_purpose", "family wellbeing": "family_wellbeing",
        "basic life skills": "basic_life_skills", "newlands resident": "newlands_resident",
        "home disaster ready": "home_disaster_ready",
        "place out of newland disaster ready": "place_out_of_newlands_disaster_ready",
    }
    stripped = re.sub(r"^(q?\d+\s*)", "", c).strip()
    for label, canonical in short.items():
        if stripped == label:
            return canonical
    return None


def read_survey(path: Path) -> tuple[pd.DataFrame, str]:
    if path.suffix.lower() == ".csv":
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                frame = pd.read_csv(path, encoding=encoding, keep_default_na=False)
                return blank_strings_to_nan(frame), "CSV"
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Could not decode {path.name}")

    workbook = pd.ExcelFile(path)
    candidates: list[tuple[int, int, str, pd.DataFrame]] = []
    for sheet in workbook.sheet_names:
        frame = pd.read_excel(path, sheet_name=sheet, keep_default_na=False)
        frame = blank_strings_to_nan(frame)
        signal = sum(
            any(k in normalise_text(c) for k in ("respondent", "timestamp", "start date"))
            for c in frame.columns
        )
        candidates.append((signal, len(frame.columns), sheet, frame))
    _, _, sheet, frame = max(candidates)
    return frame, sheet


def combine_surveymonkey_option_columns(raw: pd.DataFrame) -> pd.DataFrame:
    """Combine SurveyMonkey Yes/No and multiple-choice columns.

    SurveyMonkey exports the first option under the question header and later
    options under adjacent ``Unnamed`` columns. Ignoring those adjacent columns
    loses every No response, which materially distorted the 2022 baseline.
    """
    frame = raw.copy()
    columns = list(frame.columns)
    for index, column in enumerate(columns):
        canonical = match_column(column)
        if canonical not in BINARY_QUESTIONS:
            continue
        option_columns = [column]
        cursor = index + 1
        while cursor < len(columns) and normalise_text(columns[cursor]).startswith("unnamed"):
            option_columns.append(columns[cursor])
            cursor += 1
        if len(option_columns) > 1:
            frame[column] = frame[option_columns].bfill(axis=1).iloc[:, 0]
    return frame


def combine_duplicate_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    for name in dict.fromkeys(frame.columns):
        subset = frame.loc[:, frame.columns == name]
        result[name] = subset.apply(
            lambda row: next((value for value in row if pd.notna(value)), np.nan),
            axis=1,
        )
    return result


def standardise_file(path: Path, report: QualityReport) -> pd.DataFrame:
    raw, sheet = read_survey(path)
    discarded = [
        column for column in raw.columns
        if normalise_text(column) in DISCARDED_RAW_COLUMNS
    ]
    if discarded:
        raw = raw.drop(columns=discarded)
    raw = combine_surveymonkey_option_columns(raw)
    year = infer_year(path, raw)
    rename: dict[Any, str] = {}
    ignored = {
        "end date", "custom data 1", "survey", "covid", "score", "column1"
    }
    for column in raw.columns:
        matched = match_column(column)
        if matched:
            rename[column] = matched
        elif normalise_text(column) not in ignored and not normalise_text(column).startswith("unnamed"):
            report.unmatched_columns.append({"file": path.name, "column": str(column)})

    frame = combine_duplicate_columns(raw.rename(columns=rename))
    keep = [c for c in frame.columns if c in set(ID_COLUMNS + QUESTION_COLUMNS + ["postcode"])]
    frame = frame[keep].copy()

    # SurveyMonkey exports contain a first row describing each response type.
    if "responder_id" in frame:
        descriptor = frame["responder_id"].isna() & frame.astype(str).apply(
            lambda row: row.str.contains("Open-Ended Response|Response", case=False).any(),
            axis=1,
        )
        frame = frame.loc[~descriptor].copy()

    if "date" not in frame:
        frame["date"] = pd.Timestamp(year=year, month=7, day=1)
    else:
        frame["date"] = pd.to_datetime(
            frame["date"], errors="coerce", dayfirst=True, format="mixed"
        )
        frame["date"] = frame["date"].fillna(pd.Timestamp(year=year, month=7, day=1))
        mismatched_year = frame["date"].dt.year.ne(year)
        if mismatched_year.any():
            counts = frame.loc[mismatched_year, "date"].dt.year.value_counts().to_dict()
            report.warnings.append(
                f"{path.name}: {int(mismatched_year.sum())} response dates do not match "
                f"filename year {year}; date-year counts={counts}"
            )
    # Prefer the response date over the filename. The supplied "2020" workbook
    # deliberately contains hundreds of 2019 responses and otherwise double
    # counts them when historical workbooks are combined.
    frame["survey_year"] = frame["date"].dt.year.fillna(year).astype(int)
    frame["source_file"] = path.name
    frame["source_row"] = frame.index + 2
    if "responder_id" not in frame:
        frame["responder_id"] = [f"{year}-{i:05d}" for i in range(1, len(frame) + 1)]

    for pii in PII_COLUMNS:
        if pii in frame:
            frame = frame.drop(columns=pii)
    report.files_loaded.append(
        {"file": path.name, "sheet": sheet, "survey_year": year, "rows": len(frame)}
    )
    return frame.reset_index(drop=True)


def parse_number(value: Any, range_strategy: str = "midpoint") -> float:
    if pd.isna(value):
        return np.nan
    if isinstance(value, (int, float, np.number)):
        return float(value)
    text = normalise_text(value)
    numbers = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return np.nan
    if len(numbers) >= 2:
        if range_strategy == "upper":
            return float(numbers[1])
        return float(sum(numbers[:2]) / 2)
    return numbers[0]


def parse_time_number(value: Any) -> float:
    """Translate later survey time buckets to the earlier numeric convention."""
    if pd.isna(value):
        return np.nan
    text = normalise_text(value)
    bucket_values = {
        "0 hours": 0.0,
        "0 20 minutes": 20.0,
        "1 20": 20.0,
        "1 to 20": 20.0,
        "20 to 30": 25.0,
        "21 30": 25.0,
        "31 40": 35.0,
        "41 50": 45.0,
        "51 60": 55.0,
        "61 70": 60.0,
        "71 80": 60.0,
        "80": 60.0,
        "50 hours": 60.0,
        "60 minutes": 60.0,
    }
    if text in bucket_values:
        return bucket_values[text]
    number = parse_number(value)
    return min(number, 60.0) if not pd.isna(number) else np.nan


def score_scale_response(
    value: Any, survey_year: int | None = None, question: str | None = None
) -> float:
    if pd.isna(value) or str(value).strip() == "":
        return np.nan
    text = normalise_text(value)
    generic_categorical = {
        "none": 0.0,
        "no": 0.0,
        "not once": 0.0,
        "not at all": 0.0,
        "very poorly if at all": 0.0,
        "occasionally": 50.0,
    }
    question_categorical = {
        "cultural_activities": {"no": 0.0, "once or twice": 30.0, "many times": 50.0},
        "te_reo": {
            "very poorly if at all": 0.0,
            "moderate ability": 50.0,
            "fluent speaker": 90.0,
        },
        "cultural_knowledge": {"none": 0.0, "no": 0.0, "once or twice": 30.0, "many times": 50.0},
        "discrimination": {"none": 0.0, "not once": 0.0, "once or twice": 30.0, "many times": 50.0},
        "loneliness": {"not once": 0.0, "occasionally": 50.0, "frequently": 80.0},
        "volunteering_time": {"not at all": 0.0, "occasionally": 50.0, "very frequently": 90.0},
    }
    if question in question_categorical and text in question_categorical[question]:
        return question_categorical[question][text]
    if text in generic_categorical:
        return generic_categorical[text]
    number = parse_number(value)
    if pd.isna(number):
        return np.nan
    # 2019-2022 are 0-100 slider exports, where a value such as 5 must remain 5.
    # The Google Forms surveys from 2024 onward use a 0-10 scale.
    if survey_year is not None and survey_year >= 2024 and 0 <= number <= 10:
        return number * 10
    return float(np.clip(number, 0, 100))


def score_binary(value: Any) -> float:
    if pd.isna(value) or str(value).strip() == "":
        return np.nan
    text = normalise_text(value)
    yes_values = {"yes", "y", "true", "1", "newlands paparangi bellevue or woodridge"}
    no_values = {"no", "n", "false", "0"}
    if text in yes_values:
        return 100.0
    if text in no_values:
        return 0.0
    number = parse_number(value)
    if number == 1:
        return 100.0
    if number == 0:
        return 0.0
    return np.nan


def score_paid_hours(value: Any) -> float:
    h = parse_time_number(value)
    if pd.isna(h): return np.nan
    if h < 10: return 20.0
    if h < 20: return 40.0
    if h < 30: return 70.0
    if h <= 40: return 100.0
    if h <= 50: return 80.0
    if h <= 60: return 50.0
    return 20.0


def score_travel_time(value: Any) -> float:
    if not pd.isna(value) and normalise_text(value) == "don t travel to work regularly":
        t = 100.0
        return 100.0
    else:
        t = parse_time_number(value)
    if pd.isna(t): return np.nan
    if t < 5: return 100.0
    if t < 10: return 95.0
    if t < 20: return 90.0
    if t < 25: return 85.0
    if t <= 30: return 80.0
    if t <= 40: return 60.0
    if t <= 50: return 40.0
    if t <= 60: return 20.0
    return 10.0


def score_leisure_time(value: Any) -> float:
    h = parse_time_number(value)
    if pd.isna(h): return np.nan
    if h < 5: return 10.0
    if h < 10: return 20.0
    if h < 20: return 30.0
    if h < 30: return 60.0
    if h == 30: return 80.0
    if h < 40: return 90.0
    if h < 50: return 95.0
    if h <= 60: return 100.0
    return 90.0


def score_question(question: str, value: Any, survey_year: int | None = None) -> float:
    if question == "newlands_resident" and not pd.isna(value):
        text = normalise_text(value)
        if any(place in text for place in ("newlands", "paparangi", "bellevue", "woodridge")):
            score = 100.0
        elif text in {"johnsonville", "khandallah broadmeadows or kaiwharawhara"}:
            score = 0.0
        else:
            score = score_binary(value)
    elif question in BINARY_QUESTIONS:
        score = score_binary(value)
    elif question == "paid_working_hours":
        score = score_paid_hours(value)
    elif question == "work_travel_time":
        score = score_travel_time(value)
    elif question == "leisure_time":
        score = score_leisure_time(value)
    else:
        score = score_scale_response(value, survey_year=survey_year, question=question)
    if question in REVERSED_QUESTIONS and not pd.isna(score):
        score = 100.0 - score
    return score


def power_bi_score_input(question: str, value: Any, survey_year: int) -> float:
    """Return the numeric Score column that exists immediately before CleanScore."""
    if question in BINARY_QUESTIONS:
        binary = score_binary(value)
        return binary / 100.0 if not pd.isna(binary) else np.nan
    if question in {"paid_working_hours", "work_travel_time", "leisure_time"}:
        return parse_time_number(value)
    return score_scale_response(value, survey_year=survey_year, question=question)


def remove_duplicates(frame: pd.DataFrame, report: QualityReport) -> pd.DataFrame:
    compare = [c for c in ID_COLUMNS + QUESTION_COLUMNS if c in frame.columns]
    exact = frame.duplicated(compare, keep="first")
    for _, row in frame.loc[exact].iterrows():
        report.duplicate_rows.append(
            {"file": row.get("source_file"), "source_row": row.get("source_row"), "reason": "exact"}
        )
    frame = frame.loc[~exact].copy()

    # Respondent IDs are only meaningful within a survey year. Some exports have
    # already rounded every ID to the same value (notably the supplied 2022 CSV),
    # so an ID is used for deduplication only when it retains useful uniqueness.
    if "responder_id" in frame:
        if "source_file" not in frame:
            frame["source_file"] = "<unknown>"
        valid_id = frame["responder_id"].notna() & frame["responder_id"].astype(str).ne("")
        eligible = pd.Series(False, index=frame.index)
        for (year, source_file), group in frame.loc[valid_id].groupby(["survey_year", "source_file"]):
            uniqueness = group["responder_id"].nunique() / max(len(group), 1)
            if uniqueness >= 0.9:
                eligible.loc[group.index] = True
            elif len(group) > 1:
                report.warnings.append(
                    f"{source_file} survey year {int(year)} respondent IDs are only "
                    f"{uniqueness:.1%} unique; "
                    "ID-based deduplication was skipped"
                )
        duplicate_id = eligible & frame.loc[eligible].duplicated(
            ["survey_year", "responder_id"], keep="first"
        ).reindex(frame.index, fill_value=False)
        for _, row in frame.loc[duplicate_id].iterrows():
            report.duplicate_rows.append(
                {"file": row.get("source_file"), "source_row": row.get("source_row"), "reason": "respondent_id"}
            )
        frame = frame.loc[~duplicate_id].copy()
    return frame.reset_index(drop=True)


def calculate_backfill_values(frame: pd.DataFrame) -> dict[str, float]:
    return POWER_BI_BACKFILL_VALUES.copy()


def apply_power_bi_rules(frame: pd.DataFrame, report: QualityReport) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = frame.copy()
    for question in QUESTION_COLUMNS:
        if question not in frame:
            frame[question] = np.nan

    # The approved baseline only scores each election question in the survey
    # wave where that election was asked as the current participation measure.
    election_year_masks = {
        "vote_local_elections_2019": frame["survey_year"].eq(2021),
        "vote_general_election_2020": frame["survey_year"].eq(2021),
        "voted_local_elections_2022": frame["survey_year"].ge(2024),
        "voted_general_elections_2023": frame["survey_year"].ge(2024),
    }
    for question, valid_rows in election_year_masks.items():
        frame.loc[~valid_rows, question] = np.nan
    frame.loc[frame["survey_year"].eq(2021), "newlands_resident"] = np.nan

    # One 2022 response was treated as missing in the approved baseline after an
    # internally inconsistent disaster-answer combination. Preserve that legacy
    # decision so regenerated historical results remain comparable.
    legacy_2022_disaster_exception = (
        frame["survey_year"].eq(2022)
        & frame["home_disaster_ready"].map(normalise_text).eq("no")
        & frame["neighbourhood_support_group"].map(normalise_text).eq("yes")
        & frame["out_of_newlands_during_day"].map(normalise_text).eq("no")
        & frame["place_out_of_newlands_disaster_ready"].map(normalise_text).eq("no")
    )
    frame.loc[
        legacy_2022_disaster_exception,
        ["home_disaster_ready", "neighbourhood_support_group"],
    ] = np.nan

    backfill = calculate_backfill_values(frame)
    report.backfill_values = backfill
    for question, value in backfill.items():
        frame[question] = frame[question].fillna(value)

    frame["number_null_values"] = frame[POWER_BI_COMPLETENESS_COLUMNS].isna().sum(axis=1)
    rejected = frame["number_null_values"] > 6
    rejected = rejected | frame["age_range"].isna()
    for _, row in frame.loc[rejected].iterrows():
        reason = (
            "missing_age_range"
            if pd.isna(row["age_range"])
            else "more_than_6_missing_core_questions"
        )
        report.rejected_rows.append(
            {
                "file": row.get("source_file"),
                "source_row": row.get("source_row"),
                "reason": reason,
                "missing": int(row["number_null_values"]),
            }
        )
    accepted = frame.loc[~rejected].copy()
    accepted["gender"] = accepted["gender"].fillna("Do not wish to state")
    accepted["responder_id"] = np.arange(1, len(accepted) + 1)

    value_vars = [q for q in QUESTION_COLUMNS if accepted[q].notna().any()]
    long = accepted.melt(
        id_vars=["responder_id", "date", "survey_year", "age_range", "gender", "source_file", "source_row"],
        value_vars=value_vars,
        var_name="Question",
        value_name="OriginalResponse",
    )
    long["Score"] = [
        power_bi_score_input(q, v, int(year))
        for q, v, year in zip(long["Question"], long["OriginalResponse"], long["survey_year"])
    ]
    long["CleanScore"] = [
        score_question(q, v, int(year))
        for q, v, year in zip(long["Question"], long["OriginalResponse"], long["survey_year"])
    ]
    unscored = long["OriginalResponse"].notna() & long["CleanScore"].isna()
    if unscored.any():
        for (q, raw), count in long.loc[unscored].groupby(["Question", "OriginalResponse"], dropna=False).size().items():
            report.warnings.append(f"Unscored response: {q}={raw!r} ({count} rows)")
    long = long.dropna(subset=["CleanScore"]).copy()
    long["CleanScore"] = long["CleanScore"].clip(0, 100)

    scored_wide = accepted.drop(columns=["number_null_values"]).copy()
    for question in QUESTION_COLUMNS:
        scored_wide[question] = [
            score_question(question, value, int(year))
            for value, year in zip(scored_wide[question], scored_wide["survey_year"])
        ]
    # Keep the established output schema stable even when a new questionnaire
    # asks the 2026 question before the 2025 question.
    current_election_columns = [
        "vote_council_election_2025",
        "vote_general_election_2026",
    ]
    scored_wide = scored_wide[
        [c for c in scored_wide.columns if c not in current_election_columns]
        + current_election_columns
    ]
    return scored_wide, long


def backfill_2023(long: pd.DataFrame, report: QualityReport) -> pd.DataFrame:
    long = long.copy()
    # Scenario aggregation always expects this field. Create it even when the
    # input contains no 2022 data (for example, a future-only test file).
    if "is_backfilled" not in long:
        long["is_backfilled"] = False
    years = set(long["survey_year"].astype(int))
    if 2023 in years:
        return long
    source = long[long["survey_year"] == 2022].copy()
    if source.empty:
        report.warnings.append("2023 was not backfilled because no 2022 rows were available")
        return long
    source["survey_year"] = 2023
    source["date"] = pd.Timestamp("2023-07-01")
    source["source_file"] = "BACKFILL_FROM_2022"
    source["is_backfilled"] = True
    long["is_backfilled"] = False
    return pd.concat([long, source], ignore_index=True)


def add_scenario_metadata(long: pd.DataFrame) -> pd.DataFrame:
    frame = long.copy()
    metadata = frame["Question"].map(QUESTION_METADATA)
    known = metadata.notna()
    frame = frame.loc[known].copy()
    metadata = metadata.loc[known]
    frame["group"] = metadata.map(lambda x: x[0])
    frame["resilience_description"] = metadata.map(lambda x: x[1])
    frame["area_color_key"] = metadata.map(lambda x: x[1])
    frame["subdomain"] = metadata.map(lambda x: x[2])
    frame["Resilience_ID"] = frame["Question"]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["year"] = frame["survey_year"].astype(int)
    return frame


def discover_inputs(input_dir: Path, output_dir: Path) -> list[Path]:
    if not input_dir.exists():
        return []
    files = []
    for path in sorted(input_dir.iterdir()):
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if path.name.startswith("~$") or output_dir in path.parents:
            continue
        files.append(path)
    return files


def historical_core_columns() -> list[str]:
    metadata = [
        "responder_id",
        "date",
        "survey_year",
        "postcode",
        "age_range",
        "gender",
        "source_file",
        "source_row",
    ]
    return metadata + QUESTION_COLUMNS


def build_historical_core(
    raw_dir: Path,
    output_path: Path = DEFAULT_HISTORICAL_CORE_PATH,
    through_year: int = HISTORICAL_CORE_MAX_YEAR,
) -> Path:
    """Build a PII-free, standardised historical input dataset."""
    report = QualityReport()
    inputs = discover_inputs(raw_dir, output_path.parent)
    if not inputs:
        raise ValueError(f"No historical survey files found in {raw_dir}")

    frames = []
    for path in inputs:
        try:
            frames.append(standardise_file(path, report))
        except Exception as exc:
            raise ValueError(
                f"Historical core could not load {path.name}: {type(exc).__name__}: {exc}"
            ) from exc

    core = remove_duplicates(pd.concat(frames, ignore_index=True, sort=False), report)
    core = core.loc[core["survey_year"].le(through_year)].copy()
    if core.empty:
        raise ValueError(f"No historical responses through {through_year} were found")
    allowed_columns = set(historical_core_columns())
    for column in historical_core_columns():
        if column not in core:
            core[column] = np.nan
    # Preserve the legacy import order so responder IDs and output column order
    # remain identical when the core replaces the individual source files.
    core = core[[column for column in core.columns if column in allowed_columns]]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    core.to_csv(output_path, index=False)
    return output_path


def load_historical_core(path: Path, report: QualityReport) -> pd.DataFrame:
    """Load the standardised historical core without treating it as a survey export."""
    frame = pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)
    frame = blank_strings_to_nan(frame)
    required = {"responder_id", "date", "survey_year", "age_range", "gender"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Historical core is missing columns: {missing}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", format="mixed")
    frame["survey_year"] = pd.to_numeric(frame["survey_year"], errors="raise").astype(int)
    future_rows = frame["survey_year"].gt(HISTORICAL_CORE_MAX_YEAR)
    if future_rows.any():
        years = sorted(frame.loc[future_rows, "survey_year"].unique().tolist())
        raise ValueError(
            f"Historical core contains future survey years {years}; "
            f"expected {HISTORICAL_CORE_MAX_YEAR} or earlier"
        )
    allowed_columns = set(historical_core_columns())
    ordered_columns = [column for column in frame.columns if column in allowed_columns]
    for column in historical_core_columns():
        if column not in frame:
            frame[column] = np.nan
            ordered_columns.append(column)
    # CSV columns can contain both numeric slider values and later categorical
    # answers, so pandas loads the whole column as text. Restore cells that are
    # purely numeric to preserve the historical scoring behaviour.
    numeric_text = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

    def restore_numeric_response(value: Any) -> Any:
        if not isinstance(value, str) or not numeric_text.fullmatch(value.strip()):
            return value
        number = float(value)
        return int(number) if number.is_integer() else number

    for question in QUESTION_COLUMNS:
        frame[question] = frame[question].map(restore_numeric_response)
    report.files_loaded.append(
        {
            "file": path.name,
            "sheet": "HISTORICAL_CORE",
            "survey_year": f"through {HISTORICAL_CORE_MAX_YEAR}",
            "rows": len(frame),
        }
    )
    return frame[ordered_columns].copy()


def resolve_p2g_path(p2g_path: Path | None) -> Path | None:
    """Use an explicit P2G file, otherwise auto-discover the project config."""
    if p2g_path is not None:
        return p2g_path.expanduser().resolve()
    if DEFAULT_P2G_PATH.exists():
        return DEFAULT_P2G_PATH
    return None


def run_scenarios(cleaned: pd.DataFrame, output_dir: Path, p2g_path: Path | None, report: QualityReport) -> None:
    import newlands_scenario_pipeline as scenario

    scenario_data_dir = output_dir / "data" / "scenarios"
    chart_dir = output_dir / "charts"
    scenario_data_dir.mkdir(parents=True, exist_ok=True)
    chart_dir.mkdir(parents=True, exist_ok=True)

    resolved_p2g_path = resolve_p2g_path(p2g_path)
    if resolved_p2g_path and resolved_p2g_path.exists():
        p2g = pd.read_csv(resolved_p2g_path, encoding="utf-8-sig")
        required = {"Question", "2030 - 2033", "After 2033"}
        missing = required - set(p2g.columns)
        if missing:
            raise ValueError(f"P2G file is missing columns: {sorted(missing)}")
        if p2g["Question"].duplicated().any():
            duplicates = sorted(
                p2g.loc[p2g["Question"].duplicated(False), "Question"]
                .astype(str)
                .unique()
            )
            raise ValueError(f"P2G file has duplicate indicators: {duplicates}")
        for column in ["2030 - 2033", "After 2033"]:
            p2g[column] = pd.to_numeric(p2g[column], errors="raise")
        unknown = sorted(set(p2g["Question"].astype(str)) - set(QUESTION_METADATA))
        if unknown:
            raise ValueError(f"P2G file has unknown indicators: {unknown}")
        report.p2g_config = {
            "file": str(resolved_p2g_path),
            "indicator_count": int(len(p2g)),
            "nonzero_construction_count": int(p2g["2030 - 2033"].ne(0).sum()),
            "nonzero_after_2033_count": int(p2g["After 2033"].ne(0).sum()),
        }
    else:
        p2g = pd.DataFrame(columns=["Question", "2030 - 2033", "After 2033"])
        report.warnings.append("P2G indicator file was not supplied; P2G impacts defaulted to zero")
        report.p2g_config = {"file": None, "indicator_count": 0}

    bau = scenario.calculate_bau_trend(cleaned)
    legacy = scenario.calculate_bau_projection_per_question(cleaned)
    acorn = scenario.calculate_acorn_scenario(bau)
    p2g_acorn = scenario.calculate_p2g_scenario(acorn, p2g)
    p2g_bau = scenario.calculate_p2g_bau_scenario(bau, p2g)

    bau.to_csv(scenario_data_dir / "BAU_output.csv", index=False)
    legacy.to_csv(scenario_data_dir / "BAU_projection_per_question.csv", index=False)
    acorn.to_csv(scenario_data_dir / "ACoRN_output.csv", index=False)
    p2g_acorn.to_csv(scenario_data_dir / "P2G_output.csv", index=False)
    p2g_bau.to_csv(scenario_data_dir / "P2G_bau_output.csv", index=False)

    # Pass explicit destinations because the legacy functions bind their default
    # output paths at import time.
    scenario.plot_trend_graph(bau, chart_dir / "BAU")
    scenario.plot_acorn_graphs(acorn, chart_dir / "ACoRN")
    scenario.plot_p2g_graphs(p2g_acorn, chart_dir / "P2G")
    scenario.plot_p2g_bau_graphs(p2g_bau, chart_dir / "P2G-BAU")


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    p2g_path: Path | None = None,
    skip_charts: bool = False,
    historical_core_path: Path | None = None,
) -> Path:
    report = QualityReport()
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = discover_inputs(input_dir, output_dir)

    frames = []
    if historical_core_path is not None:
        if not historical_core_path.exists():
            raise FileNotFoundError(f"Historical core was not found: {historical_core_path}")
        frames.append(load_historical_core(historical_core_path, report))
    for path in inputs:
        try:
            frames.append(standardise_file(path, report))
        except Exception as exc:
            report.warnings.append(f"Skipped {path.name}: {type(exc).__name__}: {exc}")
    if not frames:
        raise ValueError(
            f"No historical core or supported future survey files were found in {input_dir}"
        )

    combined = remove_duplicates(pd.concat(frames, ignore_index=True, sort=False), report)
    wide, long = apply_power_bi_rules(combined, report)
    long = backfill_2023(long, report)
    cleaned = add_scenario_metadata(long)

    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    wide.to_csv(data_dir / "newlands_cleaned_wide.csv", index=False)
    baseline_wide = wide[
        ["responder_id", "date", "age_range", "gender"] + BASELINE_WIDE_QUESTION_ORDER
    ].rename(columns={"responder_id": "Responder_ID"})
    baseline_wide.to_csv(data_dir / "Newlands_baseline_wide.csv", index=False)
    baseline_long = long[
        ["responder_id", "date", "age_range", "gender", "Question", "Score", "CleanScore"]
    ].rename(columns={"responder_id": "Responder_ID"})
    baseline_long.to_csv(data_dir / "Newlands_baseline_long.csv", index=False)
    cleaned.to_csv(data_dir / "Newlands_analysis_ready_long.csv", index=False)

    if not skip_charts:
        run_scenarios(cleaned, output_dir, p2g_path, report)
    report.save(output_dir)
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_FUTURE_INPUT_DIR,
        help="Folder containing future survey CSV/XLSX files (default: data/future)",
    )
    parser.add_argument("--output", type=Path, default=None, help="Output folder (default: output/run_TIMESTAMP)")
    parser.add_argument(
        "--p2g",
        type=Path,
        default=None,
        help="Linked indicators to P2G CSV (default: config/Linked indicators to P2G.csv)",
    )
    parser.add_argument("--skip-charts", action="store_true", help="Only build cleaned wide/long datasets")
    parser.add_argument(
        "--historical-core",
        type=Path,
        default=DEFAULT_HISTORICAL_CORE_PATH,
        help="Standardised historical dataset through 2025 (default: data/core/...csv)",
    )
    parser.add_argument(
        "--historical-raw",
        type=Path,
        default=DEFAULT_HISTORICAL_RAW_DIR,
        help="Archived historical survey exports used to build the core (default: data/raw)",
    )
    parser.add_argument(
        "--rebuild-historical-core",
        action="store_true",
        help="Rebuild the historical core from --historical-raw before running",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output or PROJECT_DIR / "output" / f"run_{datetime.now():%Y%m%d_%H%M%S}"
    try:
        historical_core = args.historical_core.resolve()
        if args.rebuild_historical_core or not historical_core.exists():
            build_historical_core(args.historical_raw.resolve(), historical_core)
            print(f"Historical core ready: {historical_core}")
        result = run_pipeline(
            args.input.resolve(),
            output.resolve(),
            args.p2g,
            args.skip_charts,
            historical_core_path=historical_core,
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Pipeline completed: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

