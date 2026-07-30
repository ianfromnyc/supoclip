# Repository Guidelines

## Project Structure & Module Organization
This repository is a monorepo with three apps:
- `backend/`: FastAPI + async worker code (`src/api`, `src/services`, `src/repositories`, `src/workers`).
- `frontend/`: main Next.js app (`src/app`, `src/components`, `src/lib`, `prisma/`).
- `mcp/`: standalone `supoclip-mcp` server, a thin client over the REST API.

Infra and bootstrap files live at the root: `docker-compose.yml`, `init.sql`, `.env.example`, `Makefile`, and `start.sh`.

## Build, Test, and Development Commands
Use Docker for full-stack development:
- `docker-compose up -d --build`: start frontend, backend, mcp, worker, Postgres, and Redis.
- `docker-compose logs -f`: stream service logs.
- `docker-compose down`: stop everything.

Local app commands:
- `cd frontend && pnpm run dev`: run Next.js in dev mode (port 3107).
- `cd frontend && pnpm run build && pnpm run start`: production build + serve.
- `cd frontend && pnpm run lint`: run ESLint.
- `cd backend && uv sync && uvicorn src.main_refactored:app --reload --host 0.0.0.0 --port 8000`: run API locally. `src/main.py` is the legacy monolithic entry point; Compose runs `src.main_refactored:app`.
- `cd backend && .venv/bin/arq src.workers.tasks.WorkerSettings`: run the worker.

## Coding Style & Naming Conventions
- Python: 4-space indentation, type hints where practical, `snake_case` for functions/modules.
- TypeScript/React: 2-space indentation, `PascalCase` for component names, `camelCase` for variables/functions, route files in Next.js App Router conventions (`app/.../page.tsx`, `route.ts`).
- Linting: Next.js ESLint config in `frontend/eslint.config.mjs`.
- Imports: use the `@/*` alias in Next.js apps when possible.

## Testing Guidelines
Both apps have automated tests and CI runs them (`.github/workflows/tests.yml`). Use the root `Makefile`, which supplies the DB/Redis/auth env vars the suites need:
- `make test`: backend pytest + frontend vitest.
- `make test-backend`: `uv sync --all-groups` then pytest (`backend/tests/`, currently 113 passing / 12 skipped).
- `make test-frontend`: vitest with coverage.
- `make test-e2e`: `prisma migrate deploy` then Playwright (`frontend/e2e/`).

Also run `pnpm run lint` in `frontend/` and smoke test core flows with `docker-compose` (create task, process clips, view task page).

Place new tests near the code or under `tests/` with clear names (`test_*.py`, `*.test.ts[x]`). Backend pytest runs in `asyncio_mode = "auto"`; the `--cov-fail-under=65` gate in `backend/pyproject.toml` is scoped to `src/auth_headers.py` and `src/services/billing_service.py` only.

## Commit & Pull Request Guidelines
Recent history favors short imperative commit subjects (`Add list endpoint`, `Fix typo`, `improve UX`). Prefer:
- `type(scope): concise summary` (example: `feat(backend): add task list pagination`).
- One logical change per commit.

PRs should include:
- What changed and why.
- Any env/config or migration impact.
- Screenshots/GIFs for UI changes.
- Linked issue(s) and manual verification steps.

## Security & Configuration Tips
- Never commit real secrets; use `.env.example` as the template.
- Required runtime keys include `ASSEMBLY_AI_API_KEY` and either one hosted LLM provider key (`OPENAI_API_KEY`, `GOOGLE_API_KEY`, or `ANTHROPIC_API_KEY`) or an OpenAI-compatible endpoint (`LLM=openai:*` with `OPENAI_BASE_URL`, which usually needs no key). `LLM=ollama:*` plus `OLLAMA_BASE_URL` still works as a deprecated alias of that path.
