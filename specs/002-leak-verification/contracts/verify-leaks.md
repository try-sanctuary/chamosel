# Contract: `verify-leaks`

## Command

```bash
python3 chamosel.py verify-leaks [--json] [--timeout SECONDS] [--target URL]
```

## Defaults

- `--target`: `https://ifconfig.co/json`
- `--timeout`: implementation default must be documented in `--help`
- Human-readable output unless `--json` is supplied

## Required Behavior

1. Determine direct host public IP without using chamosel's proxy pool.
2. Request fresh controller pool state from `/pool?fresh=1`.
3. Consider every configured backend in the fresh pool state.
4. Treat unhealthy backends as verification failures by default.
5. Probe each healthy backend through its own proxy path.
6. Fail if any considered backend proxy IP equals the direct host IP.
7. Fail if any considered backend cannot return a public proxy IP.
8. Return exit code `0` only when the overall result is PASS.
9. Return non-zero for all FAIL results and top-level command errors.
10. Never print secrets or generated environment contents.

## Human Output

Human-readable output MUST include:

```text
Direct host IP: <ip-or-unavailable>

INSTANCE      STATUS      CONTROLLER_IP     PROXY_IP        COUNTRY        ASN        RESULT
surfshark_0   healthy     45.x.x.x          45.x.x.x        United States  AS9009     ok

Verified: <verified>/<total> backends
Leak result: PASS
```

On failure, `Leak result: FAIL` MUST be printed and affected rows MUST include a
specific failure result or reason.

## JSON Output

When `--json` is supplied, stdout MUST contain one JSON object:

```json
{
  "direct_ip": "149.232.250.241",
  "target": "https://ifconfig.co/json",
  "ok": true,
  "verified_count": 1,
  "total_count": 1,
  "error": null,
  "instances": [
    {
      "name": "surfshark_0",
      "controller_status": "healthy",
      "controller_public_ip": "45.134.140.5",
      "proxy_ok": true,
      "proxy_ip": "45.134.140.5",
      "country": "United States",
      "region": "New York",
      "city": "New York",
      "asn": "AS9009",
      "asn_org": "M247 Europe SRL",
      "leak_detected": false,
      "error": null
    }
  ]
}
```

Failure JSON MUST keep the same top-level shape, set `ok` to `false`, and include
top-level or per-instance `error` values.

## Error Cases

| Condition | Result |
|-----------|--------|
| Direct host IP cannot be determined | FAIL, non-zero exit |
| Direct host IP is not public | FAIL, non-zero exit |
| Controller unreachable or unauthorized | FAIL, non-zero exit |
| Pool response malformed | FAIL, non-zero exit |
| Backend unhealthy by controller state | FAIL, non-zero exit |
| Backend proxy target request fails | FAIL, non-zero exit |
| Backend proxy IP missing or not public | FAIL, non-zero exit |
| Backend proxy IP equals direct host IP | FAIL, non-zero exit |

## Secret-Safety Requirements

Output and errors MUST NOT include:

- `.env` or `.env.local` contents
- `GLUETUN_API_KEY`
- WireGuard private keys
- VPN usernames/passwords
- generated compose environment values
- full subprocess commands that embed secrets
