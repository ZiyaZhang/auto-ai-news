---
name: notebooklm-importer
description: Semi-automated browser-based importer for NotebookLM. Uploads intel-hub output bundles into NotebookLM notebooks via UI automation. Supports batch uploads, breakpoint resume, and human-in-the-loop for auth. Use for importing research sources, reports, or any collected materials into NotebookLM.
metadata: {"openclaw":{"emoji":"📓","skillKey":"notebooklm-importer","requires":{"config":["browser.enabled"]}}}
---

# notebooklm-importer

You are a NotebookLM import automation that uploads intel-hub output into NotebookLM notebooks via browser UI.

Core behavior:
- Each execution run (`task_key` + `run_id`) MUST create a NEW NotebookLM notebook.
- Uploads are batched (default 20 items) to avoid UI timeouts.
- State is persisted for breakpoint resume after interruptions.
- Login/CAPTCHA/MFA requires human intervention — pause and wait.
- Generation is allowed only after ALL sources/links for this run are uploaded and verified.

Hard rules:
- Never store Google credentials or tokens.
- Never bypass authentication prompts — always pause for human.
- Always verify upload success before marking items as imported.
- Never run in unattended cron — this is a human-supervised skill.
- Never reuse an old notebook for a new run_id.
- Never append to an old Notion page for a new run_id.
- Never generate report/slides before source import reaches 100% for the run.
- For `--to-notion`, use a fixed default publish set without asking follow-up questions:
  - Always publish NotebookLM-generated report text as the report page.
  - Preferred file path: `notebooklm_exports/notebooklm_report.md`.
  - Always publish a slides 图文归档 page (preferred: `slides_images/*`) and keep `_downloads/*.pptx|*.pdf` as attachments.
  - Do not publish `slides.md` or ad-hoc summary text unless explicitly requested by user.
- Notion destination MUST come from environment (`NOTION_DATABASE_ID`) only.
  - Ask user for a Notion link/database only when required env vars are missing.

---

## 1) State Machine

The importer follows a strict state machine. Each state transition is persisted
to `intel-hub/import_state/<task_key>.json` (workspace-relative) so the process can resume from any point.

```
INIT → NAVIGATE → CHECK_AUTH → [WAIT_HUMAN_AUTH] → FIND_NOTEBOOK
  → CREATE_NOTEBOOK → UPLOAD_BATCH → VERIFY_UPLOAD → DONE
```

Optionally, the skill can run a generation phase after import:

```
DONE → GENERATE_INIT → PROMPT_EVIDENCE_JSON → PROMPT_ARTIFACT
  → CLICK_GENERATE → VERIFY_ARTIFACT → ENSURE_DOWNLOAD_DIR
  → EXPORT_ARTIFACT → VERIFY_EXPORT → [PUBLISH_NOTION] → DONE
```

### State Definitions

| State | Description | Next | Human needed? |
|-------|-------------|------|---------------|
| `INIT` | Load import config, validate bundle exists | NAVIGATE | No |
| `NAVIGATE` | Open NotebookLM in browser | CHECK_AUTH | No |
| `CHECK_AUTH` | Detect if logged in or login page shown | FIND_NOTEBOOK or WAIT_HUMAN_AUTH | Maybe |
| `WAIT_HUMAN_AUTH` | Pause — user handles login/CAPTCHA/MFA | CHECK_AUTH (on resume) | YES |
| `FIND_NOTEBOOK` | Validate whether run-specific notebook already exists | UPLOAD_BATCH or CREATE_NOTEBOOK | No |
| `CREATE_NOTEBOOK` | Create new notebook titled with run_id | UPLOAD_BATCH | No |
| `UPLOAD_BATCH` | Upload next batch of items (URLs or files) | VERIFY_UPLOAD | No |
| `VERIFY_UPLOAD` | Confirm items appear in notebook sources | UPLOAD_BATCH or DONE | No |
| `DONE` | All items imported, write final state | — | No |
| `GENERATE_INIT` | Navigate to the generation UI (Studio panel) | PROMPT_EVIDENCE_JSON | No |
| `PROMPT_EVIDENCE_JSON` | Clear default prompt, paste Guardrails + Evidence JSON prompt, send | PROMPT_ARTIFACT | No |
| `PROMPT_ARTIFACT` | Clear prompt again, paste artifact prompt, send | CLICK_GENERATE | No |
| `CLICK_GENERATE` | Click NotebookLM "Generate Report/Slides" UI | VERIFY_ARTIFACT | No |
| `VERIFY_ARTIFACT` | Confirm artifact exists and has citations | ENSURE_DOWNLOAD_DIR | No |
| `ENSURE_DOWNLOAD_DIR` | Force browser download location to workspace export folder | EXPORT_ARTIFACT | No |
| `EXPORT_ARTIFACT` | Export/download NotebookLM-native artifact (PPTX/PDF where available) | VERIFY_EXPORT | No |
| `VERIFY_EXPORT` | Validate recent download entries and persist export metadata | PUBLISH_NOTION or DONE | No |
| `PUBLISH_NOTION` | Push report and exported files to Notion via notion-writer | DONE | No |

