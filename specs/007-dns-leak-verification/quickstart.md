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
python3 chamosel.py verify-dns --strict-dns-asn
```

Expected outcome:

- `doctor` reports a reachable, fresh pool.
- `verify-leaks` confirms backend proxy exit IPs do not equal the direct host IP.
- `verify-dns` lists DNS resolvers observed for each healthy backend. Resolver ASN mismatch is a warning by default.
- `verify-dns --strict-dns-asn` fails if resolver ASN differs from the backend connection ASN.
- No command prints provider credentials, WireGuard keys, gluetun API keys, or controller auth tokens.

## Interpreting Suspicious DNS Results

If `verify-dns` reports `suspected_leak: true`, treat it as an investigation signal. It does not rotate tunnels automatically. If the only signal is resolver ASN mismatch, remember that gluetun defaults to Cloudflare DNS-over-TLS; use strict ASN mode only when that is your desired policy.

## Optional DNS Upstream Overrides

Leave DNS upstream settings empty to keep gluetun defaults. To use named encrypted upstreams supported by gluetun, set `dns_upstream_resolver_type` and `dns_upstream_resolvers`. To use Surfshark/provider DNS addresses, set `dns_upstream_plain_addresses` to provider-supplied `ip:port` values; generated gluetun services will receive `DNS_UPSTREAM_RESOLVER_TYPE=plain` and `DNS_UPSTREAM_PLAIN_ADDRESSES`.
