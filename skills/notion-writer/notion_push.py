#!/usr/bin/env python3
"""
notion_push.py — Push content and local files to a Notion database.

Usage:
    python3 notion_push.py <file.md>
    python3 notion_push.py <file.md> --importance 高
    python3 notion_push.py <file.md> --attach ./slides.pdf --attach ./cover.png
    python3 notion_push.py --attach ./slides.pdf --title "PPT 归档"
    python3 notion_push.py --test

Env vars (required):
    NOTION_TOKEN        — Notion integration token
    NOTION_DATABASE_ID  — Target database UUID
"""

import argparse
import json
import mimetypes
import os
import re
import sys
import uuid
import urllib.request
from datetime import datetime, timezone

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
NOTION_VERSION = os.environ.get("NOTION_VERSION", "2022-06-28")
NOTION_UPLOAD_VERSION = os.environ.get("NOTION_UPLOAD_VERSION", "2025-09-03")
API_BASE = "https://api.notion.com/v1"

if not NOTION_TOKEN:
    print("ERROR: NOTION_TOKEN env var not set", file=sys.stderr)
    sys.exit(1)
if not NOTION_DATABASE_ID:
    print("ERROR: NOTION_DATABASE_ID env var not set", file=sys.stderr)
    sys.exit(1)


def notion_request(method, endpoint, body=None, notion_version=None, headers=None):
    url = f"{API_BASE}{endpoint}"
    data = json.dumps(body).encode() if body else None
    req_headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": notion_version or NOTION_VERSION,
        "Content-Type": "application/json",
    }
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"Notion API error {e.code}: {body_text}", file=sys.stderr)
        raise


def text_to_blocks(text, max_len=2000):
    """Convert text into Notion block children."""
    blocks = []
    for para in re.split(r"\n{2,}", text.strip()):
        para = para.strip()
        if not para:
            continue
        if para.startswith("^"):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": para.lstrip("^ ")}}]
                }
            })
        else:
            for i in range(0, len(para), max_len):
                chunk = para[i:i + max_len]
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": chunk}}]
                    }
                })
    return blocks


def parse_title(text):
    """Extract the first line as the page title."""
    first_line = text.strip().split("\n")[0].strip()
    return first_line or f"Untitled {datetime.now().strftime('%Y-%m-%d %H:%M')}"


def _make_rich_text(content):
    return [{"type": "text", "text": {"content": content}}]


def create_page(title, importance=None, blocks=None):
    """Create a Notion page in the target database."""
    properties = {
        "Name": {
            "title": [{"text": {"content": title}}]
        },
        "Status": {
            "status": {"name": "Not started"}
        },
    }
    if importance:
        properties["重要性"] = {"select": {"name": importance}}

    body = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
        "children": (blocks or [])[:100],
    }

    return notion_request("POST", "/pages", body)


def push_text(text, importance=None):
    """Create a Notion page in the target database."""
    title = parse_title(text)
    blocks = text_to_blocks(text)
    return create_page(title=title, importance=importance, blocks=blocks)


def push_file(filepath, importance=None):
    """Read a file and push it to Notion."""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        print(f"SKIP: {filepath} is empty", file=sys.stderr)
        return None
    result = push_text(text, importance=importance)
    page_url = result.get("url", "")
    page_id = result.get("id", "")
    print(f"OK: {filepath} -> {page_url} (id={page_id})")
    return result


def _multipart_body(fields, files):
    """Build a multipart/form-data payload."""
    boundary = f"----notion-upload-{uuid.uuid4().hex}"
    lines = []
    for key, value in fields.items():
        lines.extend([
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{key}"'.encode(),
            b"",
            str(value).encode(),
        ])

    for field_name, filename, content_type, data in files:
        lines.extend([
            f"--{boundary}".encode(),
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{filename}"'
            ).encode(),
            f"Content-Type: {content_type}".encode(),
            b"",
            data,
        ])

    lines.append(f"--{boundary}--".encode())
    body = b"\r\n".join(lines) + b"\r\n"
    return boundary, body


