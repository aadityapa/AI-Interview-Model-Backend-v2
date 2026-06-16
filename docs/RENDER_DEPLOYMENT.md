# Deploy Backend on Render

Repo: [AI-Interview-Model-Backend-v2](https://github.com/aadityapa/AI-Interview-Model-Backend-v2)

This backend is **API-only** on Render. The UI lives in the separate frontend repo (`AI-Interview-Model-F-V2`).

## 1. Push code to GitHub

```bat
cd D:\AI-Interview-Model-B-V2
git remote set-url origin https://github.com/aadityapa/AI-Interview-Model-Backend-v2.git
git push -u origin main
```

## 2. Create Render Web Service

1. [Render Dashboard](https://dashboard.render.com/) → **New** → **Web Service**
2. Connect GitHub repo `aadityapa/AI-Interview-Model-Backend-v2`
3. Settings:
   - **Runtime:** Docker
   - **Branch:** `main`
   - **Health Check Path:** `/health/live`

Or use **New → Blueprint** and upload `render.yaml` from this repo.

## 3. Add PostgreSQL

1. **New → PostgreSQL** (free tier) or use the `karnex-db` database from the Blueprint
2. Copy the **Internal Database URL**
3. Set env var on the web service:

```
AUTH_DB_URL=postgresql://user:pass@host/dbname?sslmode=require
```

Use the **Internal Database URL** from Render when the web service and Postgres are in the same region (faster). Append `?sslmode=require` if connecting via the external hostname.

## 4. Required environment variables

| Variable | Example | Notes |
|----------|---------|-------|
| `OPENAI_API_KEY` | `sk-...` | Required for AI features |
| `AUTH_SECRET` | long random string | JWT signing (32+ chars) |
| `REPORT_CODE` | random secret | Report download protection |
| `AUTH_DB_URL` | from Render Postgres | Required for auth/data |
| `CORS_ALLOW_ORIGINS` | `https://your-frontend.onrender.com` | Frontend URL(s), comma-separated |
| `PUBLIC_BASE_URL` | `https://your-frontend.onrender.com` | Used in interview invite emails |
| `UVICORN_WORKERS` | `1` | Keep at 1 until Redis session store |

Optional SMTP vars for interview invite emails: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS=true`

**Never commit `.env` to GitHub.**

## 5. Verify deployment

```bash
curl https://YOUR-SERVICE.onrender.com/health/live
curl https://YOUR-SERVICE.onrender.com/health/ready
```

## 6. Connect frontend

Point your frontend deployment at the Render API URL:

- **Vite admin dev:** `VITE_BACKEND_URL=https://YOUR-SERVICE.onrender.com`
- **Production static UI:** configure the frontend to call the Render API base URL and add that frontend origin to `CORS_ALLOW_ORIGINS`

Local split-repo workflow is unchanged — see frontend `docs/BACKEND_CONNECTION.md`.

## Notes

- Render free tier spins down after inactivity; first request may be slow (~30s).
- Container filesystem is ephemeral — use Postgres (`AUTH_DB_URL`), not local SQLite, in production.
- HTTPS is terminated by Render; run uvicorn on HTTP internally (`PORT` env is set automatically).
