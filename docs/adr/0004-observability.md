# ADR 0004 — Observability & cost guardrails

## Status

Accepted

## Context

Meridian runs on real GCP (Cloud Run, Pub/Sub, Firestore, Vertex). Without
production telemetry, stage latency only appears in the offline benchmark
harness. Without request correlation, a failed video job is hard to follow
across API → Pub/Sub → worker. Without budget alerts, a runaway demo can burn
credits silently.

## Decision

1. **OpenTelemetry** on API and worker, exporting traces to Cloud Trace and
   metrics to Cloud Monitoring when `MERIDIAN_ENV=production` and
   `MERIDIAN_OTEL_ENABLED=true`. Custom spans wrap each `PipelineStage` and
   worker control-plane stages (`transcribe` / `embed` / `complete`).
2. **Structured JSON logs** (Cloud Logging compatible) with `request_id` and
   `job_id` from contextvars, set by HTTP middleware and re-bound when a worker
   consumes a queue message.
3. **Terraform** enables Monitoring / Trace / Logging APIs, IAM for exporters,
   `google_billing_budget` with optional email notification channel, and
   uptime checks against `/health`.
4. **CI/CD** — PR workflow runs lint, mypy, pytest, security tests, and web
   build; merge to `main` builds/pushes Artifact Registry images and deploys
   Cloud Run when GCP OIDC secrets are configured.

## Consequences

- Local/test environments use no-op / disabled exporters by default.
- Budget alerts require `billing_account` (+ optional `budget_alert_email`).
- Branch protection must require the CI job checks before merge (see
  `.github/BRANCH_PROTECTION.md`).
