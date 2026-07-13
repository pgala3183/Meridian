# ADR 0002: Meridian security model (v1)

- Status: Accepted
- Date: 2026-07-12
- Deciders: Meridian engineering

## Context

HALO's roadmap left several security items unfinished: API key handling, local path
audits, remote URL validation, dependency scanning, temp-file cleanup, and
prompt-injection tests. Meridian treats those gaps as a differentiator and lands
them before production video ingestion is wired.

## Threat model (v1)

| Asset | Threat | Primary controls |
|---|---|---|
| Provider API keys | Leak via env dumps, logs, or repo | GSM in production; `.env` local-only; boot refuses placeholders / prod env keys |
| Local filesystem | Path traversal (`../`), symlink escape | `PathSandbox` + scratch dirs via `TemporaryDirectory` |
| Server-side fetch | SSRF to metadata / RFC1918 / loopback | HTTPS-only URL validator + DNS IP checks + size/timeout caps |
| LLM context | Prompt injection via transcripts / metadata | `PromptGuard` wrap + pattern scan + answer leak redaction |
| Dependencies | Known CVEs in Python (and later npm) | `pip-audit` / `npm audit` CI + Dependabot |

Attackers in scope for v1: remote unauthenticated API clients supplying URLs or
video-derived text; malicious content inside transcripts; compromised dependency
updates. Out of scope: sophisticated multi-turn jailbreaks against a fully
tool-enabled agent, insider with GCP admin, and physical host compromise.

## Decisions

1. **Secrets.** Production loads secrets exclusively from Google Secret Manager.
   Presence of `OPENAI_API_KEY` / similar in process env during production boot is
   a hard error. Local uses gitignored `.env` (see `.env.example`).
2. **Paths.** All scratch I/O goes through `storage/safe_path.py` sandboxes.
3. **URLs.** `core/security/url_validator.py` validates remote video URLs before
   any download.
4. **Prompt injection.** Defense-in-depth only — see limitations below.
5. **Supply chain.** GitHub Action audits + Dependabot PRs.

## Prompt-injection limitations (honest)

Static detectors and delimiter wrapping **reduce** risk; they do not eliminate it.
Models can still be swayed by novel phrasings, multilingual obfuscation, or
indirect injections that never match our regexes. Meridian therefore:

- Treats transcript/metadata as untrusted data (wrapped + policy preamble).
- Redacts obvious system-prompt echo in answers.
- Does **not** claim "prompt-injection proof" in marketing or design docs.

Interviewers and reviewers should expect this honesty; overclaiming is itself a
security smell.

## Out of scope for v1

- Full WAF / bot management
- Customer-managed KMS envelope encryption for every artifact
- Formal red-team continuous evaluation harness
- Browser XSS hardening for `web/` (scaffold only)
- Blocking all DNS rebinding races under adversarial resolvers (mitigated by
  connect-time IP checks; not perfect)

## Consequences

Positive: clear boot-time fail-closed behavior; testable SSRF/path suites;
CI supply-chain signal. Negative: local onboarding requires copying `.env.example`;
GSM adds an operational dependency for production deploys.
