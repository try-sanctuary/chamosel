# Data Model: DNS Leak Verification

## DNSVerificationReport

- `ok`: whether all healthy backends were DNS-verified without suspicious resolver metadata
- `target`: DNS leak service identifier or URL family used for the run
- `verified_count`: number of backends with passing DNS verification
- `total_count`: number of backends included in the report
- `error`: top-level safe error when the report cannot be produced
- `instances`: list of `BackendDNSResult`

Validation:
- `ok` is true only when `total_count > 0` and every backend result is `dns_ok`.
- Top-level errors must not include provider credentials or auth tokens.

## BackendDNSResult

- `name`: backend instance name
- `controller_status`: status from controller pool state
- `healthy`: whether the controller considers the backend healthy
- `connection_ip`: public IP reported by the DNS leak service for the backend probe
- `connection_asn`: ASN metadata for the backend connection IP, when available
- `dns_servers`: list of observed `DNSServer`
- `resolver_count`: number of observed DNS resolver entries
- `asn_match`: true when all resolver ASN values match the connection ASN, false when any differ, null when insufficient metadata exists
- `suspected_leak`: true when the result should fail operator validation
- `dns_ok`: true when the backend was healthy, resolver data was present, and no suspicion/error was found
- `conclusions`: text conclusions returned by the DNS leak service
- `error`: safe per-backend error string

Validation:
- Unhealthy backends include `dns_ok: false` and an explicit `error`.
- `suspected_leak` is true when `asn_match` is false.
- Missing ASN metadata alone does not mark a backend suspicious, but it prevents claiming ASN match.

## DNSServer

- `ip`: resolver IP
- `country`: resolver country name, when available
- `asn`: resolver ASN, when available

Validation:
- Entries without an IP are ignored.
- Metadata is optional because external DNS leak services may omit it.
