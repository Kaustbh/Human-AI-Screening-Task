# AI-Powered Funding Intelligence Screening Task

This submission implements a minimal FOA ingestion pipeline that:

- fetches a public FOA URL
- extracts the required screening-task fields into a normalized schema
- applies deterministic rule-based semantic tags
- exports `foa.json` and `foa.csv`

Current scope is limited to `simpler.grants.gov` / `grants.gov` opportunity pages.

## Run

```bash
python main.py --url "https://simpler.grants.gov/opportunity/1938b9bd-6293-480f-ba92-7ec9ba3c18ea" --out_dir ./out
```

## Output schema

The script writes:

- `foa_id`
- `foa_number`
- `title`
- `agency`
- `open_date`
- `close_date`
- `eligibility`
- `program_description`
- `program_funding`
- `award_minimum`
- `award_maximum`
- `source_url`
- `semantic_tags`
- `tagging_method`

## Source support

- `simpler.grants.gov` / `grants.gov`

## Notes

- Dates are normalized to `YYYY-MM-DD` when detected.
- Tags are deterministic and ontology-aligned through keyword rules.
- The implementation is intentionally minimal for the screening task.
