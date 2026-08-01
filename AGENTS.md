# Repository Guidelines

This file is the primary guidance document for AI coding agents (Claude Code, Codex, Cursor, …) and human contributors working in this repository. `CLAUDE.md` simply points here.

## Project Overview

SupoClip is an open-source alternative to OpusClip — an AI-powered video clipping tool that transforms long-form content into viral short clips. AGPL-3.0 licensed.

## Project Structure & Module Organization

This repository is a monorepo with three apps:

- `backend/`: FastAPI + async worker code (`src/api`, `src/services`, `src/repositories`, `src/workers`).
- `frontend/`: main Next.js app (`src/app`, `src/components`, `src/lib`, `prisma/`).
- `mcp/`: standalone `supoclip-mcp` server, a thin client over the REST API.

- `docker/`: `*.Dockerfile` for each app, plus `options/` — optional compose overlays enabled by uncommenting an `include:` line.

Infra and bootstrap files live at the root: `docker-compose.yml.example`, `init.sql`, `.env.example`, `Makefile`, and `start.sh`. Note that `docker-compose.yml` itself is not tracked; copy it from the example (`./start.sh` does this) before running any compose command.

## Build, Test, and Development Commands

### Docker (recommended)

The repo ships `docker-compose.yml.example`, not a live compose file. The
first step of any Docker work is `cp docker-compose.yml.example
docker-compose.yml` (`./start.sh` does it automatically); the copy is
git-ignored so local edits never collide with a pull.

```bash
docker-compose up -d              # Start all 6 services
docker-compose up -d --build      # Rebuild after changes
docker-compose logs -f            # Stream all service logs
docker-compose logs -f backend    # Debug backend
docker-compose logs -f worker     # Debug video processing
docker-compose down               # Stop all services
```

Services and their published host ports (all bound to `127.0.0.1`):

| Service | Host port | Notes |
|---------|-----------|-------|
| `frontend` | 3001 | Next.js listens on 3107 inside the container |
| `backend` | 8000 | OpenAPI docs at `/docs` |
| `mcp` | `${SUPOCLIP_MCP_PORT:-9100}` | MCP server (`mcp/`) |
| `worker` | — | ARQ worker, no published port |
| `redis` | 6379 | |
| `postgres` | — | Not published; reachable only on the compose network |

### Optional add-ons (`docker/options/`)

Everything optional is a separate compose file pulled in through the top-level
`include:` block in `docker-compose.yml`, which ships fully commented out, plus
a matching `.env.<option>` copied from its `.example`. Uncomment + copy is the
whole toggle — there are no profiles and no `COMPOSE_PROFILES`.

| File | Adds | Settings file |
|------|------|---------------|
| `vaapi.yml` | `devices: /dev/dri` on `backend` + `worker` | `.env.vaapi` (`VIDEO_ENCODER`, `VAAPI_DEVICE`) |
| `whisperx.yml` | `whisperx` service (whisper-asr-webservice, port 9000) | `.env.whisperx` (`TRANSCRIPTION_PROVIDER`, `WHISPERX_*`, `ASR_MODEL`, `HF_TOKEN`) |
| `tunnel.yml` | `cloudflared` service | `.env.tunnel` (`TUNNEL_TOKEN`) |
| `llama-{cpu,cuda,rocm,sycl,vulkan}.yml` | `llama` service (llama.cpp server, port 8080); enable exactly ONE | `.env.llama` (`LLAMA_ARG_*`), plus `LLM`/`OPENAI_BASE_URL` in `.env` |

Mechanics worth knowing when editing these — all verified on Compose v5.2.0:

- An included file's service **merges** with the root definition, and the root
  file **wins** on conflicting scalars. Overlays can therefore only *add* keys
  (`vaapi.yml` adds `devices:`).
- There is **no optional include**. A missing `path` is a hard parse error and
  `required: false` is silently ignored — hence comment-driven toggling. Include
  long syntax accepts only `path`, `project_directory`, `env_file`.
