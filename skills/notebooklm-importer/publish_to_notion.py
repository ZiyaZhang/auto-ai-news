#!/usr/bin/env python3
"""
publish_to_notion.py - Publish NotebookLM outputs to Notion.

Usage:
  python3 skills/notebooklm-importer/publish_to_notion.py <task_key> <run_id>
  python3 skills/notebooklm-importer/publish_to_notion.py <task_key> <run_id> --importance 高
  python3 skills/notebooklm-importer/publish_to_notion.py <task_key> <run_id> --title "weekly_ai_intel PPT归档"
  python3 skills/notebooklm-importer/publish_to_notion.py <task_key> <run_id> --no-interactive-capture
"""

import argparse
import pathlib
import re
import subprocess
import sys


def run_and_capture(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        print(output, file=sys.stderr)
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return output


def extract_notion_url(text):
    m = re.search(r"https://www\.notion\.so/[^\s)]+", text)
    return m.group(0) if m else ""


def capture_notebooklm_report(target_path):
    print("NotebookLM report text file is missing.")
    print(f"Please paste the full NotebookLM report now, then press Ctrl-D.")
    print(f"Target file: {target_path}")
    captured = sys.stdin.read()
    if not captured or not captured.strip():
        raise RuntimeError("No report text captured from stdin.")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(captured.rstrip() + "\n", encoding="utf-8")
    print(f"Captured report text -> {target_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_key")
    parser.add_argument("run_id")
    parser.add_argument("--importance", choices=["高", "中", "低"])
    parser.add_argument("--title", help="Optional slides archive page title")
    parser.add_argument(
        "--no-interactive-capture",
        action="store_true",
        help="Fail instead of prompting to paste NotebookLM report text when file is missing.",
    )
    args = parser.parse_args()

    root = pathlib.Path("intel-hub/out") / args.task_key / args.run_id
    exports = root / "notebooklm_exports"
    downloads = exports / "_downloads"
    notion_push = pathlib.Path("skills/notion-writer/notion_push.py")

    if not notion_push.exists():
        raise FileNotFoundError(f"notion-writer script not found: {notion_push}")
    if not exports.exists():
        raise FileNotFoundError(f"exports dir not found: {exports}")

    notebooklm_report_candidates = [
        exports / "notebooklm_report.md",
        exports / "report.md",
        exports / "report.txt",
    ]
    notebooklm_report = next((p for p in notebooklm_report_candidates if p.exists()), None)
    target = notebooklm_report_candidates[0]
    if not notebooklm_report:
        if args.no_interactive_capture:
            raise FileNotFoundError(
                "NotebookLM report text not found. "
                "Expected one of: "
                + ", ".join(str(p) for p in notebooklm_report_candidates)
                + ". After NotebookLM generates report, open it, copy full content, "
                "and save to notebooklm_exports/notebooklm_report.md."
            )
        if sys.stdin.isatty():
            capture_notebooklm_report(target)
            notebooklm_report = target
        else:
            raise FileNotFoundError(
                "NotebookLM report text not found and interactive capture unavailable. "
                "Provide notebooklm_exports/notebooklm_report.md first, "
                "or run in a tty without --no-interactive-capture."
            )
    report = notebooklm_report

    file_roots = [downloads, exports]
    files = []
    for file_root in file_roots:
        if file_root.exists():
            files.extend(sorted(file_root.glob("*.pptx")))
            files.extend(sorted(file_root.glob("*.pdf")))
    if not files:
        raise FileNotFoundError(f"No pptx/pdf found in {downloads} or {exports}")

    base = ["python3", str(notion_push)]

    report_cmd = base + [str(report)]
    if args.importance:
        report_cmd += ["--importance", args.importance]
    report_out = run_and_capture(report_cmd)
    report_url = extract_notion_url(report_out)

    slides_title = args.title or f"{args.task_key} {args.run_id} PPT归档"
    slides_cmd = base
    for f in files:
        slides_cmd += ["--attach", str(f)]
    slides_cmd += ["--title", slides_title]
    if args.importance:
        slides_cmd += ["--importance", args.importance]
    slides_out = run_and_capture(slides_cmd)
    slides_url = extract_notion_url(slides_out)

    print("PUBLISH_OK")
    print(f"task_key={args.task_key}")
    print(f"run_id={args.run_id}")
    print(f"report_source={report}")
    print(f"report_url={report_url}")
    print(f"slides_url={slides_url}")
    print("files=" + ",".join(str(f) for f in files))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"PUBLISH_FAILED: {e}", file=sys.stderr)
        sys.exit(1)
