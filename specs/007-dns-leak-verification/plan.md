# Implementation Plan: DNS Leak Verification

**Branch**: `007-dns-leak-verification` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/007-dns-leak-verification/spec.md`

## Summary

Add a read-only `verify-dns` operator command that checks each healthy backend's DNS resolver path through its HTTP proxy, reports resolver metadata in table/JSON form, and documents cautious live validation. The implementation extends the existing CLI leak-verification path, reuses `/pool?fresh=1` and backend proxy probe execution, and avoids controller runtime changes.

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: CLI uses `pyyaml` and `jinja2`; controller remains stdlib-only; DNS verification uses Python stdlib plus Docker Compose execution already used by `verify-leaks`.

**Storage**: None. DNS verification is read-only and does not persist reports unless the operator redirects JSON output.

**Testing**: `.venv/bin/python -m unittest discover -s tests -v`; syntax check with `.venv/bin/python -m py_compile chamosel.py controller/controller.py`; whitespace check with `git diff --check`.

**Target Platform**: Docker Compose deployment on Linux/macOS host with gluetun backends and a controller container.

**Project Type**: Python CLI plus stdlib-only controller service.

**Performance Goals**: DNS verification should complete within the configured timeout per healthy backend; default live probe uses a small fixed number of DNS trigger requests per backend.

**Constraints**: No provider credentials or auth tokens in output; no automatic rotation or repair; controller auth headers must be honored when fetching pool state; no new controller dependencies.

**Scale/Scope**: Pools of 1-10 backends are the primary live target; larger pools should still work but DNS verification is a diagnostic command, not a high-frequency poll.

## Constitution Check

- **Control Plane Security**: Pass. The feature reuses existing controller auth for `/pool?fresh=1`, does not expose new controller endpoints, and must keep tokens/provider secrets out of JSON, tables, logs, and docs.
- **Health-Aware Rotation**: Pass. DNS verification is read-only and never changes gluetun status, cooldowns, HAProxy health checks, or forced rotation behavior.
- **Observability and State**: Pass. Operator-visible output is a new CLI report with per-backend resolver details; no persisted controller state is required.
- **Configuration Discipline**: Pass. Generated Docker Compose, HAProxy, `.env`, and gluetun config are unchanged. README and examples document the command and live validation sequence.
- **Testable Operations**: Pass. Unit tests cover successful DNS verification, suspicious resolver detection, probe failures, unhealthy backend handling, JSON/table output, parser help, and README guidance.

## Project Structure

### Documentation (this feature)

```text
specs/007-dns-leak-verification/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── verify-dns.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
chamosel.py                    # CLI command, DNS probe script, report rendering
README.md                      # operator docs and live validation sequence
tests/test_verify_leaks.py     # CLI/report tests for DNS verification
```

**Structure Decision**: Keep DNS verification in `chamosel.py` alongside existing `verify-leaks` because it reuses the same pool fetch, Docker Compose backend probe, JSON/table rendering, and CLI parser patterns.

## Complexity Tracking

No constitution violations.