- Service-level `env_file` **does** honour `required: false`: a missing file is
  skipped silently, so an add-on whose settings file was never copied still
  parses.
- Each overlay attaches its own `.env.<option>` to whichever services read it —
  `vaapi.yml` and `whisperx.yml` add one to `backend` and `worker`, not the root
  template. That is what makes the include the real toggle: attached in
  `docker-compose.yml` instead, the file would be read whether or not the
  include was active, so disabling the add-on would leave the containers
  configured for a service that is no longer in the stack. Two overlays
  attaching to the same service merge rather than clobber (verified with
  `vaapi` + `whisperx` both on).
- `environment:` **always** outranks `env_file` — including `VAR=${VAR:-}`
  rendering `VAR: ""` and a bare `VAR` rendering `VAR: null`, both of which
  shadow the file. So a variable owned by a scoped file must be **absent** from
  `environment:`, and `config.py`'s defaults cover the no-file case.
- Compose interpolates `${...}` only from the root `.env`, never from a scoped
  file. A scoped file can therefore only reach a service through variable names
  that service already understands, which is why they use image-native names
  (`ASR_MODEL`, `TUNNEL_TOKEN`, `LLAMA_ARG_*`). The llama services pass no
  `command:` at all, since a CLI flag would override `LLAMA_ARG_*`.
- `env_file` paths inside an **included** file resolve relative to that file's
  own directory, not the project root — hence `../../.env.whisperx` from
  `docker/options/`. In the root compose file they are project-relative.
- Requires Compose **v5.0.0+**; `start.sh` enforces it. `include:` itself landed
  in v2.24, but every overlay here merges into a service the root file also
  defines, and partial-service includes only work from v5.0.0. Every v2.x
  release — through the final v2.40.3 — rejects them with
  `services.backend conflicts with imported resource` instead of merging, so
  the add-ons cannot work there at all.

Dockerfiles live in `docker/` (`backend.Dockerfile`, `frontend.Dockerfile`,
`mcp.Dockerfile`). Each build context is still the app directory, so the
compose `dockerfile:` values are context-relative (`../docker/backend.Dockerfile`).

### Backend (local)

Uses `uv` (not pip/poetry). Requires Python 3.11+, ffmpeg, running PostgreSQL and Redis.

```bash
cd backend
uv venv .venv && source .venv/bin/activate
uv sync

# API server (uses refactored entry point)
uvicorn src.main_refactored:app --reload --host 0.0.0.0 --port 8000

# Worker process (required for video processing)
arq src.workers.tasks.WorkerSettings
```

`src/main.py` is the legacy monolithic entry point; Compose and local dev both
run `src.main_refactored:app`. Without activating the venv, prefix commands with
`.venv/bin/` (e.g. `.venv/bin/arq src.workers.tasks.WorkerSettings`).

### Frontend (local)

```bash
cd frontend
pnpm install
pnpm run dev          # Dev server with Turbopack, port 3107
pnpm run build        # Prisma generate + Next.js build
pnpm run start        # Serve the production build, port 3107
pnpm run lint         # ESLint
```

## Architecture

### System Overview

```
User → Frontend (Next.js 15) → Backend API (FastAPI) → Redis Queue → ARQ Worker
                                      ↓                                  ↓
                               PostgreSQL ←───────────────────────────────┘
```

Task creation returns immediately (<100ms). Video processing happens asynchronously in the worker. Frontend connects via SSE for real-time progress updates.

### Backend: Layered Architecture

The backend was refactored from monolithic (`main.py`, legacy) to layered (`main_refactored.py`, active):

```
api/routes/          → HTTP handlers (tasks.py, media.py, admin.py, api_keys.py, billing.py, feedback.py)
services/            → Business logic (task_service.py, video_service.py, api_key_service.py,
                       billing_service.py, email_service.py + task/subscription/api-key email services)
repositories/        → Raw SQL via asyncpg (task_repository.py, clip_repository.py,
                       source_repository.py, api_key_repository.py, cache_repository.py)
workers/             → ARQ job queue (tasks.py, job_queue.py, progress.py)
utils/               → Thread pool helpers for blocking operations (async_helpers.py)
```