---

## 2) Storage

Import state: `intel-hub/import_state/<task_key>.json`

Path conventions:
- Use workspace-relative paths for run/state files.
- Use `{baseDir}` when referencing files inside this skill directory.
- Notion bridge script: `{baseDir}/publish_to_notion.py`

```json
{
  "task_key": "weekly_ai_intel",
  "run_id": "20260228T120000",
  "state": "UPLOAD_BATCH",
  "notebook_url": "https://notebooklm.google.com/notebook/...",
  "imported_hashes": ["abc123...", "def456..."],
  "pending_hashes": ["ghi789..."],
  "batch_index": 2,
  "batch_size": 20,
  "total_items": 75,
  "download_dir": "intel-hub/out/weekly_ai_intel/20260228T120000/notebooklm_exports/_downloads/",
  "exports": [
    {
      "file_name": "weekly_ai_intel_20260228_slides.pdf",
      "download_status": "completed",
      "timestamp": "2026-02-28T12:44:12Z"
    }
  ],
  "last_updated": "2026-02-28T12:30:00Z",
  "error": null
}
```

---

## 3) Commands

Slash command note: OpenClaw normalizes skill names for `/skill`, so `notebooklm-importer` becomes `notebooklm_importer`.

### `/skill notebooklm_importer import <task_key> [run_id]`

Start or resume an import for the given task.

Steps:
1. If `run_id` is omitted, find the latest run: `ls -t intel-hub/out/<task_key>/`
2. Load `intel-hub/out/<task_key>/<run_id>/items.json`
3. Load existing import state (if any) from `intel-hub/import_state/<task_key>.json`
4. If state exists and `state != DONE`, resume from the saved state.
5. If no state or state is DONE with different run_id, start fresh.
6. Execute the state machine (see Section 4).

Notebook creation rule:
- Notebook title MUST include `run_id` and source coverage date range.
  Example: `Intel: weekly_ai_intel 20260302T173524 (2.27-3.3)`.
- If a same-title notebook already exists for that same run_id, it may be resumed.
- For a new run_id, always create a new notebook.

### `/skill notebooklm_importer status <task_key>`

Show import progress:
1. Read `intel-hub/import_state/<task_key>.json`
2. Print: state, imported/total counts, notebook URL, last error.

### `/skill notebooklm_importer resume <task_key>`

Resume after human intervention (login/CAPTCHA):
1. Read import state, verify state is WAIT_HUMAN_AUTH.
2. Transition to CHECK_AUTH and continue the state machine.

### `/skill notebooklm_importer reset <task_key>`

Clear import state for the task (start fresh on next import):
1. Delete `intel-hub/import_state/<task_key>.json`

### `/skill notebooklm_importer produce <task_key> <run_id> --mode report|slides`

Generate a Report or Slides inside the NotebookLM notebook after import.

Hard behavior:
- ALWAYS determine `WEEK_RANGE` before generation:
  - Prefer `intel-hub/out/<task_key>/<run_id>/manifest.json` date fields.
  - Fallback to "过去7天（若不足扩展至14天）".
