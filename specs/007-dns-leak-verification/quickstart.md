# Quickstart: DNS Leak Verification

## Prerequisites

- A generated and running chamosel stack.
- Controller reachable on the configured API port.
- Controller auth token configured when `controller_auth_enabled: true`.
- Live provider credentials only in ignored local files such as `.env.local`.

## Local Automated Validation

```bash
.venv/bin/python -m py_compile chamosel.py controller/controller.py
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Expected outcome: all tests pass, syntax check passes, and no whitespace errors are reported.

## Live Read-Only Validation

```bash
python3 chamosel.py doctor
python3 chamosel.py verify-leaks
python3 chamosel.py verify-dns
python3 chamosel.py verify-dns --json
```

Expected outcome:

- `doctor` reports a reachable, fresh pool.
- `verify-leaks` confirms backend proxy exit IPs do not equal the direct host IP.
- `verify-dns` lists DNS resolvers observed for each healthy backend.
- No command prints provider credentials, WireGuard keys, gluetun API keys, or controller auth tokens.

## Interpreting Suspicious DNS Results

If `verify-dns` reports `suspected_leak: true`, treat it as an investigation signal. It does not rotate tunnels automatically. Compare resolver ASN/country metadata with the backend connection metadata and provider documentation before changing live settings.
