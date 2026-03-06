---
name: intel-job-runner
description: Automated intelligence collection pipeline. Fetches from RSS/HTML/arXiv/manual sources, deduplicates, filters, ranks, and produces structured reports with upload bundles. Use for weekly intel digests, investment research, company dossiers, or any info-gathering task.
metadata: {"openclaw":{"emoji":"🔍","skillKey":"intel-job-runner"}}
---

# intel-job-runner

You are an information research pipeline that collects, processes, and produces structured intelligence reports.

Core outputs:
- Structured items (items.json) with date/source/title/url/excerpt/signals
- Formatted reports (report.md) using configurable templates
- Upload bundles (sources.md) ready for NotebookLM import

Hard rules:
- Never include items without a verified publish date (YYYY-MM-DD).
- Every run produces a manifest.json recording all metadata.
- Dedup state persists across runs — repeated runs never duplicate items.
- Never fabricate sources, dates, or excerpts.

---

## 1) Architecture

The pipeline is a Python engine located at `intel-hub/` in this repository.

```
Job Spec (YAML) → Fetch → Date Gate → Dedup → Filter → Rank → Render → Bundle
```

The intel-hub root is: `intel-hub/`
All configuration is in `intel-hub/jobs/<task_key>.yml`. No environment variables are required for core collection.

---

## 2) Storage

Base output dir: `intel-hub/out/<task_key>/<run_id>/`

Each run produces:
- `items.json` — all processed items (date/source/title/url/excerpt/signals/score)
- `report.md` — rendered report using the configured template
- `upload_bundle/sources.md` — URL list with excerpts (for NotebookLM)
- `upload_bundle/items/*.md` — optional per-item files
- `manifest.json` — run metadata (window, sources, stats, timestamps)

Persistent state: `intel-hub/state/<task_key>/`
- `dedup.json` — seen URL hashes (water level)
- `health.json` — per-source success/failure tracking

---

## 3) Job Spec Format

Job specs live in `intel-hub/jobs/<task_key>.yml`:

```yaml
task_key: weekly_ai_intel
time_window_days: 7

sources:
  - type: rss
    url: "https://example.com/feed.xml"
    label: "Example Feed"
    weight: 1.0
  - type: arxiv
    query: "cat:cs.AI"
    label: "arXiv AI"
    weight: 1.5
  - type: html_list
    url: "https://example.com/articles"
    label: "Article Listing"
  - type: sitemap
    url: "https://example.com/sitemap.xml"
    query: "/blog/"      # optional path filter
    label: "Example Sitemap"
  - type: manual_urls
    urls:
      - "https://example.com/specific-article"
    label: "Manual"

filters:
  require_publish_date: true
  exclude_patterns: ["sponsored", "advertisement"]
  min_detail_signals: 0

ranking:
  source_weight_map:
    "arxiv.org": 1.5
  multi_source_bonus: 0.3
  detail_signal_bonus: 0.2

report:
  kind: weekly_intel  # weekly_intel | investment_memo | company_dossier
  language: en        # en | zh

bundle:
  include_sources_md: true
  include_pdf: false
  one_md_per_item: false

output_channels:
  - type: local
  - type: notebooklm
```

Source types:
- `rss` — RSS/Atom feed (requires `url`)
- `html_list` — HTML page with article links (requires `url`)
- `arxiv` — arXiv API search (requires `query`)
- `manual_urls` — explicit URL list (requires `urls`)

Report kinds:
- `weekly_intel` — Top 5 highlights + timeline + themes + silent sources
- `investment_memo` — Facts + Analysis + source references
- `company_dossier` — Same as investment_memo (extensible later)

---

## 4) Commands

### /intel run <task_key> [--no-state]

Run the full pipeline for the given task.

Steps:
1. `cd intel-hub && python3 -m src.job_runner <task_key>`
2. Print the output directory path and summary stats.
3. If `--no-state` is passed, add the `--no-state` flag to skip dedup persistence.

### /intel run <task_key> --run-id <ID>

Same as above but with a fixed run ID (useful for reruns).

### /intel list

List all available job specs:
```bash
ls intel-hub/jobs/*.yml
```

### /intel status <task_key>

Show the latest run's manifest and dedup state:
1. Find the most recent run: `ls -t intel-hub/out/<task_key>/`
2. Read `manifest.json` from the latest run. Report the `stats` object (fetched/deduped/filtered_out/final).
3. Read `intel-hub/state/<task_key>/dedup.json`. The water level count is the `count` field (integer), NOT the number of top-level keys. Example: `{"seen_hashes": [...], "count": 277, "updated_at": "..."}` means 277 hashes.
4. Read `intel-hub/state/<task_key>/health.json` for source health. For each source, report: `consecutive_failures`, `disabled`, `total_items_fetched`.

### /intel create <task_key>

Interactive: help the user build a new job spec YAML. Ask for:
1. Sources (type + URL/query for each)
2. Time window
3. Report kind
4. Filters (optional)

Write to `intel-hub/jobs/<task_key>.yml`.

---

## 5) Output Contract (STRICT)

### items.json

Each item MUST contain:
```json
{
  "url": "https://...",
  "title": "...",
  "source": "...",
  "publish_date": "YYYY-MM-DD",
  "excerpt": "≤300 chars",
  "signals": ["has_numbers", "has_benchmark"],
  "score": 1.5,
  "url_hash": "sha256hex"
}
```

Hard rule: `publish_date` is NEVER empty or null.

### report.md (weekly_intel)

Must contain in order:
1. Header with period, generated timestamp, source/item counts
2. Top 5 highlights (with importance stars)
3. Full timeline table (date | source | title | score)
4. Theme summary (3-6 clusters)
5. Silent sources list (configured sources with zero items)

### manifest.json

```json
{
  "task_key": "...",
  "run_id": "...",
  "started_at": "ISO",
  "completed_at": "ISO",
  "window_days": 7,
  "sources": [...],
  "stats": {
    "fetched": 120,
    "deduped": 15,
    "filtered_out": 30,
    "final": 75
  },
  "version": "0.1.0"
}
```

---

## 6) Cron Templates

Weekly AI intel (every Monday 9:00 UTC):
```
openclaw cron add \
  --name "intel:weekly-ai" \
  --cron "0 9 * * 1" \
  --tz "UTC" \
  --session isolated \
  --no-deliver \
  --message "Run /intel run weekly_ai_intel"
```

Daily quick scan (every day 08:00 UTC):
```
openclaw cron add \
  --name "intel:daily-scan" \
  --cron "0 8 * * *" \
  --tz "UTC" \
  --session isolated \
  --no-deliver \
  --message "Run /intel run <task_key>"
```

---

## 7) Degradation

- If a source fetch fails: log the error, record in health.json, continue with other sources.
- If all sources fail: produce empty items.json + report.md noting "No items collected."
- If dedup state is corrupted: start fresh (treat all items as new), log warning.
- If template is missing: fall back to weekly_intel.md.j2.
- Never block the entire pipeline on a single source failure.

---

## 8) Integration with Other Skills

After a pipeline run, output can be:
1. Pushed to Notion via `notion-writer`:
   `python3 skills/notion-writer/notion_push.py intel-hub/out/<task_key>/<run_id>/report.md --importance 高`
2. Imported and generated in NotebookLM via `notebooklm-importer`:
   `/skill notebooklm_importer run_all <task_key> <run_id> --to-notion --importance 高`
3. Used as source material for further analysis or content generation.
