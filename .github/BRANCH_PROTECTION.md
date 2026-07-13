# Branch protection (main)

Require CI to pass before merging to `main`. GitHub cannot set this from a
workflow without admin permissions — apply once via the UI or `gh`:

```bash
gh api -X PUT "repos/{owner}/{repo}/branches/main/protection" \
  -H "Accept: application/vnd.github+json" \
  -f required_status_checks='{"strict":true,"contexts":["Lint, typecheck, unit tests","Security tests & audits","Web typecheck & build"]}' \
  -F enforce_admins=true \
  -F required_pull_request_reviews='{"required_approving_review_count":0}' \
  -F restrictions= \
  -F allow_force_pushes=false \
  -F allow_deletions=false
```

Or in the GitHub UI: **Settings → Branches → Add rule** for `main`:

- Require a pull request before merging (optional for solo repos)
- Require status checks to pass: the three CI job names above
- Do not allow bypassing the above settings

## Deploy secrets (GitHub → GCP)

For `.github/workflows/deploy.yml`, configure:

| Name | Kind | Purpose |
|------|------|---------|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | secret | WIF provider resource name |
| `GCP_SERVICE_ACCOUNT` | secret | Deployer SA email |
| `GCP_PROJECT_ID` | variable | Target project |
| `GCP_REGION` | variable | e.g. `us-central1` |
| `ARTIFACT_REPO` | variable | Artifact Registry repo id (`meridian`) |

Deploy is skipped when `GCP_PROJECT_ID` is unset so forks stay green.
