# Meridian

[![CI](https://github.com/pgala3183/Meridian/actions/workflows/ci.yml/badge.svg)](https://github.com/pgala3183/Meridian/actions/workflows/ci.yml)
[![Benchmarks](https://github.com/pgala3183/Meridian/actions/workflows/benchmarks.yml/badge.svg)](https://github.com/pgala3183/Meridian/actions/workflows/benchmarks.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/frontend-Next.js-black.svg)](web/)

Meridian is a grounded video Q&A platform for long-form content. Paste a YouTube URL,
wait for its timed transcript and hierarchical index, then ask questions and jump directly
to the cited moments in the video.

The project goes beyond a chat demo: it includes asynchronous processing, structured
citations, measurable retrieval quality, cost and latency benchmarks, OpenTelemetry
instrumentation, Terraform-managed Google Cloud infrastructure, and gated CI/CD.

## Live Gemini benchmark

Full live evaluation on Vertex AI Gemini 2.5 Flash across **12 videos and 84 labeled
questions** (72 answerable, 12 unanswerable):

| Metric | Result |
|---|---:|
| Retrieval recall@3 | **89.8%** |
| Mean reciprocal rank | **0.824** |
| nDCG@3 | **0.835** |
| Citation precision / recall | **89.6% / 89.8%** |
| Refusal accuracy (answerable / unanswerable) | **97.2% / 91.7%** |
| Estimated cost reduction vs full-transcript baseline | **37.2%** |
| Q&A latency p50 / p95 | **1.34s / 3.78s** |
| Answer quality (heuristic overall) | **0.877** |

The suite spans lectures, interviews, product demos, podcasts, tutorials, panels, news,
and code walkthroughs. Gold timestamp spans support recall@k, MRR, nDCG, and citation
scoring. See the [full benchmark report](docs/benchmarks/latest_report.md), the
[machine-readable results](docs/benchmarks/latest_results.json), and the
[evaluation methodology](docs/benchmarks/README.md).

> Quality uses deterministic rubric scoring on synthetic, checked-in transcripts — not
> human ground truth. Cost is estimated from token counts, not billing exports. Repeat-query
> cache hits skip re-indexing but still call Gemini, so end-to-end latency stays ~1x on
> warm runs in this eval harness.

## Product flow

1. Submit a YouTube URL through the Next.js interface.
2. The FastAPI service enqueues a video-processing job.
3. A worker fetches timed captions, creates semantic chunks, and builds a hierarchical index.
4. The UI polls job status and unlocks grounded Q&A when processing completes.
5. Gemini answers from transcript evidence and returns timestamped citations.
6. Clicking a citation seeks the embedded player to the supporting moment.

## Architecture

```text
Next.js web
    |
    v
FastAPI API ---- job state ---- Firestore / in-memory
    |
    +---- Pub/Sub ---- Cloud Run worker
                         |
                         +---- YouTube transcript ingest
                         +---- semantic chunking + hierarchy
                         +---- GCS / local object storage
                                      |
                                      v
                              retrieval + Gemini Q&A
```

Production telemetry uses OpenTelemetry spans and metrics exported to Google Cloud
Trace and Monitoring. Structured JSON logs carry request and job IDs through the
API-to-worker path.

## Technology

- **Backend:** Python 3.11, FastAPI, Pydantic, Google Gen AI SDK
- **Frontend:** Next.js App Router, TypeScript, Tailwind CSS
- **Cloud:** Cloud Run, Pub/Sub, GCS, Firestore, Artifact Registry
- **Operations:** OpenTelemetry, Cloud Monitoring, Cloud Trace, structured logging
- **Infrastructure:** Terraform with budget alerts and uptime checks
- **Quality:** pytest, Ruff, mypy, pip-audit, npm audit, benchmark regression gates

## Local setup

### Prerequisites

- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- Google Cloud CLI
- A Google Cloud project with Vertex AI enabled

### 1. Configure Google Cloud credentials

```powershell
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

Copy `.env.example` to `.env`, then set:

```dotenv
MERIDIAN_ENV=local
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=us-central1
MERIDIAN_GEMINI_MODEL=gemini-2.5-flash
MERIDIAN_STORAGE_BACKEND=local
MERIDIAN_JOB_STORE=memory
```

No Gemini API key is required when using Vertex AI; Meridian uses Application Default
Credentials. Never commit `.env`.

### 2. Start the API

```powershell
uv sync --extra dev
uv run uvicorn meridian.api.main:app --reload --port 8000
```

Health endpoints:

- `GET http://localhost:8000/health`
- `GET http://localhost:8000/ready`
- API documentation: `http://localhost:8000/docs`

### 3. Start the web app

In another terminal:

```powershell
cd web
npm ci
$env:NEXT_PUBLIC_MERIDIAN_API_URL = "http://localhost:8000"
npm run dev
```

Open `http://localhost:3000`.

For local development, the API uses in-memory jobs and executes processing without
requiring Pub/Sub. Production uses the same job contract with Google Cloud services.

## Tests and evaluation

Run the complete test suite:

```powershell
uv run ruff check meridian tests
uv run ruff format --check meridian tests
uv run mypy meridian
uv run pytest -q
```

Run the offline, deterministic evaluation and enforce regression thresholds:

```powershell
uv run python -m tests.benchmarks.run_eval --pin-checksums --check-thresholds
```

Run a budget-conscious live Gemini evaluation:

```powershell
uv run python -m tests.benchmarks.run_eval --provider gemini --limit 3 --no-cached
```

Remove `--limit 3 --no-cached` to evaluate all 84 questions and include cached repeats.
Live runs call Vertex AI and incur usage charges.

CI enforces:

- Python linting, formatting, strict type checking, and unit/security tests
- Frontend linting, type checking, production build, and dependency audit
- Offline retrieval, citation, cost, and latency regression thresholds
- Docker build and Cloud Run deployment after the main branch passes CI

## Repository layout

```text
meridian/
  api/              FastAPI routes and grounded Q&A orchestration
  core/             chunking, retrieval, hierarchy, cache, pipeline
  ingest/           YouTube transcript ingestion
  jobs/             job models, queues, and state stores
  observability/    logging, tracing, metrics, request context
  providers/        Gemini, OpenAI, and Anthropic adapters
  workers/          asynchronous video processing and indexing
web/                Next.js demo interface
tests/
  unit/             deterministic unit and integration-style tests
  security/         prompt injection, SSRF, path, and secret tests
  benchmarks/       versioned dataset, metrics, judges, and report generator
infra/terraform/    Google Cloud infrastructure and cost guardrails
docs/               ADRs and published benchmark artifacts
```

## Deployment

Terraform provisions the Google Cloud services, service accounts, IAM permissions,
budget notification channel, and uptime checks. GitHub Actions builds API, worker,
and web images, pushes them to Artifact Registry, and deploys to Cloud Run.

Start with [`infra/terraform/terraform.tfvars.example`](infra/terraform/terraform.tfvars.example)
and [`.github/BRANCH_PROTECTION.md`](.github/BRANCH_PROTECTION.md).

## Design decisions

Architecture decisions are documented under [`docs/adr/`](docs/adr/), including provider
abstraction, asynchronous processing, security boundaries, and observability.
