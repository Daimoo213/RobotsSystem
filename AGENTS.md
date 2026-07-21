# Repository Guidelines

## Project Structure & Module Organization

`backend/app/` contains the FastAPI service. Keep routes in `api/`, WebSockets in `ws/`, infrastructure in `core/`, persistence models in `models/`, and scheduling logic in `scheduler/`. `frontend/` is a pnpm workspace: `apps/pm` and `apps/om` are the Vite applications; `packages/` holds reusable UI, client, types, 3D, and utility code. `manager/` contains the standalone process manager. Root `build_*.py` scripts generate documents and spreadsheets.

## Build, Test, and Development Commands

- `docker compose up -d postgres redis` starts required local services.
- `cd backend && pip install -r requirements.txt` installs Python dependencies.
- `cd backend && uvicorn app.main:app --reload --port 8000` runs the API; Swagger UI is at `http://localhost:8000/docs`.
- `cd frontend && pnpm install` installs all workspace dependencies.
- `cd frontend && pnpm dev:pm` or `pnpm dev:om` starts the PM app on 5173 or the O&M app on 5174.
- `cd frontend && pnpm build` type-checks and builds both applications.
- `docker compose up -d` starts the containerized database, Redis, and backend.

## Coding Style & Naming Conventions

Use four spaces, type hints, and concise docstrings in Python. Prefer async APIs for database and Redis work; modules and functions use `snake_case`, classes use `PascalCase`. TypeScript and TSX use two spaces, single quotes, semicolons, and strict compiler settings. Name React components and files `PascalCase` (for example, `DashboardPage.tsx`), hooks `useSomething`, and utilities `camelCase`. Reuse `@robots/*` packages instead of duplicating shared code.

## Testing Guidelines

Backend test dependencies are installed, but no tests are committed. Add `backend/tests/test_*.py` files using `pytest` and `pytest-asyncio`; run `cd backend && pytest`. No frontend test runner or coverage threshold is configured. At minimum, run `pnpm build`; add colocated `*.test.ts(x)` files with a documented runner for substantial client logic.

## Commit & Pull Request Guidelines

Git metadata is absent from this workspace snapshot, so historical conventions cannot be verified. Use concise Conventional Commit subjects such as `feat(pm): add task filters` or `fix(api): handle Redis timeout`. Keep commits scoped to one concern. Pull requests should explain behavior and verification, link relevant issues, note configuration or schema changes, and include screenshots for PM/O&M visual changes.

## Security & Configuration

Treat `backend/.env` as local-only and never commit credentials or tokens. Docker Compose credentials are development defaults; replace them in deployed environments. Avoid committing logs, caches, generated build output, or `node_modules/`.
