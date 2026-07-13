# Meridian web demo

Next.js (App Router) UI for paste-URL / upload → job polling → cited Q&A with
seekable timestamps and a live pipeline explainer.

## Local

```bash
# terminal 1 — API (from repo root)
MERIDIAN_ENV=test uv run uvicorn meridian.api.main:app --reload --port 8000

# terminal 2 — web
cd web
cp .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000

Demo traffic uses `X-API-Key: demo-web` (shared rate-limited quota).

## Cloud Run

```bash
docker build -t meridian-web \
  --build-arg NEXT_PUBLIC_MERIDIAN_API_URL=https://YOUR_API_URL \
  .
# push + deploy; see infra/terraform web service
```

`NEXT_PUBLIC_MERIDIAN_API_URL` is baked in at build time for the browser client.
