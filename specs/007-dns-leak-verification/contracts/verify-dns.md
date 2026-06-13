# Contract: `verify-dns`

## CLI

```bash
python3 chamosel.py verify-dns
python3 chamosel.py verify-dns --json
python3 chamosel.py verify-dns --timeout 30
```

## Behavior

1. Fetch current pool state through `/pool?fresh=1` using controller auth headers when configured.
2. For each healthy backend, run the DNS leak challenge through that backend's HTTP proxy.
3. Normalize the returned DNS leak service payload into a stable report.
4. Print a human table by default or JSON with `--json`.
5. Exit non-zero if any backend fails DNS verification, is suspicious, or cannot be checked.

Unhealthy backends are included in the report with a safe error and do not run a DNS challenge.

## JSON Shape

```json
{
  "ok": false,
  "target": "bash.ws",
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

- `0`: every included backend passed DNS verification.
- `1`: one or more backends failed, were suspicious, were unhealthy, or the pool could not be read.
