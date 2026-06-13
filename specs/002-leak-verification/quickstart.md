# Quickstart: Leak Verification

## Automated Validation

Run from the repository root:

```bash
python3 -m py_compile chamosel.py controller/controller.py
python3 -m unittest discover -s tests -v
git diff --check
```

Expected result:

- Syntax checks pass.
- Unit tests pass without Docker, live VPN credentials, or network access.
- Diff check reports no whitespace errors.

## Manual Dry Validation

Inspect CLI help after implementation:

```bash
python3 chamosel.py --help
python3 chamosel.py verify-leaks --help
```

Expected result:

- `verify-leaks` is listed as a command.
- Help documents `--json`, `--timeout`, and `--target`.
- Help does not print secrets or environment file contents.

## Optional Live Validation

Prerequisites:

- Docker is running.
- `config.yml` points to a working provider configuration.
- Sensitive provider values are supplied through ignored local files such as
  `.env.local`.
- The chamosel stack is running and healthy.

Start or refresh the stack:

```bash
python3 chamosel.py up
python3 chamosel.py status
```

Run human-readable verification:

```bash
python3 chamosel.py verify-leaks
```

Expected result:

- Direct host IP is printed.
- Each backend has one result row.
- Verified count equals total backend count.
- `Leak result: PASS` is printed.
- Exit code is `0`.

Run structured verification:

```bash
python3 chamosel.py verify-leaks --json
```

Expected result:

- Output is a single JSON object.
- `ok` is `true`.
- `instances` contains one object per backend.
- No secrets or environment values appear in the JSON.

## Failure Validation

Use mocked unit tests for deterministic failure cases:

- direct host IP unavailable
- controller unreachable
- backend proxy request failure
- backend proxy IP equals direct host IP
- malformed or non-public IP response

Expected result:

- Workflow reports FAIL.
- Exit code is non-zero.
- Each failure includes an operator-visible reason.
- JSON output keeps the documented shape.

## DNS and Client Boundary Check

After README updates, verify the documentation explains:

- HTTP proxy clients should send hostnames through the proxy path.
- SOCKS clients need remote DNS behavior such as `socks5h://`.
- Browser/WebRTC leak prevention is outside this command's guarantee.
- Traffic bypassing chamosel is outside this command's guarantee.