def upload_local_file(file_path):
    """Upload a local file using Notion's File Upload API and return file_upload_id."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    filename = os.path.basename(file_path)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    create_resp = notion_request(
        "POST",
        "/file_uploads",
        body={"mode": "single_part", "filename": filename, "content_type": content_type},
        notion_version=NOTION_UPLOAD_VERSION,
    )
    file_upload_id = create_resp.get("id")
    if not file_upload_id:
        raise RuntimeError(f"Create upload failed: {create_resp}")

    send_endpoint = f"/file_uploads/{file_upload_id}/send"
    with open(file_path, "rb") as f:
        data = f.read()
    boundary, body = _multipart_body({}, [("file", filename, content_type, data)])
    # notion_request sends JSON body by default. For multipart, send a raw request.
    url = f"{API_BASE}{send_endpoint}"
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_UPLOAD_VERSION,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            send_resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"Notion upload error {e.code}: {body_text}", file=sys.stderr)
        raise

    status = send_resp.get("status")
    if status != "uploaded":
        raise RuntimeError(f"Upload not completed for {file_path}: status={status}")
    return file_upload_id


def _detect_block_type(file_path, content_type):
    if content_type.startswith("image/"):
        return "image"
    if content_type == "application/pdf" or file_path.lower().endswith(".pdf"):
        return "pdf"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type.startswith("video/"):
        return "video"
    return "file"


def append_uploaded_file_block(page_id, file_upload_id, file_path, caption=None):
    """Attach an uploaded file to a page as a media/file block."""
    filename = os.path.basename(file_path)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    block_type = _detect_block_type(file_path, content_type)
    caption_text = caption or filename
    block_payload = {
        "object": "block",
        "type": block_type,
        block_type: {
            "caption": _make_rich_text(caption_text),
            "type": "file_upload",
            "file_upload": {"id": file_upload_id},
        },
    }
    notion_request(
        "PATCH",
        f"/blocks/{page_id}/children",
        body={"children": [block_payload]},
        notion_version=NOTION_UPLOAD_VERSION,
    )


def attach_files_to_page(page_id, file_paths, caption=None):
    for file_path in file_paths:
        file_upload_id = upload_local_file(file_path)
        append_uploaded_file_block(page_id, file_upload_id, file_path, caption=caption)
        print(f"OK: attached {file_path} to page {page_id} via file_upload {file_upload_id}")


def push_attachment_page(file_paths, importance=None, title=None, caption=None):
    created_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    page_title = title or f"附件归档 {created_at}"
    intro = (
        f"{page_title}\n\n"
        f"创建时间：{created_at}\n"
        f"附件数量：{len(file_paths)}\n"
        f"说明：以下文件通过 Notion File Upload API 上传并附加。"
    )
    page = push_text(intro, importance=importance)
    page_id = page.get("id")
    if not page_id:
        raise RuntimeError("Failed to create attachment page")
    attach_files_to_page(page_id, file_paths, caption=caption)
    return page


def test_connection():
    """Verify Notion token + database access."""
    try:
        db = notion_request("GET", f"/databases/{NOTION_DATABASE_ID}")
        title = " ".join(t.get("plain_text", "") for t in db.get("title", []))
        props = {k: v["type"] for k, v in db.get("properties", {}).items()}
        print(f"DB Title: {title or '(untitled)'}")
        print(f"Properties: {json.dumps(props, ensure_ascii=False)}")

        test_result = push_text(
            f"连通测试 — {datetime.now(timezone.utc).isoformat()}\n\n"
            "这是 notion_push.py 的自动连通测试，可以安全删除。",
        )
        print(f"Test page: {test_result.get('url', '')}")
        print("\nSUCCESS: Notion connection verified.")
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Push markdown and local files to Notion.")
    parser.add_argument("paths", nargs="*", help="Markdown/text files to push as pages.")
    parser.add_argument("--importance", choices=["高", "中", "低"], help="Set 重要性.")
    parser.add_argument("--attach", action="append", default=[], help="Attach local file to the created page. Repeatable.")
    parser.add_argument("--title", help="Page title for --attach only mode.")
    parser.add_argument("--caption", help="Attachment caption text (optional).")
    parser.add_argument("--test", action="store_true", help="Verify Notion connectivity.")
    cli = parser.parse_args()

    if cli.test:
        test_connection()
        sys.exit(0)

    if not cli.paths and not cli.attach:
        print(__doc__.strip())
        sys.exit(0)

    for file_path in cli.attach:
        if not os.path.isfile(file_path):
            print(f"ERROR: attachment not found: {file_path}", file=sys.stderr)
            sys.exit(1)

    if cli.attach:
        if len(cli.paths) > 1:
            print("ERROR: with --attach, provide at most one content file.", file=sys.stderr)
            sys.exit(1)
        if len(cli.paths) == 1:
            content_path = cli.paths[0]
            if not os.path.isfile(content_path):
                print(f"ERROR: content file not found: {content_path}", file=sys.stderr)
                sys.exit(1)
            page = push_file(content_path, importance=cli.importance)
            page_id = page.get("id", "")
            if not page_id:
                print("ERROR: failed to get page id after content push", file=sys.stderr)
                sys.exit(1)
            attach_files_to_page(page_id, cli.attach, caption=cli.caption)
        else:
            page = push_attachment_page(
                file_paths=cli.attach,
                importance=cli.importance,
                title=cli.title,
                caption=cli.caption,
            )
            page_url = (page or {}).get("url", "")
            page_id = (page or {}).get("id", "")
            if page_url:
                print(f"OK: attachment page -> {page_url} (id={page_id})")
        sys.exit(0)

    for filepath in cli.paths:
        if not os.path.isfile(filepath):
            print(f"SKIP: {filepath} not found", file=sys.stderr)
            continue
        push_file(filepath, importance=cli.importance)
