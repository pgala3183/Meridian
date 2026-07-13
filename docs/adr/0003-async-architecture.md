# ADR 0003: Async video processing on GCP

- Status: Accepted
- Date: 2026-07-12
- Deciders: Meridian engineering

## Context

Long-form video intelligence cannot run inside a synchronous HTTP request:
transcription, embedding, and hierarchy builds routinely exceed Cloud Run
request deadlines and would tie up API capacity. HALO-style local CLI flow
does not survive multi-tenant cloud spend.

We also need fan-out: transcription workers and embedding/indexing workers may
scale independently as load shapes diverge.

## Decision

### Queue: **Pub/Sub** (not Cloud Tasks)

| Option | Pros | Cons |
|---|---|---|
| Cloud Tasks | Per-task HTTP dispatch, built-in retries, scheduling | One target queue → one handler; awkward fan-out |
| **Pub/Sub** | Native fan-out (one topic, many subscriptions), push to Cloud Run, DLQ | At-least-once delivery requires idempotent workers |

We choose **Pub/Sub** because Meridian's roadmap includes separate worker pools
(transcribe vs embed vs index). A single `meridian-video-jobs` topic can push
to multiple Cloud Run services without the API knowing topology.

Cloud Tasks remains appropriate later for **deferred single-target** work
(e.g. webhook retries with exact ETA).

### Compute: **Cloud Run services** for API + workers

- **API service:** `POST /videos` enqueues and returns `job_id` (HTTP 202).
- **Worker service:** Pub/Sub push to `/pubsub/push`; processes job; updates Firestore.
- Cloud Run Jobs are reserved for batch backfills, not the interactive path.

### State: **Firestore**

Job status and cache-index metadata are document-shaped point lookups. See
`docs/architecture/data-model.md`. Blobs stay in GCS.

### Why not process in the API container?

Keeps request latency and blast radius small, enables independent autoscaling
and IAM (API SA can publish; worker SA can read GCS + write Firestore).

## Consequences

- Workers must be **idempotent** (Pub/Sub redelivery).
- Clients poll `GET /videos/{job_id}/status` or subscribe to SSE `/events`.
- Terraform provisions topic, push subscription, dual Cloud Run services, GCS,
  Firestore, Secret Manager, and least-privilege SAs.

## Alternatives rejected

1. **Inline FastAPI BackgroundTasks** — lost on instance kill; no fan-out.
2. **Cloud Tasks only** — insufficient for multi-worker topology.
3. **GKE** — operational overhead unjustified at current scale.
