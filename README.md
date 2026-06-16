# KARNEX AI HR — Backend (API)

**Release:** Version 1.0.0

FastAPI backend for the KARNEX AI Interview Suite. UI lives in the sibling frontend repo:

`D:\AI-Interview-Model-F-V2`

## Project Structure

- `backend/` — FastAPI app, AI logic, evaluation, auth
- `services/` — Phase 1 microservice sidecars + API gateway (Docker)
- `data/` — Runtime data (created at startup)
- `logs/` — Server logs
- `scripts/` — `run_backend.cmd`, `get_lan_ip.ps1`, `smoke_test.py`

## Quick Start (Windows)

**Terminal 1 — build UI (frontend repo):**
```bat
cd D:\AI-Interview-Model-F-V2
start_frontend.bat
```

**Terminal 2 — start API:**
```bat
cd D:\AI-Interview-Model-B-V2
copy .env.example .env
start_app.bat
```

HTTP mode (no cert warning): `start_app.bat --http`

Dev without browser: `start_app.bat --no-browser`

## Environment (`.env`)

Copy `.env.example` → `.env`. Key settings:

- `OPENAI_API_KEY`, `AUTH_SECRET`, `REPORT_CODE`
- `FRONTEND_DIR=D:\AI-Interview-Model-F-V2\frontend` (auto-detected if sibling)
- `AUTH_DB_URL` — Postgres; remove to use SQLite locally

## Microservices (Docker)

```bat
docker compose -f docker-compose.yml -f docker-compose.microservices.yml up -d --build
```

Gateway: http://localhost:8080

## Verify

```bat
python scripts\smoke_test.py
curl http://127.0.0.1:2020/health/live
```

## Frontend repo

UI build and Vite dev server: `D:\AI-Interview-Model-F-V2\start_frontend.bat`

See frontend `docs/BACKEND_CONNECTION.md` for full connection guide.

## GitHub & Render deployment

- **Repo:** https://github.com/aadityapa/AI-Interview-Model-Backend-v2
- **Guide:** [docs/RENDER_DEPLOYMENT.md](docs/RENDER_DEPLOYMENT.md)

Quick push:

```bat
git remote set-url origin https://github.com/aadityapa/AI-Interview-Model-Backend-v2.git
git push -u origin main
```

On Render: **New Web Service** → connect repo → **Docker** runtime → set env vars from `.env.example` → health check `/health/live`.
