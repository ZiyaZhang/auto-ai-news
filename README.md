# Auto AI News

Auto AI News 是一个 **human-in-the-loop（人类监督）** 的 AI 情报生产流水线，用来把分散在 RSS、博客、论文、社区和站点地图里的更新，整理成适合阅读、归档和二次生产的周报材料。

它目前覆盖四个阶段：

1. **Collect**：从 RSS / HTML 列表页 / arXiv / sitemap / 手工 URL 采集候选内容。
2. **Curate**：对候选内容做日期校验、去重、过滤、打分和报告渲染。
3. **Generate**：将整理后的材料导入 NotebookLM，生成人工审阅后的中文报告和幻灯片。
4. **Publish**：把 NotebookLM 产出的报告、幻灯片图片和原始 PDF/PPTX 发布到 Notion。

> 这个项目不是“全自动新闻机器人”，而是一个 **“自动采集 + 半自动生成 + 自动归档”** 的情报工作流。

---

## Why this project exists

做 AI 周报最耗时间的部分，往往不是写，而是：

- 找源
- 去重
- 判断哪些值得保留
- 把内容整理成一个能继续喂给 NotebookLM / Notion 的结构化输入

Auto AI News 解决的是这部分问题：

- 用配置化 job 管理信息源
- 对新内容做可重复执行的处理
- 产出稳定的中间件格式（`items.json` / `report.md` / `upload_bundle/`）
- 把 NotebookLM 和 Notion 接到这条链路后面

---

## What’s in this repo

- `intel-hub/`：采集、过滤、排序、渲染、bundle 输出的核心引擎。
- `skills/intel-job-runner/`：用于运行采集流水线的 skill 定义。
- `skills/notebooklm-importer/`：负责 NotebookLM 产物整理、图片转换、Notion 发布编排。
- `skills/notion-writer/`：负责把 markdown、图片、PDF、PPTX 推送到 Notion。

---

## End-to-end flow

```text
intel-hub/jobs/<task>.yml
  -> fetchers (rss / html_list / arxiv / sitemap / manual_urls)
  -> date extraction + dedup + filtering + ranking
  -> report.md + items.json + upload_bundle/
  -> NotebookLM import (browser / human supervised)
  -> notebooklm_report.md + slides + exported pdf/pptx
  -> slides_images/ (preferred) or PDF -> images fallback
  -> Notion publish
```

---

## Runtime model

这个项目 **不是完全无人值守**。

### 可脚本化部分

- 信息源抓取
- 去重 / 过滤 / 排序
- 本地报告渲染
- NotebookLM 输入 bundle 生成
- Notion 页面和附件发布
- PDF 转图片回退流程

### 需要人工参与的部分

- Google 登录 / MFA / CAPTCHA
- NotebookLM UI 变化后的适配
- 对最终报告和 slides 做质量把关

这个项目适合作为：

- **研究 / 投资 / AI 行业扫描的内部工作流**
- **个人周报生产线**
- **情报收集与归档系统原型**

---

## Core capabilities

### 1) Config-driven collection

Job 配置写在 `intel-hub/jobs/*.yml` 中，定义：

- 时间窗口
- 去重 TTL
- 信息源列表
- 过滤规则
- 排序权重
- 输出格式
- 输出渠道

### 2) Multiple source types

当前支持：

- `rss`
- `html_list`
- `arxiv`
- `sitemap`
- `manual_urls`

### 3) Structured outputs

一次完整运行会产出：

- `items.json`：结构化条目列表
- `report.md`：本地渲染的报告
- `upload_bundle/`：可直接导入 NotebookLM 的素材包
- `manifest.json`：运行元信息与统计信息

### 4) Notion-ready publishing

可将以下内容发布到 Notion：

- 报告 markdown
- 幻灯片图片目录
- 原始 PDF / PPTX 附件

---

## Repository layout

```text
auto-ai-news/
├── .env.example
├── README.md
├── intel-hub/
│   ├── jobs/
│   │   └── weekly_ai_intel.yml
│   ├── requirements.txt
│   ├── src/
│   │   ├── extract/
│   │   ├── fetchers/
│   │   ├── io/
│   │   ├── pipeline/
│   │   ├── render/
│   │   ├── job_runner.py
│   │   └── models.py
│   └── templates/
└── skills/
    ├── intel-job-runner/
    ├── notebooklm-importer/
    └── notion-writer/
```

---

## Architecture notes

### `intel-hub/src/job_runner.py`

核心 orchestrator，串起完整流水线：

- 读取 job spec
- 抓取 source items
- 执行 dedup
- 执行 filter
- 执行 ranking
- 渲染 report
- 写入 bundle / items / manifest
- 更新 dedup state 和 source health

### `src/fetchers/*`

每种 source type 一个 fetcher，统一注册到 registry 中。

- `rss.py`
- `html_list.py`
- `arxiv.py`
- `sitemap.py`
- `manual.py`

### `src/pipeline/*`

负责核心处理逻辑：

- `dedup.py`
- `filter.py`
- `rank.py`

### `src/io/*`

负责运行产物与状态持久化：

- `bundle.py`
- `manifest.py`
- `state_store.py`

