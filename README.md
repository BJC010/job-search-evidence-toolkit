# Job Search Evidence Toolkit

A small, local-first Python utility for planning bounded job-board searches, validating saved page-by-page collection evidence, checking exact company–title deduplication against a supplied tracker snapshot, and calculating descriptive yield metrics.

The toolkit is not a job-board scraper or a complete job-application automation system. It does not log in to sites, read a resume, access a live tracker, score job descriptions, submit applications, send email, or create schedules. A human-operated collector or a separately reviewed integration supplies the evidence files.

## Included

- `job_search_evidence.py`: deterministic manifest, checkpoint, validation, and measurement functions.
- `validate_config.py`: checks a local search configuration.
- `config/search.example.json`: neutral placeholder configuration; replace its example lane, query phrases, filters, radius, and target for your own workflow.
- `tests/`: synthetic integrity tests only. They are not live search results.
- `docs/input-contract.md`: input fields and evidence limitations.

This release contains no resume, candidate profile, role preferences, tracker identifiers or rows, email addresses, credentials, or historical job-search artifacts.

## Requirements and setup

- Python 3.11 or later
- No runtime third-party dependencies

From this folder:

```bash
python -m venv .venv
```

Activate the environment and copy the example config to a local-only file.

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
Copy-Item config/search.example.json config/search.json
```

macOS/Linux:

```bash
source .venv/bin/activate
cp config/search.example.json config/search.json
```

Then install the local command and validate the example:

```bash
python -m pip install -e .
python validate_config.py config/search.example.json
```

Before using the CLI, create `config/search.json` from the example and replace every placeholder with your own search lanes, query phrases, filters, and target. `config/search.json` and `output/` are ignored by Git because they may contain personal search criteria and job records.

## Typical offline workflow

```bash
job-search-evidence plan 2026-10-07 --config config/search.json --output output/manifest.json
job-search-evidence checkpoint output/raw-collection.json output/manifest.json --config config/search.json --output output/checkpoint.json
job-search-evidence measure output/checkpoint.json output/analysis.json --config config/search.json --output output/measurement.json
python -m unittest discover -s tests -v
```

The JSON input formats are documented in [`docs/input-contract.md`](docs/input-contract.md). `raw-collection.json` should contain only records collected by an authorized process. `analysis.json` is supplied by the caller after reviewing job descriptions and a current tracker snapshot.

## Evidence and privacy limits

Structural checks can detect missing pages, mismatched filters, duplicate normalized pairs, inaccessible job descriptions that were scored, and invalid timestamps. They cannot prove that a screenshot or text observation is authentic, that a job is still open, or that a resume/JD assessment is correct. Do not include actual resume text, contact details, tracker exports, or collected role records in a public repository. Keep local config and output files private.

The MIT License in [`LICENSE`](LICENSE) permits reuse, modification, and redistribution subject to its notice and warranty terms.
