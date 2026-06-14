# Contract: Controller Security

## Protected Routes

- `/pool`
- `/metrics`
- `/rotate`
- `/rotate/all`
- `/rotate/{instance}`
- `/repair`
- `/repair/auto`
- `/repair/duplicate-ip`
- `/repair/{instance}`

## Required Behavior

- Controller auth is required whenever controller exposure is not explicitly loopback-only.
- Mutating routes require explicit authenticated operator intent.
- Cookie-authenticated mutating requests must include anti-forgery protection, or mutating requests must require explicit auth headers.
- Fresh read-only pool requests must refresh observed state without scheduling repair.
- Explicit repair requests may schedule repair.
- Overlapping same-instance rotation/repair returns an explicit in-progress outcome.
- Named rotation respects cooldown unless force is explicitly requested.

## Response Semantics

- Unauthorized requests return `401` and never perform side effects.
- Rotation-in-progress requests return an explicit outcome that can be tested without inspecting logs.
- Forced bypass responses include a visible forced/bypass indicator.
- Read-only pool responses do not change rotation counters or repair scheduling counters.