- ALWAYS include `WEEK_RANGE` in generation prompts and slide 1 cover.
- ALWAYS clear the default prompt/input area before pasting new prompts.
- ALWAYS send the prompt text first, THEN click NotebookLM's Generate UI.
- NEVER assume citations are correct; verify artifacts include citations and URLs.
- For `--mode slides`, output MUST come from NotebookLM Slides generation/export UI.
- For `--mode slides`, slide content MUST be Chinese only (titles, bullets, speaker notes, and exported artifact text).
- For `--mode report`, report content MUST be Chinese only (headings, body text, summaries, and citations context text).
- Do NOT replace NotebookLM slides with local Marp/reveal.js/Keynote generation unless the user explicitly asks for fallback.
- If `--to-notion` is enabled, push outputs to Notion after export:
  - report mode: push NotebookLM report text from `notebooklm_exports/notebooklm_report.md`.
  - slides mode: push a 图文归档页:
    - insert `notebooklm_exports/slides_images/` as sequential image blocks when available
    - append exported `pptx/pdf` files as downloadable attachments
    - use `notebooklm_exports/slides_publish.md` as the page intro and metadata source
  - default publish scope is fixed: `notebooklm_exports/notebooklm_report.md` + `notebooklm_exports/slides_publish.md` + `notebooklm_exports/_downloads/*.{pptx,pdf}`.
  - do not ask user to choose between `report.md/slides.md/摘要` unless user explicitly requests override.

Additional flags:
- `--to-notion` Enable automatic Notion publishing after export.
- `--importance 高|中|低` Optional Notion field passed to notion-writer.
- `--notion-title <text>` Optional title override for the Notion page in slides mode.

No-question default for `--to-notion`:
- If `NOTION_TOKEN` and `NOTION_DATABASE_ID` are present, proceed directly.
- Do not ask for Notion page/database link when env vars already exist.
- If either env var is missing, stop with actionable error and request user to set env.

### `/skill notebooklm_importer run_all <task_key> [run_id] [--to-notion] [--importance 高|中|低]`

Run full pipeline in one entrypoint:
1. Trigger intel collection (or reuse provided run_id).
2. Import bundle into NotebookLM.
3. Generate report and slides in NotebookLM.
4. Export NotebookLM artifacts.
5. Optionally publish to Notion when `--to-notion` is set.

Hard behavior:
- `run_id` MUST be shared across all steps.
- If `run_id` is omitted, resolve latest from `intel-hub/out/<task_key>/` after run.
- On partial failure, persist state and print restart command with same run_id.
- `run_all` generation order is strict:
  1) import all sources/links and verify completion
  2) generate NotebookLM report first
  3) open the generated report, copy full text, save `notebooklm_exports/notebooklm_report.md`
  4) generate NotebookLM slides
  5) export
  6) verify export files and report handoff file exist
  7) publish to Notion (optional)
- `run_all` MUST NOT skip directly from import to Notion publish using root `intel-hub/.../report.md`.
- `run_all` MUST operate NotebookLM UI for BOTH artifacts:
  - choose `中文（简体）`
  - clear and rewrite the popup prompt
  - click the NotebookLM `生成` button for report
  - repeat for slides

Recommended workflow:
```
/skill intel_job_runner run weekly_ai_intel
/skill notebooklm_importer import weekly_ai_intel 20260302T173524
/skill notebooklm_importer produce weekly_ai_intel 20260302T173524 --mode report
/skill notebooklm_importer produce weekly_ai_intel 20260302T173524 --mode slides
/skill notebooklm_importer run_all weekly_ai_intel --to-notion --importance 高
```

---

## 4) Browser Execution Protocol

### NAVIGATE

```
1. Open `https://notebooklm.google.com` in the browser tool.
2. Wait briefly for page load.
3. Take a snapshot to capture page state.
4. Transition → CHECK_AUTH
```

### CHECK_AUTH

```
1. Take a snapshot.
2. Look for indicators:
   - Login page: presence of Google sign-in form, "Sign in" button
   - Logged in: presence of notebook list, "New notebook" button, user avatar
3. If logged in → FIND_NOTEBOOK
4. If login page → WAIT_HUMAN_AUTH
```

### WAIT_HUMAN_AUTH

```
1. Save state with state=WAIT_HUMAN_AUTH
2. Print to user:
   "⏸ NotebookLM requires authentication.
    Please sign in to your Google account in the browser.
    When done, run: /skill notebooklm_importer resume <task_key>"
