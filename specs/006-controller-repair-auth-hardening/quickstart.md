# Quickstart: Controller Repair and Auth Hardening

## Automated validation

```bash
.venv/bin/python -m py_compile chamosel.py controller/controller.py
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

Expected result: syntax checks pass, all tests pass, and whitespace check is clean.

## Local auth validation

1. Configure controller authentication in `config.yml`.
2. Generate the stack:

   ```bash
   .venv/bin/python chamosel.py generate
   ```

3. Confirm generated compose passes auth settings to the controller without printing the secret.
4. Run status/doctor commands and confirm they can authenticate through configured local settings.

## Doctor repair validation

1. Start with a degraded duplicate-IP pool state in tests or a controlled live stack.
2. Run read-only doctor:

   ```bash
   .venv/bin/python chamosel.py doctor --json
   ```

   Expected: `repair_decision` is shown and no repair action is executed.

3. Run repair doctor:

   ```bash
   .venv/bin/python chamosel.py doctor --repair --json
   ```

   Expected: at most one repair action is attempted, and mismatch-only state remains monitor-only.

## Live validation

When Docker and live credentials are available:

```bash
.venv/bin/python chamosel.py up --no-pull
.venv/bin/python chamosel.py doctor --json
.venv/bin/python chamosel.py doctor --repair --json
.venv/bin/python chamosel.py verify-leaks --json
```

Do not commit live secrets or generated reports.
