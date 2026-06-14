# Contract: `verify-dns`

## CLI

```bash
python3 chamosel.py verify-dns
python3 chamosel.py verify-dns --json
python3 chamosel.py verify-dns --timeout 30
python3 chamosel.py verify-dns --strict-dns-asn
```

## Behavior

1. Fetch current pool state through `/pool?fresh=1` using controller auth headers when configured.
2. For each healthy backend, run the DNS leak challenge through that backend's HTTP proxy.
3. Normalize the returned DNS leak service payload into a stable report.
4. Print a human table by default or JSON with `--json`.
5. Exit non-zero if any backend fails DNS verification, has a fail-level DNS risk, or cannot be checked.
6. Treat resolver ASN mismatch as a warning by default. With `--strict-dns-asn`, treat resolver ASN mismatch as a fail-level suspicious result.

Unhealthy backends are included in the report with a safe error and do not run a DNS challenge.

## JSON Shape

```json
{
  "ok": false,
  "target": "bash.ws",
  "policy": "external-ok",
  "verified_count": 1,
  "total_count": 2,
  "error": "one or more backends failed DNS leak verification",
  "instances": [
    {
      "name": "surfshark_0",
      "controller_status": "healthy",
      "healthy": true,
      "connection_ip": "198.51.100.10",
      "connection_asn": "AS12345",
      "dns_servers": [
        {
          "ip": "198.51.100.53",
          "country": "Germany",
          "asn": "AS12345"
        }
      ],
      "resolver_count": 1,
      "asn_match": true,
      "suspected_leak": false,
      "strict_asn": false,
      "warnings": [],
      "resolver_risks": [],
      "dns_ok": true,
      "conclusions": [],
      "error": null
    }
  ]
}
```

## Secret Safety

The report must not include:

- VPN provider credentials
- WireGuard private keys
- `GLUETUN_API_KEY`
- `CONTROLLER_AUTH_TOKEN`
- generated `.env` values

## Exit Codes

- `0`: every included backend passed DNS verification. Default-policy warnings do not fail the command.
- `1`: one or more backends failed, had fail-level DNS risk, were unhealthy, or the pool could not be read.