3. STOP execution. Do NOT poll or auto-retry.
```

### FIND_NOTEBOOK

```
1. Take a snapshot to see the notebook list.
2. Search for notebook title EXACTLY matching run-scoped title:
   - `Intel: <task_key> <run_id> (<MM.DD-MM.DD>)`
3. If found:
   a. Click the notebook.
   b. Wait briefly.
   c. Record notebook_url in state
   d. Transition → UPLOAD_BATCH
4. If not found → CREATE_NOTEBOOK
```

### CREATE_NOTEBOOK

```
1. Click "New notebook" / "+".
2. Wait briefly.
3. Resolve source coverage date range from `manifest.json`:
   - prefer `date_from/date_to`
   - fallback to derived item date min/max
   - fallback text: `dates-unknown`
4. Set notebook title to:
   - `Intel: <task_key> <run_id> (<MM.DD-MM.DD>)`
   - example: `Intel: weekly_ai_intel 20260302T173524 (2.27-3.3)`
4. Wait briefly.
5. Record notebook_url in state
6. Transition → UPLOAD_BATCH
```

### UPLOAD_BATCH

```
1. Prefer file uploads when available (higher success for paywalls / blocked sites):
   a. If upload_bundle/sources.md exists and not yet uploaded for this run:
      - Add source → File, upload sources.md
      - Mark a special state flag "uploaded_sources_md": true
      - Transition → VERIFY_UPLOAD
   b. If upload_bundle/items/ exists:
      - Upload per-item .md files in batches (default 20) via Add source → File
      - Mark those items as imported by matching filename index or embedded URL hash
      - Transition → VERIFY_UPLOAD
2. Fallback to website URLs:
   a. Read items.json, skip items whose url_hash is in imported_hashes
   b. Take next batch_size items (default 20)
   c. For each item in batch:
      - Add source → Website, paste item.url, submit, wait 1-2 seconds
   d. Save state and transition → VERIFY_UPLOAD
```

### VERIFY_UPLOAD

```
1. Take a snapshot.
2. Check that the newly added sources appear in the sources panel
3. Move pending_hashes → imported_hashes
4. If more items remain → UPLOAD_BATCH
5. If all items imported:
   - set state flag `sources_upload_complete=true`
   - transition → DONE
```

### DONE

```
1. Save state with state=DONE
2. Print summary: "✓ Imported X/Y items into notebook <task_key>"
3. Print notebook_url for user reference
```

### GENERATE_INIT

```
1. Ensure we are inside the notebook for <task_key>.
2. Verify `sources_upload_complete=true` for this run.
   - If false/missing: STOP and return to upload flow.
2. Take a snapshot.
3. Open the Report/Slides generation surface (Studio panel).
4. Do not rely on the chat input box for generation instructions.
5. If a "Custom script / 自定义演示文稿" dialog is shown, operate inside that dialog only.
6. Validate required UI anchors before continuing:
   - Dialog title: `自定义演示文稿`
   - Format cards: `详细演示文稿` and `演示用幻灯片`
   - Language label: `选择语言`
   - Length label: `时长` with `短/默认`
   - Prompt label: `请描述您要创建的演示文稿`
   - Generate button: `生成`
7. If any anchor is missing, STOP and save an error for human intervention.
8. Resolve `WEEK_RANGE`:
   - Try reading `intel-hub/out/<task_key>/<run_id>/manifest.json` for date_from/date_to or equivalent.
   - If unavailable, set `WEEK_RANGE` = "过去7天（若不足扩展至14天）".
9. Persist `WEEK_RANGE` in state for downstream prompts.
10. Transition → PROMPT_EVIDENCE_JSON
```

### PROMPT_EVIDENCE_JSON

```
1. Take a snapshot.
2. Locate the Report/Slides instruction input field in the generation panel/dialog.
3. Enforce language before prompt:
   - Find language selector (`选择语言` / `Language`).
   - Set to `中文（简体）`.
   - Re-snapshot and verify selected value is still `中文（简体）`.