**Key patterns:**
- All DB access goes through repository classes using raw SQL (`text()` queries), not SQLAlchemy ORM
- Blocking operations (video processing, downloads, transcription) wrapped in `run_in_thread()` to avoid blocking the async event loop
- Progress tracking uses Redis pub/sub → SSE to frontend
- Task status flow: `queued → processing → completed/error/cancelled`

### Video Processing Pipeline

1. **Input** → YouTube URL (yt-dlp) or uploaded file
2. **Transcription** → AssemblyAI word-level timestamps (cached as `.transcript_cache.json`); or local WhisperX via `TRANSCRIPTION_PROVIDER=whisperx` (`src/transcription_whisperx.py`), which has two implementations picked by `WHISPERX_API_URL`: HTTP against the `whisperx` add-on container (how Docker runs it) when set, or in-process from the optional `whisperx` uv extra when unset. Both emit the identical transcript structure
3. **AI Analysis** → Pydantic AI selects 2-5 viral segments (15-60s each, ideally 25-50s) with virality scoring
4. **Clip Generation** → direct `ffmpeg` subprocess calls (`run_ffmpeg_command()` in `video_utils.py`) build the clips. There is no MoviePy dependency — every render is a hand-built ffmpeg argv using `-vf`/`-filter_complex`. Clips get:
   - Face-centered cropping: MediaPipe → OpenCV DNN → Haar cascade (fallback chain)
   - Word-synced subtitles from AssemblyAI
   - Custom fonts (TTF files in `backend/fonts/`)
   - Optional transition effects (`backend/transitions/`)
   - Optional B-roll overlays (Pexels API)
   - Caption templates with animation styles
5. **Storage** → Clips to `{TEMP_DIR}/clips/`, metadata to PostgreSQL

### Frontend Architecture

- **Next.js 15** with App Router, React 19, TailwindCSS v4
- **ShadCN UI** (New York style, stone base color, Radix primitives)
- **Better Auth** with Prisma adapter for email/password auth
- **No global state library** — React hooks only (`useState`, `useEffect`, `useSession`)
- All pages use `"use client"` — SSR is minimal
- Prisma client generated to `frontend/src/generated/prisma/` (custom output path)
- Build: `prisma generate && next build` (Prisma generate runs on both build and postinstall)

**Auth flow:** Frontend calls Better Auth → session cookie → passes `user_id` header to backend API

### Database

PostgreSQL 15. Schema in `init.sql`. Mixed naming conventions:
- `tasks`, `sources`, `generated_clips` → snake_case
- `session`, `account`, `verification`, `users` → camelCase (Better Auth)
- UUIDs stored as VARCHAR(36)
- Auto-update triggers on `updated_at`/`updatedAt` columns

## Key Backend Files

| File | Purpose |
|------|---------|
| `src/main_refactored.py` | Active FastAPI entry point (~230 lines) |
| `src/main.py` | Legacy monolithic entry point (do not use for new work) |
| `src/api/routes/tasks.py` | Task CRUD, SSE progress, clip editing endpoints (~1090 lines) |
| `src/api/routes/media.py` | Fonts, transitions, uploads, templates |
| `src/api/routes/admin.py` | Admin runtime-settings API (see `runtime_settings.py`) |
| `src/services/task_service.py` | Task orchestration, clip editing logic (~980 lines) |
| `src/services/video_service.py` | Video download, transcription, AI analysis, clip generation |
| `src/workers/tasks.py` | ARQ worker task definitions (`max_jobs = config.worker_max_jobs`, i.e. `WORKER_MAX_JOBS`, default 4 concurrent tasks) |
| `src/workers/job_queue.py` | Job queue management |
| `src/workers/progress.py` | Real-time progress via Redis |
| `src/ai.py` | Pydantic AI agents, system prompt, segment validation |
| `src/video_utils.py` | ffmpeg command builders, cropping, subtitles (~3740 lines) |
| `src/clip_editor.py` | Clip trim, split, merge, export presets |
| `src/broll.py` | Pexels API B-roll integration |
| `src/caption_templates.py` | Caption template system |
| `src/config.py` | Environment variable configuration |
| `src/runtime_settings.py` | Encrypted admin-editable settings loaded over the env vars |

