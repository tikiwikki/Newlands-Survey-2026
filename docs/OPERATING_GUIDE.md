# Newlands pipeline operating guide

## Purpose

The pipeline combines the approved historical core through 2025 with any
authorized 2026-or-later survey exports, applies the configured cleaning and
scoring rules, and creates analysis and scenario outputs. Files are read from
`data/future` because they are newer than the fixed core; their results are
observed survey data, not forecasts.

## Prepare local inputs

The public repository does not include survey responses. Keep respondent-level
inputs in an approved private location. Local files under `data/core`,
`data/future`, and `data/raw` are ignored by Git.

1. Place the approved historical core at
   `data/core/Newlands_historical_core_through_2025.csv`, or pass its location
   with `--historical-core`.
2. Remove old local test exports from `data/future` if they should not be part
   of the run.
3. Copy authorized 2026-or-later exports into `data/future`.
4. From the project folder, run:

   ```bash
   python newlands_integrated_pipeline.py
   ```

5. Confirm the terminal reports `Pipeline completed:` and review the newest
   timestamped folder under `output/`, especially its `reports` directory.

Every supported export in `data/future` is included in the run. Leaving two
exports in that folder intentionally includes both. Do not commit survey files
or generated output to the public repository.

## What the pipeline does

During a normal run, it:

1. loads the standardised historical core through 2025;
2. imports supported survey exports from `data/future`;
3. removes duplicate responses where the available identifiers are reliable;
4. applies the configured missing-data, backfill, and scoring rules;
5. treats imported survey-year results as observed (`historical`) data;
6. fits the BAU trend using all available observed years;
7. starts projections after the latest observed year; and
8. writes cleaned data, scenario results, reports, and charts under `output/`.

The pipeline leaves source files unchanged. No database server is required.

## Review outputs before sharing

Check the following files in the newest run folder:

- `reports/quality_report.json` for loaded files, warnings, backfill details,
  rejected rows, and P2G configuration;
- `reports/unmatched_columns.csv` for survey questions that did not match the
  configured fields;
- `reports/duplicate_rows.csv` for removed duplicate responses;
- `reports/rejected_rows.csv` for excluded responses; and
- `data/newlands_cleaned_wide.csv` for the imported survey years and counts.

Generated outputs can contain row-level survey data. Treat them with the same
care as the source inputs and share them only through an approved channel.

## Manage the historical core

Treat the approved core as read-only during ordinary runs. The `data/raw`
archive is needed only when rebuilding the core after an approved historical
correction. Keep that archive private as well.

Survey files do not move automatically as calendar years pass. Keep a
post-2025 survey in `data/future` until its records are formally incorporated
into a newly approved core. Moving a file to `data/raw` alone does not include
it in ordinary runs.

To rebuild the core after an approved correction, make sure the complete
historical archive is available locally and run:

```bash
python newlands_integrated_pipeline.py --rebuild-historical-core
```

After rebuilding, run the automated tests and compare the historical output
before distributing an updated core.

## Useful commands

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Generate cleaned data without scenario calculations or charts:

```bash
python newlands_integrated_pipeline.py --skip-charts
```

Run the existing unit tests:

```bash
python -m unittest discover -s tests -v
```

The optional `baseline_regression_check.py` requires private archived source
files under `data/raw` and approved comparison files under
`reference/previous_baseline`; neither is included in this public repository.

## Troubleshooting

### `SystemExit: 1`

This indicates the program exited after another error. Read the earlier
terminal line beginning with `ERROR:` for the cause.

### Historical core was not found

Provide the approved core with `--historical-core`, put it at the documented
local path, or restore the full historical archive and rebuild the core.

### Required questions appear in `unmatched_columns.csv`

The survey wording is not covered by the current matching rules. Update the
field matching and review the output before approving results.

### One year appears as both `historical` and `projected`

Regenerate outputs with the current pipeline scripts. Projection years start
after the latest imported observed year; BAU output checks for overlaps.

### A Python package is missing

From the project folder, run `python -m pip install -r requirements.txt`.
