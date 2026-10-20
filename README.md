# Newlands survey pipeline

Python pipeline for importing Newlands community survey exports, applying the
approved cleaning and scoring rules, and producing analysis-ready data,
scenario outputs, charts, and quality reports.

## Repository contents

This public repository contains the pipeline code, scoring configuration,
automated tests, and operating documentation. It does not contain survey
responses. The supplied historical and 2026 survey files include respondent
identifiers, postcodes, timestamps, or a free-text contact field. Keep those
files in an approved private location and do not commit them here.

The data folders contain instructions only. The repository's `.gitignore`
excludes files added locally under `data/core`, `data/future`, and `data/raw`,
as well as generated `output` and regression-reference files.

## Set up a local run

1. Install Python 3.10 or later.
2. Install dependencies from the repository folder:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Place the approved historical core at
   `data/core/Newlands_historical_core_through_2025.csv`, and place authorized
   2026-or-later survey exports in `data/future`. Keep all these inputs local
   and out of Git.
4. Run the pipeline:

   ```bash
   python newlands_integrated_pipeline.py
   ```

On Windows, `py` can be used instead of `python`. To use a separately stored
historical core, pass its local path explicitly:

```bash
python newlands_integrated_pipeline.py --historical-core /path/to/private/historical_core.csv
```

New survey exports are observed results, even though they are read from
`data/future`. Projections start after the latest observed survey year. The
pipeline writes each run to a timestamped folder under `output/`; inspect its
quality reports before sharing results.

## Project layout

```text
newlands_integrated_pipeline.py       Main import, cleaning, and orchestration
newlands_scenario_pipeline.py         Scenario calculations and charts
baseline_regression_check.py          Optional historical comparison check
config/                               Scoring and P2G configuration
data/core/                            Local approved historical core
data/future/                          Local post-2025 survey intake
data/raw/                             Local archive for approved core rebuilds
docs/                                 Operating guide and legacy translation
tests/                                Automated unit tests
output/                               Generated results (ignored by Git)
```

Run the existing unit test suite with:

```bash
python -m unittest discover -s tests -v
```

`baseline_regression_check.py` also requires approved reference files under
`reference/previous_baseline`. Those files are not included in this public
repository; keep them local.

See [docs/OPERATING_GUIDE.md](docs/OPERATING_GUIDE.md) for the operating
procedure and [docs/POWERBI_BACKFILL_TRANSLATION.md](docs/POWERBI_BACKFILL_TRANSLATION.md)
for the archived Power Query translation reference.
