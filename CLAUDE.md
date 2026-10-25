# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

CrawlerHub is a local, single-user crawler workbench for video / text / image sources. A FastAPI
backend owns all crawling, scheduling, and file output; a Vue 3 SPA is the only UI. Data model:
data source → batch (source + strategy) → task (one item) → artifact (file/dir on disk).

- `docs/PRD.md` — requirements source of truth (Chinese).
- `docs/ARCHITECTURE.md` — implementation-level contract: API list, table fields, strategy
  boundaries, frontend design. §13–§15 record deliberate deviations and bug fixes; update them when
  behavior diverges from the original design.
- `docs/TEST-REPORT.md` — pytest suite scope, known environment limits, coverage notes.

Code comments, log messages, and user-facing strings are Chinese; keep that style.

## Commands

### Backend (Python 3.11+, tested on 3.13)

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

`python run.py` (from `backend/`) or `python -m backend.run` (from repo root) starts uvicorn on
`127.0.0.1:8000` with `reload=False` — restart manually after backend edits. API docs at `/docs`,
health at `/api/health`. Runtime paths are derived from the repo root (`backend/app/config.py`):
SQLite `data/crawlerhub.db`, output `data/output`, logs `logs/app.log`. Override with
`CRAWLERHUB_HOST`, `CRAWLERHUB_PORT`, `CRAWLERHUB_DB`, `CRAWLERHUB_OUTPUT`, `CRAWLERHUB_LOG_DIR`.

### Frontend

```bash
cd frontend
npm install
npm run dev      # http://127.0.0.1:5173, proxies /api and /static to :8000
npm run build    # vue-tsc --noEmit && vite build → dist/ (then served by backend on :8000)
npm run build:only
```

There is no backend linter/formatter configured. `npm run build` is the frontend type-check.

### Tests

The pytest suite is fully offline: `tests/conftest.py` creates a temporary DB/output/log dir and a
local mock HTTP site before importing `app`, so tests never touch `data/` or the network.

```bash
cd backend
pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest tests -q          # all (POSIX: .venv/bin/python)
.venv/Scripts/python.exe -m pytest tests/test_strategy.py -q
.venv/Scripts/python.exe -m pytest tests/test_strategy.py::TestStrategyCount::test_first_run_without_cursor_starts_from_first_item -q
.venv/Scripts/python.exe -m pytest tests -q --cov=app --cov-config=tests/coverage.rc --cov-report=term-missing
```

`backend/scripts/selftest_offline.py` is a standalone end-to-end smoke test (three content types +
m3u8 fallback + AES vector), run from `backend`:

```bash
.venv/Scripts/python.exe scripts/selftest_offline.py   # exit code 0 = pass
```

`scripts/verify_migrate.py` and `scripts/verify_singleflight.py` are one-off diagnostics, not part
of CI. ffmpeg is optional; if absent, video tasks degrade to `.ts` (see below). The app also probes
`tools/ffmpeg/{bin/,}` for a local binary (`tools/` is gitignored).

## Architecture

### Backend layering

`api/` (parse input + wrap responses only) → `schemas/` (Pydantic v2 DTOs) → `services/` (business
orchestration, transaction boundaries) → `engine/` (scheduling) → `parsers/` + `downloader/` (HTTP
and disk I/O) with `db/` underneath. Do not perform HTTP fetching or file I/O in the API layer.
`main.py` startup order matters: logging → dirs → `init_db()` (create tables + idempotent
migrations + seed) → `CrawlerEngine.start()` (orphan recovery, limiter sync, ffmpeg probe) → routes
→ optional static hosting of `frontend/dist`.

### Batch execution model (`engine/`)

- `CrawlerEngine` is a process-global singleton. Each batch runs one `BatchRunner` thread; phase two
  adds a per-batch `ThreadPoolExecutor`. Actual concurrency is bounded by a shared `GlobalLimiter`
  (count-based semaphore, adjustable at runtime) set from the `max_threads` setting; page-two
  workers must acquire a global token before claiming a task.
- Every batch has two phases (`parse` → `execute` → `done`). Phase one resolves the source list into
  `crawl_task` rows; a phase-one failure creates no tasks and does not advance cursors. An empty
  result is a `success` batch with zero tasks.
- Single-flight is enforced at the DB level: partial unique index `uq_batch_active` on
  `crawl_batch(data_source_id)` for busy statuses. `batch_service.create()` catches `IntegrityError`
  and returns `3001`; `retry_tasks` pre-checks for a conflicting active batch before reviving one.
- Tasks are claimed with a conditional `UPDATE ... WHERE status='pending'`, ordered by `seq_no`.
- Pause does not kill threads. `PauseController` is an `Event`; downloaders call `checkpoint()` at
  atomic-step boundaries (per m3u8 segment / image; text tasks have no checkpoint) and raise
  `PauseRequested`, which reverts the task to `pending` while keeping `step_done`. The runner waits
  up to 30 s for active tasks to drain: `paused`, otherwise `paused_with_warning` plus a WARN log.
  Resume waits for the old runner to exit before submitting a new one.
- Retry only for `failed` tasks; backoff `1s × 2^(attempt-1)` capped at 30 s. Only `4005 HTTP_ERROR`
  and `4006 M3U8_PARSE` are retryable (404/403/script errors are not); transport-layer HTTP retries
  are disabled so `attempt_count` reflects real attempts.
- On startup, orphan `running` tasks go back to `pending`, `running` batches become
  `paused_with_warning` (with a WARN log), and stale `processing` artifacts are closed as
  `success`/`failed` depending on whether the file exists.