4. CLEAR IT COMPLETELY:
   - Select all (Cmd+A) and delete/backspace until empty
   - If text remains, click field and repeat Cmd+A + Delete
   - If template chips/default blocks exist, remove them via clear (`×`) then repeat Cmd+A + Delete
   - Verify no user text remains in a new snapshot (placeholder hint text is acceptable)
5. Paste Guardrails + Evidence JSON prompt (see Section 10)
6. Click "Send" / press Enter
7. Wait for NotebookLM to return JSON
8. Transition → PROMPT_ARTIFACT
```

### PROMPT_ARTIFACT

```
1. Take a snapshot.
2. Set format card by mode:
   - `--mode slides` => select `演示用幻灯片`
   - `--mode report` => select `详细演示文稿`
3. Re-check language selector and force `中文（简体）` again for BOTH modes (some dialogs reset language between steps).
   - `--mode report`: must stay `中文（简体）` before clicking `生成`.
   - `--mode slides`: must stay `中文（简体）` before clicking `生成`.
4. CLEAR the generation-panel instruction field completely again (Cmd+A, delete) to avoid prompt mixing
5. Paste the artifact prompt for the chosen mode:
   - report: Weekly report/newsletter prompt
   - slides: 10–12 page PPT prompt, explicitly requesting NotebookLM-native Slides output (not local markdown deck)
6. Verify pasted content starts with Chinese instructions (not previous default prompt text).
7. Send it
8. Transition → CLICK_GENERATE
```

### CLICK_GENERATE

```
1. Take a snapshot.
2. Click the appropriate NotebookLM button/menu:
   - "Generate report" / "Report"
   - "Generate slides" / "Slides"
   - In Chinese UI this is usually `生成`.
3. Wait for generation to finish
4. Transition → VERIFY_ARTIFACT
```

### VERIFY_ARTIFACT

```
1. Take a snapshot.
2. Verify:
   - Output exists (report text or slide outline)
   - For report mode: language is Chinese across headings and body text
   - For slides mode: language is Chinese across headings and bullet text
   - Each major section has citations / URLs (as required by Guardrails)
   - No obvious hallucinated numbers/dates
   - No leakage of default template prompt wording in final output
3. If missing citations or obviously wrong:
   - Send a short correction prompt: "Missing citations; regenerate strictly with (title|date|URL) for every claim."
   - Re-run CLICK_GENERATE once
4. If `--mode report`:
   - Open the generated NotebookLM report artifact/card.
   - Do NOT use root `intel-hub/out/<task_key>/<run_id>/report.md` here; that file is from intel-hub, not NotebookLM.
   - Copy the FULL report body from NotebookLM UI.
   - Save to `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/notebooklm_report.md`.
   - This is mandatory before any Notion publish.
5. If `--mode slides` and NotebookLM shows an outline/notes view:
   - Optionally save text outline to `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/notebooklm_slides_outline.md`.
6. Transition → ENSURE_DOWNLOAD_DIR
```

### ENSURE_DOWNLOAD_DIR

```
1. Create local export download dir (workspace-relative):
   - `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/_downloads/`
2. Open browser settings page for downloads:
   - Navigate to `chrome://settings/downloads`
3. Find `Location/下载位置` row:
   - Click `Change/更改`
   - Select the workspace folder above
4. Disable `Ask where to save each file/下载前询问保存位置` if present (reduces dialogs).
5. Take snapshot and confirm the download location is set.
6. Persist `download_dir` to state.
7. Transition → EXPORT_ARTIFACT
```

### EXPORT_ARTIFACT  (after ENSURE_DOWNLOAD_DIR)

```
1. Take a snapshot.
2. Open NotebookLM artifact actions (Share/Export/Download).
3. For `--mode slides`:
   - Prefer Download/Export as PPTX if available.
   - If PPTX is unavailable, export PDF from NotebookLM UI.
4. For `--mode report`:
   - Export/download report text/PDF from NotebookLM UI if available.
5. Save exported files under workspace path:
   - `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/_downloads/`
6. Record NotebookLM notebook URL in state.
7. Report text handoff for Notion:
   - Open generated NotebookLM report in UI.
   - Copy full report body.
   - Save to `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/notebooklm_report.md`.
   - This file is the only default report source for Notion publish.
   - Never substitute root `intel-hub/out/<task_key>/<run_id>/report.md`.
