# Quickstart: Production Security Hardening Validation

## Prerequisites

- Python 3.10+ virtual environment with `requirements.txt` installed.
- Docker and Docker Compose v2 available for template validation.
- No live VPN credentials are required for automated validation.

## Automated Validation

```sh
.venv/bin/python -m py_compile chamosel.py controller/controller.py
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

## Security Behavior Checks

1. Generate default config and confirm proxy, API, and stats bind locally.
2. Configure non-loopback controller bind without controller auth and confirm generation fails.
3. Configure non-loopback proxy bind without explicit public proxy protection and confirm generation fails.
4. Configure non-loopback stats bind without stats protection and confirm generation fails.
5. Run read-only pool, leak, DNS, and doctor test paths and confirm rotation counters and repair scheduling counters do not change.
6. Trigger overlapping same-backend rotations in tests and confirm one request reports rotation in progress.
7. Feed DNS verification payloads without connection IP or strict ASN evidence and confirm they fail.
8. Run doctor against mutable image references and confirm production warnings are shown.

## Optional Live Validation

After automated tests pass and live credentials are configured:

```sh
python3 chamosel.py up --no-pull
python3 chamosel.py doctor --json
python3 chamosel.py verify-leaks --json
python3 chamosel.py verify-dns --json
```

Expected live outcome: no secrets in output, read-only diagnostics do not rotate backends, non-loopback exposure requires explicit protection, and any unsafe exposure or runtime-hardening gap is visible before production traffic is allowed.
