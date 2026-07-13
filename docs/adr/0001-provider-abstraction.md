# ADR 0001: Multi-provider adapter abstraction

- Status: Accepted
- Date: 2026-07-12
- Deciders: Meridian engineering

## Context

HALO, Meridian's predecessor, was hardcoded to Google Gemini. That coupling was already
called out on HALO's own roadmap ("Add provider adapters for OpenAI, Anthropic, Gemini,
and local models") because it blocked cost comparison, vendor negotiation, and failover
when a single backend degraded.

Meridian is being rebuilt as a production video-intelligence platform on GCP. The default
path still uses Gemini, but through **Vertex AI** (service-account / ADC auth, Cloud Billing,
Cloud Monitoring) rather than the consumer Gemini API. We also need secondary adapters so
benchmarks and customers are not locked to one vendor's pricing or feature set.

## Decision

Introduce a provider-agnostic `MultimodalProvider` interface with four async methods:

1. `transcribe(audio) -> Transcript`
2. `embed_text(text) -> Embedding`
3. `answer_question(context, question, images=[]) -> GroundedAnswer`
4. `estimate_cost(request) -> CostEstimate`

Concrete adapters live under `meridian/providers/`:

| Adapter | Role | Backend |
|---|---|---|
| `GeminiProvider` | Default / primary | `google-genai` client with `vertexai=True` |
| `OpenAIProvider` | Secondary | OpenAI chat, Whisper, embeddings |
| `AnthropicProvider` | Secondary | Anthropic Messages (text + vision) |

A factory (`providers/factory.py`) selects the adapter from config and defaults to Gemini
on Vertex.

Unsupported capabilities (e.g. Anthropic transcription/embeddings) raise
`ProviderCapabilityError` rather than inventing a silent fallback. Callers decide how to
compose providers (e.g. Whisper via OpenAI + Claude for Q&A).

## Consequences

### Positive

- **Portability:** Core pipeline code depends on the interface, not an SDK.
- **Cost visibility:** `estimate_cost` makes benchmarking and budget gates first-class,
  without requiring live paid calls.
- **Infra alignment:** Vertex mode keeps Gemini usage inside GCP IAM, billing, and
  monitoring — required for the later Terraform / Cloud Run story.
- **Honest capability boundaries:** Missing APIs fail loudly instead of degrading quality.

### Negative / tradeoffs

- **Lowest common denominator:** The shared interface cannot expose Gemini-only
  video-native features (native video understanding, long-context Vertex tooling, etc.).
  Provider-specific power requires narrowing to a concrete type or a future optional
  capability interface.
- **Duplicated pricing tables:** Approximate USD rates live in adapters and drift from
  vendor list prices; they must be treated as estimates and overridden via config for
  serious finance work.
- **Composition burden:** Pipelines that need Anthropic answers plus OpenAI embeddings
  must wire two providers (or a façade) themselves — the factory returns one provider
  per call.
- **Test surface:** Each adapter needs mocked-client unit tests; integration tests against
  live APIs remain a separate, opt-in concern.

### Alternatives considered

1. **Stay Gemini-only (HALO model)** — Rejected; repeats the roadmap debt we are fixing.
2. **Consumer Gemini API + API keys** — Rejected for production; weak billing/monitoring
   attribution compared to Vertex + service accounts.
3. **Per-operation strategy objects** (separate Transcriber / Embedder / Answerer) —
   Deferred. Cleaner for mixed-vendor pipelines, but heavier for v0 when most deployments
   will pick one primary provider. Can evolve from this interface later.
4. **LangChain / LlamaIndex abstractions** — Rejected for core. Useful optionally at the
   edges, but too heavy and version-volatile for Meridian's core contract.

## Notes

Local / open-weight models are intentionally out of scope for this ADR; the registry is
extensible and can add a `local` provider later without changing call sites that already
depend on `MultimodalProvider`.
