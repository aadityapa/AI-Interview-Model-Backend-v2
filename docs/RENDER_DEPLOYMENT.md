# Deploy Backend on Render (AWS RDS database)

Repo: [AI-Interview-Model-Backend-v2](https://github.com/aadityapa/AI-Interview-Model-Backend-v2)

- **Backend:** Render Web Service (Docker)
- **Database:** AWS RDS PostgreSQL (or any managed Postgres)
- **Frontend:** Vercel — production at `https://interview.karnex.in` (preview: `https://ai-interview-model-frontend-v2.vercel.app`)

## 1. Render Web Service

1. [Render Dashboard](https://dashboard.render.com/) → **New** → **Web Service**
2. Connect `aadityapa/AI-Interview-Model-Backend-v2`
3. **Runtime:** Docker · **Health check:** `/health/live`
4. Do **not** add a Render PostgreSQL instance — use your external RDS database.

## 2. AWS RDS connection string

In AWS RDS: **Connectivity & security** → copy the endpoint and use your database name (e.g. `karnex_db`).

Set on Render as `AUTH_DB_URL` (or `DATABASE_URL` — both work). Example shape:

```
postgresql://postgres:[PASSWORD]@database-1.xxxxx.ap-south-1.rds.amazonaws.com:5432/karnex_db
```

`sslmode=require` is added automatically for RDS. **Never commit this URL to GitHub.**

**RDS security group:** allow inbound **PostgreSQL (5432)** from Render. On the free tier, you may need `0.0.0.0/0` temporarily, or use a paid static outbound IP on Render.

## 3. Required Render environment variables

| Variable | Value |
|----------|--------|
| `AUTH_DB_URL` | Your RDS connection URI |
| `OPENAI_API_KEY` or per-purpose keys | Your OpenAI keys |
| `AUTH_SECRET` | Long random string (32+ chars) |
| `REPORT_CODE` | Random secret |
| `CORS_ALLOW_ORIGINS` | `https://interview.karnex.in,https://ai-interview-model-frontend-v2.vercel.app` |
| `PUBLIC_BASE_URL` | `https://interview.karnex.in` |
| `ALLOW_PUBLIC_HR_REGISTRATION` | `true` (until first HR user exists) |
| `SMTP_ENABLED` | `false` |
| `UVICORN_WORKERS` | `1` |

## 4. Verify

```bash
curl https://YOUR-SERVICE.onrender.com/health/ready
```

Expect `"database_connected": true` and `"database_backend": "postgresql"`.

## 5. Frontend (Vercel)

Production domain: **https://interview.karnex.in** (add in Vercel → Project → Settings → Domains).

API routes are proxied via `vercel.json` to your Render backend URL. Invite links use `PUBLIC_BASE_URL` on Render — must match this domain.

## Notes

- Render free tier sleeps after inactivity (~30–60s cold start).
- SMTP is off by default; invite emails are skipped until you set `SMTP_ENABLED=true` and SMTP credentials.
- Use RDS in the same region as Render (e.g. `ap-south-1`) when possible for lower latency.