## API Endpoints (routes in `api/routes/`)

**Task lifecycle:**
- `POST /start-with-progress` — Create task, enqueue to worker (returns task_id)
- `GET /tasks/` — List user tasks
- `GET /tasks/{id}` — Get task with clips
- `GET /tasks/{id}/progress` — SSE real-time progress stream
- `POST /tasks/{id}/cancel` — Cancel processing
- `POST /tasks/{id}/resume` — Resume cancelled/errored task
- `DELETE /tasks/{id}` — Delete task

**Clip editing:**
- `PATCH /tasks/{id}/clips/{clip_id}` — Trim clip
- `POST /tasks/{id}/clips/{clip_id}/split` — Split at timestamp
- `POST /tasks/{id}/clips/merge` — Merge selected clips
- `PATCH /tasks/{id}/clips/{clip_id}/captions` — Update captions
- `GET /tasks/{id}/clips/{clip_id}/export?preset=tiktok` — Export with platform preset

**Media:**
- `GET /fonts`, `GET /transitions`, `GET /caption-templates`, `GET /broll/status`
- `POST /upload` — Upload video file
- `GET /clips/{filename}` — Serve generated clips

**API keys (programmatic access):**
- `GET /api-keys/` — List the user's API keys (metadata only)
- `POST /api-keys/` — Create a key (plaintext `sk_...` returned exactly once)
- `DELETE /api-keys/{key_id}` — Revoke a key

