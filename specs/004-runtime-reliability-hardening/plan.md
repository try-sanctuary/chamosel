# Implementation Plan: Runtime Reliability Hardening

**Branch**: `004-runtime-reliability-hardening`
**Spec**: `specs/004-runtime-reliability-hardening/spec.md`
**Status**: Implemented

## Technical Context

- Python 3.10+ CLI with `pyyaml` and `jinja2`
- Controller remains Python stdlib-only
- Docker Compose remains the runtime/deployment boundary
- Tests use `unittest` and module import isolation

## Constitution Check

- Preserve local-only default API/stat bindings.
- Do not expose secrets in generated diagnostics, tests, logs, or docs.
- Keep changes compatible with current config defaults.
- Prefer operator-visible state over implicit log-only behavior.

## Implementation Scope

1. Add CLI doctor diagnostics.
2. Add controller state freshness and degraded pool summary.
3. Add conservative duplicate public IP repair.
4. Add bounded batch mode for `/rotate/all`.
5. Add metrics/dashboard/status surfacing for aggregate pool state.
6. Render new controller settings from config into compose.
7. Document live usage and add focused unit coverage.

## Project Structure

```text
chamosel.py
controller/controller.py
templates/docker-compose.yml.j2
config.yml.example
README.md
tests/
specs/004-runtime-reliability-hardening/
```

## Verification

- `python3 -m py_compile chamosel.py controller/controller.py`
- `.venv/bin/python -m unittest discover -s tests -v`