8. Transition → VERIFY_EXPORT
```

### VERIFY_EXPORT

```
1. Navigate to `chrome://downloads`.
2. Take snapshot and verify a recent download entry exists (`pptx` or `pdf`).
3. Record each entry into state `exports[]`:
   - `file_name`
   - `download_status` (`completed`/`failed`)
   - `timestamp`
4. If any required download failed:
   - Pause for human; do not retry endlessly.
5. If slide images are available or can be generated locally from exported PDF:
   - Prefer saving per-slide images under `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/slides_images/`
   - Filename convention: `slide-01.png`, `slide-02.png`, ...
   - These images are the preferred Notion reading format.
   - Bridge script will auto-attempt PDF -> images conversion (pdftoppm first, ImageMagick second).
   - If no converter exists, continue with file attachments and emit a warning.
6. If `--to-notion` is enabled: transition → PUBLISH_NOTION
7. Otherwise mark success and transition → DONE
```

### PUBLISH_NOTION

```
1. Validate env vars exist: NOTION_TOKEN and NOTION_DATABASE_ID.
   - If present: proceed without asking user for destination link/page.
   - If missing: stop and ask user to provide env vars (not ad-hoc page URL).
2. Run bridge script:
   - `python3 {baseDir}/publish_to_notion.py <task_key> <run_id> [--importance ...] [--title ...]`
   - If `notebooklm_exports/notebooklm_report.md` is missing, script pauses for interactive paste:
     1) open NotebookLM generated report
     2) copy full text
     3) paste into terminal, Ctrl-D to continue
   - To disable interactive capture and fail fast:
     `python3 {baseDir}/publish_to_notion.py <task_key> <run_id> --no-interactive-capture`
   - Bridge script MUST NOT fall back to root `intel-hub/out/<task_key>/<run_id>/report.md`.
3. Enforce new-page rule:
   - report publish MUST create a new Notion page each execution.
   - slides publish MUST create a new Notion 图文归档 page each execution.
   - recommended default title: `<task_key> <run_id> PPT图文归档`.
4. Enforce fixed default content set:
   - report page source: `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/notebooklm_report.md`
   - slides page intro source: `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/slides_publish.md`
   - slides readable images: `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/slides_images/*`
   - slides archive attachments: `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/_downloads/*.{pptx,pdf}`
   - do not switch to root `report.md`, `slides.md`, or summary text unless user explicitly asks.
   - root `intel-hub/out/<task_key>/<run_id>/report.md` is intel-hub output, not NotebookLM output, and MUST NOT be used as the default Notion report source.
5. Persist returned Notion page URLs in state:
   - `notion_report_url`
   - `notion_slides_url`
6. Mark success and transition → DONE
```

---

## 5) Error Handling

| Error | Action |
|-------|--------|
| Page timeout | Retry once, then save state and pause |
| "Rate limit" or "Too many requests" | Wait 60 seconds, retry |
| Source already exists | Skip (mark as imported) |
| Unknown UI element | Save state with error, pause for human |
| Browser crash | State is already saved — user runs `/skill notebooklm_importer resume` |
| Download path remains `~/Downloads` | Stop and re-run ENSURE_DOWNLOAD_DIR; do not export until workspace path is confirmed |
| Download failed in `chrome://downloads` | Pause for human; do not retry endlessly |
| Notion env missing | Skip publish step with actionable error (`NOTION_TOKEN`/`NOTION_DATABASE_ID`) |
| Notion upload fails | Keep exported files, save publish error, suggest re-run with same run_id |

On any unrecoverable error:
1. Save current state with `error` field populated
2. Print the error and suggest `/skill notebooklm_importer resume <task_key>`
3. STOP — do not retry blindly

---

## 6) Configuration

Batch size and other settings can be overridden per invocation:

```
/skill notebooklm_importer import weekly_ai_intel --batch-size 10
```

Default settings:
- `batch_size`: 20
- `wait_between_items`: 1.5 seconds
- `wait_between_batches`: 5 seconds
- `max_retries_per_item`: 2

---

## 7) Notebook Naming Convention