### Cursors and strategies

Three strategies live in `engine/strategy.py` (pure calculation, no DB): `count` (n items after
`cursor_last_item_no`, auto-paginating), `page` (`start` + `pages`, truncation at the last page,
page failures become `skipped`), `date` (inclusive range, dedup by historical success fingerprints,
missing dates kept with a WARN). Cursor columns live on `data_source`. Only the batch finalizer
advances them, and only for successful work: `count` advances to the max successful `seq_no`;
`page`/`date` use the phase-one planned cursor; a failed batch keeps `cursor_before`.

### Parsing, downloading, artifacts

- `parsers/registry.build_parser()` prefers a custom Python script (executed by
  `engine/script_sandbox.py` with a restricted builtin set, 60 s timeout, allowed module whitelist,
  helpers `http_get` / `http_get_json` / `parse_html`); otherwise it selects a built-in parser by
  type (`HtmlListParser` for video/text, `ImageSetParser` for image), driven by CSS selectors in
  `data_source.config_json`. The script contract is documented at the top of `registry.py`.
- Video: m3u8 only; AES-128 with explicit or default IV; SAMPLE-AES/DRM raises `4007`. Segments are
  downloaded concurrently, concatenated, then remuxed with `ffmpeg -c copy`, falling back to
  `libx264 + aac`. Missing ffmpeg is rejected at batch creation (`3003`), and if it disappears
  mid-run the `.ts` is kept while the task is failed (`3003`) so a retry can reuse segments.
- Text always writes UTF-8 TXT first; PDF is additionally written when `export_format=pdf` and a
  PDF failure only downgrades the artifact type to `text` (task stays successful).
- Artifacts are registered as `processing` before work starts and updated via an idempotent upsert
  keyed by `(task_id, name)` (unique index `uq_artifact_task_name`), so pause/retry/redownload never
  duplicate rows.
- Output templates are defined only in `common/path_builder.py`: video
  `root/source/category/name.mp4`; novel `root/source/category/book/chapter.txt`; article
  `root/source/category/date/title.txt`; image `root/source/category/date/gallery/001.jpg`.
  Empty category → `未分类`; temp work lives under `root/.tmp/{task_id}`; writes go through
  `.part` + `os.replace`.

### Database and migrations

Seven tables (`data_source`, `crawl_batch`, `crawl_task`, `task_result`, `task_log`, `artifact`,
`app_setting`). SQLite with `WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, `foreign_keys=ON`.
Use `session_scope()` short transactions; never share a Session across threads, and do not hold a
Session open across network I/O (load a snapshot, `expunge`, then write back). There is no Alembic:
`db/migrate.py` is the idempotent upgrade path (add columns/indexes, dedupe before unique indexes),
with the version stored in `app_setting._schema_version`. Add schema changes to both `models.py` and
`migrate.py` so existing databases upgrade without data loss.

### API conventions

All endpoints are under `/api`. Success and failure both use the envelope
`{"code", "data", "message"}` (`code=0` = success; non-zero `message` is user-facing Chinese);
pagination is `{"items","total","page","pageSize"}`. JSON fields are snake_case end to end. Raise
`BizError(code, message, retryable=..., detail=...)`; business codes map to HTTP statuses via
`common/errors.py` (1xxx input, 2xxx data source, 3xxx scheduling, 4xxx parse/download, 5xxx
system). `PauseRequested` is control flow, not an error.

### Frontend

Vue 3 + Vite + TypeScript + Element Plus + Pinia + ECharts, `@` aliased to `src`. The router uses
**hash history** (`/#/artifacts`) because the backend serves `dist` with `StaticFiles(html=True)`
and has no SPA fallback. Eight routes reuse `ContentListView` and `WorkbenchView` for all three
content types via the `:type` param.

- `src/api/request.ts` unwraps the envelope (returns `data` on `code=0`, otherwise toasts and
  rejects `BizError`), tracks `backendOnline`, and probes `/api/health` every 5 s while offline.
  Request timeout is 15 s (uploads/downloads 60 s).
- Pinia owns polling: `stores/batch.ts` polls batch progress every 2 s and stops on terminal or
  paused states; `stores/app.ts` polls system metrics every 3 s. Logs use incremental `after_log_id`.
- Status labels/colors exist only in `src/utils/constants.ts`, which mirrors `class E` in
  `backend/app/config.py` and `ErrCode` in `backend/app/common/errors.py` — update both sides when
  adding enums.

## Key enums and defaults

Enum literals live in `backend/app/config.py::E` (shared with DB CHECK constraints and mirrored by
the frontend constants). Tunable defaults live in `DEFAULTS` (max threads 4, hard limit 32, retry
attempts 3, pause timeout 30 s, script timeout 60 s, queue cap 5000, segment concurrency 4, etc.) and
can be overridden by the `app_setting` table. Timestamps are ISO 8601 local time with milliseconds
and offset, generated by `common/timeutil.now_iso()`; date-only fields use `yyyy-MM-dd`.

## Known constraints

- No login/captcha/browser automation; custom parsing scripts are trusted-local-user code with a
  timeout and restricted builtins, not process isolation.
- m3u8 supports AES-128 only; SAMPLE-AES and DRM are explicitly rejected.
- `data/`, `logs/`, `tools/`, `.claude/`, `.agents/`, `node_modules/`, `frontend/dist/` and `.venv/`
  are gitignored.