### `src/render/engine.py`

基于 Jinja2 模板渲染报告。

---

## Prerequisites

### Required

- Python 3.12+
- 一个可用的 Notion integration
- Notion database 写权限

### Required for full workflow

- OpenClaw（或你的 browser skill runtime）
- 可访问 NotebookLM 的浏览器环境

### Optional but recommended

- `pdftoppm`（优先）或 ImageMagick，用于 PDF -> 图片回退
- `.env` loader（如 `direnv` / `dotenv`）

---

## Setup

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r intel-hub/requirements.txt
```

### 2. Configure secrets

```bash
cp .env.example .env
```

至少需要：

- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`

在运行 Notion publisher 或 skill runtime 之前，把环境变量加载进 shell。

### 3. Register skills

把以下目录复制或软链接到你的 skill workspace：

- `skills/intel-job-runner`
- `skills/notebooklm-importer`
- `skills/notion-writer`

---

## Quickstart

### Option A: collection only

```bash
cd intel-hub
python3 -m src.job_runner weekly_ai_intel
```

输出目录示例：

```text
intel-hub/out/weekly_ai_intel/<run_id>/
```

### Option B: full workflow

```text
/skill notebooklm_importer run_all weekly_ai_intel --to-notion --importance 高
```

预期流程：

1. 运行 `intel-hub` 采集。
2. 将 bundle 导入 NotebookLM。
3. 在 NotebookLM 中生成中文报告与 slides。
4. 保存 `notebooklm_report.md`。
5. 生成 `slides_publish.md`。
6. 优先上传 `slides_images/` 中的逐页图片。
7. 若没有 slide images，则尝试用 PDF 自动转图片。
8. 将 markdown、图片、PDF、PPTX 发布到 Notion。

---

## Output contract

一次完整 run 建议至少包含：

```text
intel-hub/out/<task_key>/<run_id>/items.json
intel-hub/out/<task_key>/<run_id>/manifest.json
intel-hub/out/<task_key>/<run_id>/upload_bundle/
intel-hub/out/<task_key>/<run_id>/report.md
intel-hub/out/<task_key>/<run_id>/notebooklm_exports/notebooklm_report.md
intel-hub/out/<task_key>/<run_id>/notebooklm_exports/slides_publish.md
intel-hub/out/<task_key>/<run_id>/notebooklm_exports/slides_images/
intel-hub/out/<task_key>/<run_id>/notebooklm_exports/_downloads/*.pdf
intel-hub/out/<task_key>/<run_id>/notebooklm_exports/_downloads/*.pptx
```

其中：

- `report.md` 是本地采集报告。
- `notebooklm_report.md` 是 NotebookLM 产出的最终报告正文。
- `slides_publish.md` 是 Notion slides 页面介绍文本。
- `slides_images/` 是 Notion 内优先阅读的逐页图片。

---

## Example job spec

```yaml
task_key: weekly_ai_intel
time_window_days: 7
dedup_ttl_days: 45

sources:
  - type: rss
    url: "https://openai.com/blog/rss.xml"
    label: "OpenAI Blog"
    weight: 1.3

  - type: arxiv
    query: "cat:cs.AI OR cat:cs.CL"
    label: "arXiv AI/CL"
    weight: 1.0

filters:
  require_publish_date: true
  include_patterns: ["ai", "llm", "agent", "benchmark"]
  exclude_patterns: ["podcast", "webinar", "hiring"]
  min_detail_signals: 0

ranking:
  source_weight_map:
    "openai.com": 1.5
    "arxiv.org": 1.1
  multi_source_bonus: 0.3
  detail_signal_bonus: 0.1

report:
  kind: weekly_intel
  language: zh

bundle:
  include_sources_md: true
  one_md_per_item: true

output_channels:
  - type: local
  - type: notebooklm
```

---

## Troubleshooting

### 1. Source repeatedly returns zero items

检查：

- source 是否改版
- RSS 是否失效
- `html_list` 是否遇到 JS 渲染页面
- 是否被 source health 自动标记为 disabled

### 2. NotebookLM report text missing

发布脚本会优先查找：

- `notebooklm_exports/notebooklm_report.md`
- `notebooklm_exports/report.md`
- `notebooklm_exports/report.txt`

如果都不存在，需要手工保存 NotebookLM 正文。

### 3. No slide images generated

如果 `slides_images/` 缺失，脚本会尝试：

1. `pdftoppm`
2. `magick` / `convert`

如果都不可用，只会上传原始 PDF / PPTX。

### 4. Notion API errors

优先检查：

- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`
- 数据库字段名是否匹配
- integration 是否已被邀请进目标 database

---

## Limitations

- NotebookLM 自动化天然脆弱，容易受 UI 变化影响。
- `html_list` 和 `sitemap` 依赖启发式规则，不保证所有站点都稳定。
- 当前 ranking 仍然偏规则系统，不是学习型排序。
- 当前 dedup 基于 URL 归一化，不处理“同内容不同 URL”的语义去重。
- 当前 Notion markdown 转 block 能力比较基础，更偏向归档而不是高保真排版。

---

## License

MIT
