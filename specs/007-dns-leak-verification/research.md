# Research: DNS Leak Verification

## Decision: Use a DNS-leak challenge flow, not a plain DNS lookup

**Rationale**: A plain lookup from the host or controller only proves which resolver that process uses. A DNS leak check needs a challenge service that records resolver IPs for unique generated hostnames, then returns the resolver list for the challenge ID.

**Alternatives considered**:
- Inspect `/etc/resolv.conf`: rejected because it only shows configuration, not the resolver observed by an external service.
- Resolve a fixed hostname through Python: rejected because cached DNS and proxy behavior can hide the resolver path.

## Decision: Default to the bash.ws DNS leak flow

**Rationale**: The bash.ws DNS leak page describes a flow where generated subdomains are resolved and the service reports IPs that sent DNS requests. The linked open-source terminal script uses `https://bash.ws/id`, triggers unique DNS names, and then reads `https://bash.ws/dnsleak/test/<id>?json`.

**Alternatives considered**:
- Browser-only leak pages: rejected because chamosel needs CLI automation and JSON output.
- Hard-coded browser automation: rejected because it adds heavy dependencies and does not fit the current CLI/controller architecture.

## Decision: Probe through each backend HTTP proxy

**Rationale**: chamosel already validates backend egress by executing a Python probe inside the controller container and using `http://<instance>:8888` as the proxy. DNS verification can use the same path so the proxy backend is responsible for resolving the generated hostnames.

**Alternatives considered**:
- Execute tools inside each gluetun container: rejected because the gluetun image may not include Python, curl, ping, or nslookup consistently.
- Run probe on the host: rejected because it would test host DNS, not backend proxy DNS.

## Decision: Treat ASN mismatch as suspicious, not automatic repair

**Rationale**: The open-source DNS leak script README states that matching ASN between DNS and connection is the expected safe case and mismatch may indicate a problem. Some VPN providers may use resolvers with different metadata, so the command should flag suspicion and require operator review rather than rotating automatically.

**Alternatives considered**:
- Always fail on country mismatch: rejected as too noisy for anycast and provider DNS deployments.
- Never fail on mismatch: rejected because operators need a clear signal for possible DNS leaks.
