# Auto AI News

Auto AI News is a human-supervised pipeline for weekly AI intelligence.

It does four jobs end to end:

1. Collect AI updates from feeds, blogs, papers, and community sources.
2. Deduplicate, filter, rank, and render a structured weekly report bundle.
3. Import the curated bundle into NotebookLM, then generate a Chinese report and slides.
4. Publish the NotebookLM report and exported PPT/PDF into Notion.

The repository is organized for OpenClaw, but the collection engine and Notion publisher can also be run directly from the command line.

## What is in this repo

- `intel-hub/`: the collection, ranking, rendering, and bundling engine.
- `skills/intel-job-runner/`: OpenClaw skill contract for collection.
- `skills/notebooklm-importer/`: OpenClaw skill contract for NotebookLM import, report generation, slide generation, export, and Notion handoff.
- `skills/notion-writer/`: Notion publisher with support for markdown pages and local file uploads.


## Architecture

```text
intel-hub/jobs/<task>.yml
  -> fetchers (rss/html_list/arxiv/sitemap/manual)
  -> date gate + dedup + filtering + ranking
  -> report.md + items.json + upload_bundle/
  -> NotebookLM import via browser skill
  -> NotebookLM report + slides generation
  -> notebooklm_report.md + exported pptx/pdf
  -> Notion publish
```

## Runtime model

This project is not fully unattended.

The NotebookLM stage is browser-driven and still requires human supervision for:

- Google login / CAPTCHA / MFA
- UI drift in NotebookLM
- Report text capture if NotebookLM does not expose a direct text export

Everything before and after that stage is scriptable.

## Prerequisites

- Python 3.12+
- OpenClaw with browser support enabled
- A Notion integration with access to the target database
- Optional: a shell loader for `.env` files

## Setup

### 1. Install Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r intel-hub/requirements.txt
```

### 2. Configure secrets

Copy `.env.example` to `.env` and set your values:

```bash
cp .env.example .env
```

Required env vars:

- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`

Load them into your shell before running the Notion publisher or starting OpenClaw.

### 3. Register the skills in OpenClaw

Copy or symlink these folders into your OpenClaw workspace skills directory:

- `skills/intel-job-runner`
- `skills/notebooklm-importer`
- `skills/notion-writer`

## Quickstart

### A. Run collection only

```bash
cd intel-hub
python3 -m src.job_runner weekly_ai_intel
```

Outputs land in:

```text
intel-hub/out/weekly_ai_intel/<run_id>/
```

### B. Run the full OpenClaw workflow

```text
/skill notebooklm_importer run_all weekly_ai_intel --to-notion --importance 高
```

Expected flow:

1. Collect sources via `intel-hub`
2. Import all sources into a new NotebookLM notebook
3. Set language to `中文（简体）`
4. Rewrite the NotebookLM popup prompt for report and slides
5. Click NotebookLM `生成` for report and slides
6. Save NotebookLM report text to `notebooklm_exports/notebooklm_report.md`
7. Generate `notebooklm_exports/slides_publish.md` for the slides page intro
8. Prefer slide images in `notebooklm_exports/slides_images/` for direct reading in Notion
9. If `slides_images/` is missing, publisher auto-attempts PDF->images conversion (`pdftoppm` first, `ImageMagick` second)
10. Export PPTX/PDF to `notebooklm_exports/_downloads/`
11. Create new Notion pages for the report and slides archive

## Key output contract

For a run to be considered complete, these files should exist:

- `intel-hub/out/<task_key>/<run_id>/items.json`
- `intel-hub/out/<task_key>/<run_id>/manifest.json`
- `intel-hub/out/<task_key>/<run_id>/upload_bundle/`
- `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/notebooklm_report.md`
- `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/slides_publish.md`
- `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/slides_images/` when slide images are available
- `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/_downloads/*.pptx` or `*.pdf`

The root `intel-hub/out/<task_key>/<run_id>/report.md` is the local collection report. It is not the default Notion handoff target for NotebookLM publishing.

The preferred Notion page structure is:

1. A report page built from `notebooklm_report.md`
2. A slides page built from `slides_publish.md`
3. Sequential image blocks from `slides_images/`
4. Original PDF/PPTX attachments at the end of the slides page

## Repository layout

```text
auto-ai-news/
├── .env.example
├── .gitignore
├── README.md
├── intel-hub/
│   ├── jobs/
│   ├── src/
│   └── templates/
└── skills/
    ├── intel-job-runner/
    ├── notebooklm-importer/
    └── notion-writer/
```

## Privacy and release policy

Before publishing this repository, run a secret scan and verify that none of the following are present:

- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`
- local `.env` files
- `intel-hub/out/` artifacts
- `intel-hub/state/` and `intel-hub/import_state/`
- OpenClaw local config files
- usernames or home-directory paths

## Limitations

- NotebookLM UI automation is brittle by nature and may require skill updates after UI changes.
- Notion publishing depends on your database schema matching the expected fields.
- Some source sites may block direct import in NotebookLM; the workflow prefers file-based upload bundles to mitigate that.

## License

MIT
