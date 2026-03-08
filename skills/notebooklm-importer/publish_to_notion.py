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
import shutil
import subprocess
import sys
from datetime import datetime, timezone


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


def natural_sort_key(value):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def collect_image_files(images_dir):
    exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    if not images_dir.exists():
        return []
    return sorted(
        [p for p in images_dir.iterdir() if p.is_file() and p.suffix.lower() in exts],
        key=lambda p: natural_sort_key(p.name),
    )


def normalize_slide_image_names(images_dir):
    image_files = collect_image_files(images_dir)
    if not image_files:
        return []
    width = max(2, len(str(len(image_files))))
    temp_paths = []
    for idx, src in enumerate(image_files, start=1):
        temp = images_dir / f".tmp-slide-{idx:04d}{src.suffix.lower()}"
        src.rename(temp)
        temp_paths.append(temp)
    normalized = []
    for idx, temp in enumerate(temp_paths, start=1):
        dst = images_dir / f"slide-{idx:0{width}d}{temp.suffix.lower()}"
        temp.rename(dst)
        normalized.append(dst)
    return normalized


def try_convert_pdf_with_pdftoppm(pdf_path, images_dir):
    tool = shutil.which("pdftoppm")
    if not tool:
        return False
    prefix = images_dir / "slide"
    proc = subprocess.run(
        [tool, "-png", "-r", "180", str(pdf_path), str(prefix)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        return False
    return bool(collect_image_files(images_dir))


def try_convert_pdf_with_imagemagick(pdf_path, images_dir):
    for tool_name in ("magick", "convert"):
        tool = shutil.which(tool_name)
        if not tool:
            continue
        target = images_dir / "slide-%03d.png"
        proc = subprocess.run(
            [tool, "-density", "180", str(pdf_path), str(target)],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and collect_image_files(images_dir):
            return True
        if proc.stderr:
            print(proc.stderr.strip(), file=sys.stderr)
    return False


def ensure_slides_images(slides_images, attachments):
    image_files = collect_image_files(slides_images)
    if image_files:
        return normalize_slide_image_names(slides_images)

    pdf_files = [p for p in attachments if p.suffix.lower() == ".pdf"]
    if not pdf_files:
        return []

    slides_images.mkdir(parents=True, exist_ok=True)
    source_pdf = pdf_files[0]
    converted = (
        try_convert_pdf_with_pdftoppm(source_pdf, slides_images)
        or try_convert_pdf_with_imagemagick(source_pdf, slides_images)
    )
    if not converted:
        print(
            "WARN: could not auto-convert PDF to slide images (needs pdftoppm or ImageMagick).",
            file=sys.stderr,
        )
        return []
    return normalize_slide_image_names(slides_images)


def build_slides_publish_md(target_path, title, image_files, attachments):
    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    lines = [
        title,
        "",
        f"创建时间：{generated_at}",
        f"幻灯片图片：{len(image_files)}",
        f"原始附件：{len(attachments)}",
        "",
        "^ 页面结构",
        "",
        "- 本页优先插入逐页幻灯片图片，便于直接在 Notion 中阅读。",
        "- 页面末尾保留 NotebookLM 导出的 PDF/PPTX 原始文件，便于下载。",
        "",
    ]
    if image_files:
        lines.extend([
            "^ 图片目录",
            "",
            *(f"- {path.name}" for path in image_files),
            "",
        ])
    if attachments:
        lines.extend([
            "^ 原始附件",
            "",
            *(f"- {path.name}" for path in attachments),
            "",
        ])
    target_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


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
    slides_images = exports / "slides_images"
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
    image_files = ensure_slides_images(slides_images, files)

    base = ["python3", str(notion_push)]

    report_cmd = base + [str(report)]
    if args.importance:
        report_cmd += ["--importance", args.importance]
    report_out = run_and_capture(report_cmd)
    report_url = extract_notion_url(report_out)

    slides_title = args.title or f"{args.task_key} {args.run_id} PPT图文归档"
    slides_publish_md = exports / "slides_publish.md"
    build_slides_publish_md(slides_publish_md, slides_title, image_files, files)

    slides_cmd = base + [str(slides_publish_md)]
    if image_files:
        slides_cmd += ["--attach-images-dir", str(slides_images)]
    for f in files:
        slides_cmd += ["--attach", str(f)]
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
    print(f"slide_image_count={len(image_files)}")
    print("files=" + ",".join(str(f) for f in files))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"PUBLISH_FAILED: {e}", file=sys.stderr)
        sys.exit(1)