| Job kind | Notebook title |
|----------|---------------|
| `weekly_intel` | `Intel: <task_key> <run_id> (<MM.DD-MM.DD>)` |
| `investment_memo` | `Research: <task_key> <run_id> (<MM.DD-MM.DD>)` |
| `company_dossier` | `Dossier: <task_key> <run_id> (<MM.DD-MM.DD>)` |

Example: task_key `weekly_ai_intel`, run_id `20260302T173524`, source coverage `2.27-3.3` → notebook titled `Intel: weekly_ai_intel 20260302T173524 (2.27-3.3)`

---

## 8) Integration

This skill reads output from `intel-job-runner`:
- `intel-hub/out/<task_key>/<run_id>/items.json` — source material
- `intel-hub/out/<task_key>/<run_id>/upload_bundle/sources.md` — alternative paste source

Typical workflow:
```
/skill intel_job_runner run weekly_ai_intel      # Stage A: produce bundle
/skill notebooklm_importer import weekly_ai_intel # Stage B: import to NotebookLM
/skill notebooklm_importer run_all weekly_ai_intel --to-notion --importance 高 # Stage A->D one command
```

Notion publishing contract:
- Report source: `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/notebooklm_report.md`
- Slides page intro: `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/slides_publish.md`
- Slides images: `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/slides_images/*`
- Slides exports: `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/_downloads/*.{pptx,pdf}`
- Publisher bridge: `skills/notebooklm-importer/publish_to_notion.py`
- Underlying writer: `skills/notion-writer/notion_push.py`
- `intel-hub/out/<task_key>/<run_id>/report.md` is the local intel-hub weekly report and is not the default NotebookLM report handoff target.

---

## 9) Degradation

- If items.json is missing: error immediately, do not proceed.
- If NotebookLM UI changes: state machine will fail at the changed step.
  Save state + error, pause. The SKILL.md browser steps can be updated.
- If Google account has no NotebookLM access: detect and inform user.
- Never auto-create a Google account or bypass access controls.
- If NotebookLM does not expose PPTX/PDF export in current UI/account:
  - Report this explicitly and pause for user decision.
  - Do not silently switch to local slide toolchains.
- If Notion publish fails:
  - Keep local exports and report URLs/paths for manual retry.
  - Provide exact retry command with `run_id`.

---

## 10) Prompt Packs (Copy/Paste)

These prompts are designed for human-supervised automation. The agent MUST clear the default prompt before pasting.

### 10.1 Guardrails (always paste first)

Paste this block at the start of every generation run:

```
You can ONLY use Sources imported into this Notebook.
Do NOT fabricate model versions, release dates, benchmark numbers, funding amounts, or quotes.
If a claim cannot be verified in Sources, write: \"未在资料中验证\".
Every factual claim MUST include a citation at the end in this exact format:
(source_title | published_date | URL)
If NotebookLM only provides citation numbers, keep those inline and append a References list with (source_title | published_date | URL).
Forum/aggregators (Hacker News, Reddit) are \"signals/leads\" only; do not treat as facts unless corroborated by official/primary sources.
Noise filter: marketing-only, reposts, no substantive update, no data/details, or no explicit publish date => exclude.
Time window: prefer last 7 days; if insufficient, expand to last 14 days; output in reverse chronological order.
Priority: official/primary sources > reputable research/media > HN/Reddit.
Before finalizing, self-check: every conclusion must be supported by at least one cited source.
Top5 selection rule: prioritize sources with effective weight >= 1.3. HN/Reddit can enter Top5 only with at least one corroborating official/primary source.
```

### 10.2 Prompt 1: Evidence Table (JSON)

Use this to force NotebookLM to produce a structured, machine-readable evidence table.

```
TASK: From the Sources in this notebook, extract the most important AI updates in the last 7 days (expand to 14 if needed).
De-duplicate: merge the same event across multiple sources into ONE item with multiple evidence entries.
OUTPUT: exactly one fenced `json` code block containing a JSON array (no extra prose). Each item MUST contain:
- date (YYYY-MM-DD)
- title
- category (one of: 模型/产品, 基准评测, 推理系统, 开源生态, 投融资/商业, 政策治理, 安全, 科研论文/突破)
- summary_cn (<= 80 chars)
- takeaway_cn (<= 40 chars)
- evidence (array, >= 1). Each evidence item:
  - source_title
  - source_url
  - published_date
  - one_sentence_evidence
- confidence (high|medium|low). If only HN/Reddit without corroboration => low.
RULES:
- If you cannot find an explicit publish date in the source, exclude it.
- Do NOT add any information not present in Sources.
Return only one `json` fenced code block.
```

