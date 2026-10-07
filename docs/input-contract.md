# Input contract

The collector and analyst are outside this package. The package accepts JSON and validates consistency; it does not verify that the observations themselves are true.

## Search configuration

Start with `config/search.example.json`. Configure each lane with one or more `core_queries` and exactly one bounded `fallback_queries` entry. Set source filters and the target explicitly. The helper fingerprints the full configuration so a checkpoint cannot silently be measured under changed search rules.

## Collection input

The raw collection file has two arrays:

```json
{
  "candidate_cards": [
    {
      "cell_id": "manifest-cell-id",
      "page": 1,
      "company": "Example Employer",
      "title": "Example Role",
      "url": "https://example.test/job",
      "captured_at": "2026-10-07T13:00:00+00:00"
    }
  ],
  "coverage": [
    {
      "cell_id": "manifest-cell-id",
      "source": "LinkedIn",
      "lane": "Example family A",
      "query": "example query",
      "days": 1,
      "radius_km": 25,
      "sort": "Most recent",
      "page": 1,
      "filtered_results_url": "https://example.test/search",
      "timestamp": "2026-10-07T13:00:00+00:00",
      "status": "exhausted",
      "card_count": 1,
      "has_next_page": false,
      "page_end_observed": true,
      "sort_control_observed": true,
      "evidence": "Synthetic example: page end observed"
    }
  ]
}
```

For empty result pages, include `no_results_evidence`. For blocked pages, include an observed `blocker`; a blocker preserves an incomplete-coverage status rather than implying zero supply. If a page indicates more results, collect the next configured page. The last configured page may be reported as capped when more results remain.

## Analysis input

Analysis includes a complete, fresh tracker snapshot and one record for each eligible normalized company–title pair. Each record must identify whether the JD was accessible, provide JD evidence and an actual check timestamp, and remain unscored when the JD could not be read. Assessed records require a 0–10 score, a written rationale, and an assessment timestamp after the collection checkpoint. Capability matches and mandatory gaps must be tied to evidence in the supplied resume and JD; this package does not contain either document.

## Output interpretation

The measurement output describes only the collected, filtered evidence. Incomplete or blocked coverage is never interpreted as zero market supply. Counts and composition are descriptive; they do not establish market-wide availability or causation.
