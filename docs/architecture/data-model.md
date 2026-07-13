# Meridian data model (v1)

## Choice: Firestore (document) over Cloud SQL

We store **job lifecycle state** and **cache index pointers**, not heavy
relational analytics. Firestore fits because:

- Job documents are naturally keyed by `job_id` with nested maps (`artifact_uris`).
- Cache index lookups are point-gets by `cache_key` (content hash).
- No multi-row joins in the v1 hot path; object blobs live in GCS.
- Scales with Cloud Run without connection-pool babysitting.

Cloud SQL remains an option if we later need strong relational reporting;
see ADR 0003.

## Collections

### `video_jobs` (document id = `job_id`)

| Field | Type | Notes |
|---|---|---|
| `job_id` | string | UUID |
| `user_id` | string | Auth / rate-limit identity |
| `video_id` | string | Caller-supplied stable id |
| `source_uri` | string \| null | `https://` or `gs://` |
| `status` | enum | `queued` \| `running` \| `succeeded` \| `failed` \| `cancelled` |
| `stage` | enum | `ingest` \| `transcribe` \| `embed` \| `index` \| `complete` |
| `progress` | number | 0.0–1.0 |
| `error_message` | string \| null | Set on failure |
| `artifact_uris` | map<string,string> | e.g. `transcript`, `context_tree`, `keyframes/...` |
| `cache_key` | string \| null | Content-hash cache key |
| `webhook_url` | string \| null | Optional completion callback |
| `created_at` / `updated_at` / `completed_at` | timestamp | UTC |
| `extra` | map | Forward-compatible bag |

**Indexes:** single-field on `user_id`, `status`, `video_id` (composite later if listing filters grow).

### `cache_index` (document id = `cache_key`)

| Field | Type | Notes |
|---|---|---|
| `cache_key` | string | SHA-256 of video fingerprint + chunking/pipeline params |
| `video_id` | string | |
| `object_uri` | string | `gs://…` or local URI of serialized `ContextTree` |
| `content_hash` | string \| null | Raw media hash |
| `created_at` / `expires_at` | timestamp | TTL policy applied by sweeper (future) |

## Object storage layout (GCS / local)

```
videos/{video_id}/transcripts/full.json
videos/{video_id}/context/tree.json
videos/{video_id}/keyframes/{timestamp}.jpg
videos/{video_id}/cache/{cache_key}.pkl
```

Firestore holds **pointers**; GCS holds **bytes**.