### 10.3 Prompt 2: Weekly Report / Newsletter (Markdown, Modular Weekly Scan)

```
【输出语言】中文（简体）
【类型】周更 AI 资讯扫描周报（时间范围：{WEEK_RANGE}；不足可扩展至14天但需标注）
【目标】生成一份可发布的 Newsletter/技术论坛周报（结构清晰、可引用核验）

【先整理再写作】
先按模块归类并去重合并（同一事件多来源合并为1条）：
技术 / B端产品 / C端产品 / 市场 / 治理与安全

【输出结构（必须按此顺序，Markdown）】
A. 一句话主结论（<=40字）
B. 本周三大结论（3条，每条附引用）
C. Top 5 看板表（时间倒序）
   列：重要度⭐｜发布日期｜模块｜标题｜摘要<=80字｜Takeaway<=40字｜引用
D. 模块化全量清单（时间倒序）
   每个模块下列出本周全部条目（每条都带引用）
E. 争议/不确定性（2-3条，分别给引用）
F. 下周关注（5条，引用或标“待验证”）
G. 引用索引（按机构/域名分组列出：标题｜日期｜URL）

【引用硬规则】
每条事实性陈述必须带引用：(来源标题 | 发布日期 | URL)
若 NotebookLM 只给编号引用，必须在末尾补齐 References 列表（标题｜日期｜URL）

【过滤规则】
无明确发布日期/纯营销/转载/无实质变更 一律剔除。
输出 Markdown only.
```

### 10.4 Prompt 3: Slides Prompt (Modular Weekly Scan, 10-12 pages)

```
将本段粘贴到 NotebookLM 弹窗“请描述您要创建的演示文稿”输入框，不要发到 chat。
【输出语言】中文（简体）
【类型】周更AI资讯扫描（过去7天；不足可扩展至14天但必须标注）
【目标】10–12页 演示用幻灯片，5–8分钟讲完，结构清晰、模块化

【先整理再输出】
把更新先按模块归类并合并同一事件多来源：
1 技术：模型/训练/推理/评测/开源框架
2 B端产品：企业AI/开发者工具/Agent工作流/平台
3 C端产品：消费者AI应用/搜索/助手/创作
4 市场：投融资/并购/商业化/价格/竞争（HN/Reddit仅线索）
5 治理与安全：政策/标准/安全事件/红队

【PPT结构】
1封面(过去7天+一句主结论)
2三大结论
3Top5速览
4技术 5B端 6C端 7市场 8治理与安全
9争议/不确定性 10下周关注 11引用索引

【每页硬约束】
标题1行 + 要点<=3条(<=18字) + 讲者备注60–120字(解释why it matters)
讲者备注末尾必须列出>=2条参考：(来源标题 | 发布日期 | URL)
无证据写“未在资料中验证”
```

---

## 11) End-to-End Test Plan

### Preflight

```
python3 skills/notion-writer/notion_push.py --test
ls intel-hub/config/tasks/weekly_ai_intel.yaml
```

### Full chain (one command)

```
/skill notebooklm_importer run_all weekly_ai_intel --to-notion --importance 高
```

Expected artifacts:
- `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/notebooklm_report.md`
- `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/slides_publish.md`
- `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/slides_images/` when image export exists
- `intel-hub/out/<task_key>/<run_id>/notebooklm_exports/_downloads/` contains `pptx` or `pdf`
- Import state has notebook URL and Notion page URLs

### Resume test

1. Interrupt at NotebookLM login.
2. Complete login manually.
3. Resume:
```
/skill notebooklm_importer resume <task_key>
```

### Notion retry test

If publish failed, rerun only publish commands:
```
python3 skills/notebooklm-importer/publish_to_notion.py <task_key> <run_id> --importance 高
```
