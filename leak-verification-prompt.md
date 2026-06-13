# Prompt: Implement Leak Verification for chamosel

Implement DNS/IP leak verification and safer runtime checks for chamosel.

## Goal

Add a verification workflow that gives operators confidence that requests made through chamosel do not expose the host/server IP and that each gluetun backend is routing traffic through VPN correctly.

## Required Changes

### 1. Add a New CLI Command

Add:

```bash
python3 chamosel.py verify-leaks
```

Optional flags:

```bash
python3 chamosel.py verify-leaks --json
python3 chamosel.py verify-leaks --timeout 30
python3 chamosel.py verify-leaks --target https://ifconfig.co/json
```

Default target:

```text
https://ifconfig.co/json
```

### 2. Verification Behavior

The command must:

- Fetch direct host IP without proxy.
- Fetch pool state from controller `/pool?fresh=1`.
- For each configured/healthy backend, perform a request through that backend's gluetun HTTP proxy.
- Verify that each backend proxy IP is different from the direct host IP.
- Verify that each backend returns a public IP.
- Verify that controller marks the backend `healthy`.
- Return non-zero exit code if:
  - direct IP cannot be determined
  - controller is unreachable
  - any healthy backend cannot proxy the target
  - any backend proxy IP equals direct host IP
  - any backend has no public IP
  - any backend is unhealthy unless explicitly skipped by a flag

### 3. Backend-Specific Proxy Checks

Because HAProxy hides which backend served a request, verify each backend directly from inside the Docker network.

Use the controller container as the probe runner when available:

```bash
docker compose exec -T controller python - ...
```

Inside the controller container, request:

```text
https://ifconfig.co/json
```

through each proxy:

```text
http://surfshark_0:8888
http://surfshark_1:8888
...
```

Use Python stdlib only inside the probe.

### 4. Output

Human-readable output should show a table:

```text
INSTANCE      STATUS     CONTROLLER_IP     PROXY_IP        COUNTRY        ASN        RESULT
surfshark_0   healthy    45.x.x.x          45.x.x.x        US             AS9009     ok
surfshark_1   healthy    84.x.x.x          84.x.x.x        US             AS60068    ok
```

Also print:

```text
Direct host IP: x.x.x.x
Verified: N/N backends
Leak result: PASS
```

On failure:

```text
Leak result: FAIL
```

and include the reason per backend.

JSON output should include:

```json
{
  "direct_ip": "149.232.250.241",
  "target": "https://ifconfig.co/json",
  "ok": true,
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

### 5. DNS Leak Guidance

The command cannot fully prove DNS behavior for every external client, but it should document and warn:

- HTTP proxy clients should pass hostnames through the proxy.
- SOCKS clients must use `socks5h://`, not `socks5://`.
- Applications must not make direct requests outside the proxy.
- Browser/WebRTC traffic requires separate hardening.

Add README section:

```md
## Leak Verification
```

Include examples:

```bash
python3 chamosel.py verify-leaks
python3 chamosel.py verify-leaks --json
```

Document that the command verifies:

- direct host IP differs from proxy exit IPs
- each backend can reach the target through VPN
- controller/backend health agrees

Document what it does not guarantee:

- browser WebRTC leaks
- clients that resolve DNS locally before using a proxy
- traffic that bypasses chamosel entirely

### 6. Tests

Add unit tests for:

- parsing direct IP response from `ifconfig.co/json`
- leak failure when backend proxy IP equals direct host IP
- success when all backend proxy IPs differ from direct host IP
- JSON output shape
- non-zero exit behavior on controller unreachable
- command construction for Docker exec probe without printing secrets

Tests must not require Docker or live VPN credentials. Mock subprocess/API calls.

### 7. Constraints

- Do not add non-stdlib runtime dependencies.
- Do not print `.env`, `.env.local`, API keys, WireGuard keys, or generated compose secrets.
- Keep generated files ignored.
- Preserve existing commands and behavior.

Run:

```bash
python3 -m py_compile chamosel.py controller/controller.py
python3 -m unittest discover -s tests -v
git diff --check
```