API keys authenticate `/tasks/*`, `/fonts` and `/upload` directly via
`Authorization: Bearer sk_...` or `x-api-key`. Resolution lives in
`auth_headers.resolve_authenticated_user_id` (API key → DB lookup, else falls
back to the frontend's HMAC-signed session headers). Only the SHA-256 hash is
stored (`api_keys` table). The frontend manages keys at `/settings/api-keys`.

## Environment Variables

Required in `.env` (root) or `backend/.env`:

Note the split: `.env` holds core and stack-level settings, while each optional
add-on's settings live in its own `.env.<option>` (see the add-ons table above).
`TRANSCRIPTION_PROVIDER`, `WHISPERX_*`, `HF_TOKEN`, `VIDEO_ENCODER`,
`VAAPI_DEVICE` and `TUNNEL_TOKEN` are **not** read from `.env` under Docker —
the compose file no longer passes them through. `config.py` still reads them as
plain environment variables, so a bare-metal run can keep them in `.env`.

```bash
ASSEMBLY_AI_API_KEY=...              # Required unless transcribing with whisperx
LLM=google-gla:gemini-3-flash-preview # Format: provider:model-name
GOOGLE_API_KEY=...                   # Or OPENAI_API_KEY / ANTHROPIC_API_KEY
OPENAI_BASE_URL=https://api.openai.com/v1  # The endpoint openai:* talks to. Change it
                                     # for any OpenAI-compatible server (llama.cpp,
                                     # vLLM, Ollama /v1, OpenRouter, ...). Never blank:
                                     # an empty value is an empty endpoint, not a default
OPENAI_SERVICE_TIER=                 # Optional; auto|default|flex|scale|priority
OLLAMA_BASE_URL=http://localhost:11434/v1  # Deprecated; ollama:* only, ignores OPENAI_BASE_URL
OLLAMA_API_KEY=...                   # Deprecated; ollama:* only, ignores OPENAI_API_KEY

# Optional
PEXELS_API_KEY=...                   # B-roll stock footage
REDIS_HOST=localhost                 # Default: localhost
REDIS_PORT=6379                      # Default: 6379
QUEUED_TASK_TIMEOUT_SECONDS=180      # Fail-safe for stuck tasks
WORKER_MAX_JOBS=4                    # ARQ worker concurrency (default 4)
TEMP_DIR=/tmp                        # Temp file storage
DATABASE_URL=postgresql+asyncpg://...
BETTER_AUTH_SECRET=...               # Frontend auth secret
```

Stack-level switches Compose interpolates from `.env` (`SUPOCLIP_MCP_PORT`,
`FRONTEND_BUILD_TARGET`, `LLAMA_MODELS_DIR`, `LLAMA_PORT`, `WHISPERX_PORT`) are
documented in `.env.example`. Everything an optional add-on needs at runtime
lives in its `.env.<option>` instead — see
[Optional add-ons](#optional-add-ons-dockeroptions).

## Common Workflows

### Adding fonts/transitions

Drop `.ttf` files into `backend/fonts/` or `.mp4` files into `backend/transitions/`. They auto-appear via their respective `GET` endpoints.

### Modifying AI clip selection

Edit `backend/src/ai.py`: `simplified_system_prompt` controls selection criteria, `TranscriptSegment` defines the output model, `get_most_relevant_parts_by_transcript()` runs analysis with validation.

Authoritative selection bounds (the one-line summary in the pipeline section
above is a rough sketch; these constants are what the code enforces):

- **Segment count** — both prompts ask for **2-5** segments, quality over quota. `FAST_MODE_MAX_CLIPS` (default 4) and `MAX_CLIPS` (default 10) cap it further downstream.
- **Duration** — `MIN_ACCEPTED_CLIP_SECONDS = 15` / `MAX_ACCEPTED_CLIP_SECONDS = 60` are enforced; `IDEAL_CLIP_MIN_SECONDS = 25` / `IDEAL_CLIP_MAX_SECONDS = 50` are what the prompt asks for.
- **Hook titles** — `sanitize_hook_title()` truncates to `HOOK_TITLE_MAX_WORDS = 10` words and `HOOK_TITLE_MAX_CHARS = 64` characters, even though the prompt asks for 3-9 words.
- **Virality** — the model returns `total_score`; it is validated to equal the sum of the four sub-scores and persisted as `generated_clips.virality_score`.

### Video processing constraints

- Output formats (`VALID_OUTPUT_FORMATS`): `vertical`, `vertical_pan`, `vertical_split` all render 1080x1920 9:16 H.264; `original` keeps the source aspect ratio. Dimensions are forced even (`round_to_even()`)
- Subtitle vertical placement comes from each caption template's `position_y` in `caption_templates.py` (0.70-0.82 of frame height; the default template uses 0.80)
- Virality scoring: `hook_score`, `engagement_score`, `value_score`, `shareability_score` (0-25 each, summed to `virality_score` 0-100)
- Each segment gets an AI-written `hook_title` (3-9 words) burned into the top safe area for the first ~4s (`build_hook_title_ass` in `video_utils.py`), persisted on `generated_clips.hook_title`
- Static talking-head crops get a slow ~5% Ken Burns punch-in (`kenburns_zoom_fragment`); tracked pans and split screens keep their own motion

## MCP Server

`mcp/` is a standalone [MCP](https://modelcontextprotocol.io) server
(`supoclip-mcp`, Python/FastMCP, stdio) that exposes SupoClip to MCP clients
(Claude Desktop/Code, Cursor, …). It is a thin client over the REST API.

- **Default target:** the hosted API `https://api.supoclip.com`. Override with
  `SUPOCLIP_API_URL` for self-hosting (e.g. `http://localhost:8000`).
- **Auth:** a per-user API key in `SUPOCLIP_API_KEY` (see API keys above).
  Self-hosters may instead use `SUPOCLIP_USER_ID` (+ `SUPOCLIP_AUTH_SECRET` when
  signing is enforced).
- **Tools:** create/list/get/wait/cancel/resume/delete tasks, list/download/
  export clips, and public discovery (templates, transitions, fonts, B-roll).
- Run with `cd mcp && uv run supoclip-mcp`. Details in `mcp/README.md`.

## Coding Style & Naming Conventions

- Python: 4-space indentation, type hints where practical, `snake_case` for functions/modules.
- TypeScript/React: 2-space indentation, `PascalCase` for component names, `camelCase` for variables/functions, route files in Next.js App Router conventions (`app/.../page.tsx`, `route.ts`).
- Linting: Next.js ESLint config in `frontend/eslint.config.mjs`.
- Imports: use the `@/*` alias in Next.js apps when possible.

## Testing Guidelines

The backend and frontend both have test suites, and CI runs them
(`.github/workflows/tests.yml`). The `Makefile` at the repo root is the easiest
entry point because it supplies the DB/Redis/auth env vars the suites expect:

```bash
make test           # backend pytest + frontend vitest
make test-backend   # uv sync --all-groups, then pytest
make test-frontend  # vitest with coverage
make test-e2e       # Playwright against a migrated database
make test-ci        # backend + frontend + e2e
```

Or run them directly:

```bash
cd backend && uv run pytest          # 175 passing, 16 skipped without a DB
cd frontend && pnpm run test         # vitest run
cd frontend && pnpm run test:e2e     # prisma migrate deploy + playwright
```

- **Backend** — `backend/tests/`, pytest with `asyncio_mode = "auto"`. Split
  into `tests/unit/` (config, auth headers, billing, AI models/prompt, clip
  editor, video utils/service, YouTube helpers) and `tests/integration/`
  (health, tasks, admin, feedback routes via httpx). Shared fixtures live in
  `tests/conftest.py` and `tests/fixtures/factories.py`.
- **Coverage gate** — `backend/pyproject.toml` sets `--cov-fail-under=65` scoped
  to `src/auth_headers.py` and `src/services/billing_service.py` only, so most
  new code is not covered by the gate. Add tests next to the module you touch.
- **Frontend** — Vitest specs colocated with the code (`src/**/*.test.ts(x)`)
  plus a Playwright end-to-end spec in `frontend/e2e/`.

Place new tests near the code or under `tests/` with clear names (`test_*.py`,
`*.test.ts[x]`). Also run `pnpm run lint` in `frontend/` and smoke test core
flows with `docker-compose` (create task, process clips, view task page).

## Commit & Pull Request Guidelines

Recent history follows [Conventional Commits](https://www.conventionalcommits.org/):

- `type(scope): concise summary` (example: `feat(backend): add task list pagination`).
- One logical change per commit; never bundle unrelated changes.

PRs should include:

- What changed and why.
- Any env/config or migration impact.
- Screenshots/GIFs for UI changes.
- Linked issue(s) and manual verification steps.

## Agent Skills Configuration

Agent-facing conventions live in `docs/agents/`:

- **Issue tracker** — issues live in GitHub Issues on `ianfromnyc/supoclip`, driven via the `gh` CLI. See `docs/agents/issue-tracker.md`.
- **Triage labels** — default five-role vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.
- **Domain docs** — single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Security & Configuration Tips

- Never commit real secrets; use `.env.example` as the template.
- Required runtime keys include `ASSEMBLY_AI_API_KEY` and either one hosted LLM provider key (`OPENAI_API_KEY`, `GOOGLE_API_KEY`, or `ANTHROPIC_API_KEY`) or a self-hosted OpenAI-compatible endpoint (`LLM=openai:*` with `OPENAI_BASE_URL` pointed at your own server, which usually needs no key). `LLM=ollama:*` plus `OLLAMA_BASE_URL` still works as a deprecated prefix reaching the same kind of server; it reads only the `OLLAMA_*` pair.
