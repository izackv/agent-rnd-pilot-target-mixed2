# agent-rnd-pilot-target-mixed2

**Disposable sandbox** for the Agent Team R&D Platform pilot — **Phase 2d mixed-team v2 comparison copy** (same baseline, same gate; five local agents plus a hosted Architect and a hosted Gate Reviewer on security-flagged PRs only). Agent teams work on this repo
during trials; the control repo (`agent-rnd-control`, private) owns the plan, policies and
results. This repo is public only so that GitHub merge rules can be enforced on it (Free plan).

Nothing here is a real product. Contents may be reset between trials.

See `docs/index.md` for the app, tests and the documentation policy. Required CI checks:
`lint`, `unit`, `integration`, `e2e`, `docs`, `security`. Releases go through the `release`
workflow, whose `production` environment requires the owner's approval.
