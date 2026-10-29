# Development, review and release workflow

## Daily work

1. Start from current main and create a descriptive branch, such as
   `feature/gateway-rest-clients`, `fix/request-timeouts` or `chore/update-contracts`.
2. Commit and push work to that branch. Keep the persistent `frontend` branch
   available for frontend development; feature branches can branch from it.
3. Open a pull request into main. CI runs on creation and subsequent PR updates.
4. Resolve review conversations and obtain one approval from another collaborator
   with write access. The PR author cannot approve their own PR. There are no
   mandatory code-owner reviewers, so any eligible teammate may approve.
5. Update the branch against main if needed; checks must pass on an up-to-date
   branch. New reviewable changes invalidate earlier approvals.
6. Merge through the pull request once GitHub confirms all requirements are met.

Main is the integration branch, not a production deployment destination. Direct
unreviewed pushes are blocked, including for repository administrators. Main
cannot be force-pushed or deleted. Development branches remain writable.
Do not delete the persistent frontend branch after merging.

## Automated checks

`.github/workflows/ci.yml` runs on PRs into main, pushes to main/frontend, and
manual dispatch once the workflow is on the default branch. Feature branches
receive checks through their PRs; open a draft PR early for feedback.

| Check | Coverage |
|---|---|
| Python tests | Existing suite; no real model or immigration-source network calls |
| API contracts | Six OpenAPI documents and shared reference resolution |
| Frontend checks | JavaScript syntax, local asset references and duplicate IDs |
| RabbitMQ integration | Existing opt-in test with a temporary real broker |
| CI gate | Succeeds only when all four jobs succeed; failures/skips/cancellations block merging |

Unit tests skip the broker case; the separate integration job explicitly enables
it. Broker credentials are disposable CI-only values, never deployment secrets.
The frontend job uploads a seven-day static artifact. It does not publish a site.
Workflows use read-only repository permissions and pinned action commits.
Do not run untrusted PR code with deployment credentials or pull_request_target.

Main protection is configured remotely, not enforced by the JSON file alone.
`.github/main-protection.json` records the intended policy. CI gate is bound to
the GitHub Actions application; verify its app ID against an observed run before
applying it. A collaborator's approval and a green check are both required.

## Deployment boundary

No production deployment workflow is configured by this change. A merge into
main runs verification and packages frontend assets; it does not automatically
deploy. The existing hosted preview is separate from GitHub deployment automation.

Once the hosting target and backend environment are agreed, add a release
workflow with manual dispatch or release tags, deploy only a verified main
revision, and use a protected production environment for deployment credentials.
Keep previews separate from production. Changes to deployment audiences or
credentials need explicit review rather than being hidden in the test workflow.

## Initial rollout

The CI workflow enters main through the same one-review PR process. Main
protection can be enabled before that PR is merged; existing PRs without the
new gate may remain blocked until the workflow is merged and their branches are
updated. No administrative bypass or self-approval is part of rollout.
