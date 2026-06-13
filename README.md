# chamosel

> *Spin the wheel. Change the skin.*

A rotating VPN exit-IP pool orchestrator built for scrapers. Runs N [gluetun](https://github.com/qdm12/gluetun) VPN containers behind a single HAProxy endpoint, plus a **controller** that exposes a REST API, Prometheus metrics and a live dashboard — and performs **graceful IP rotation** without restarting containers.

Point your scraper at one proxy port. Get blocked? `POST /rotate` (or let the PHP client do it automatically) and you're on a fresh exit IP within seconds.

```
scraper ──http_proxy──> HAProxy :8888 ──tcp──> gluetun_0 ── exit IP #1
   │                                     ├────> gluetun_1 ── exit IP #2
   │                                     ├────> gluetun_2 ── exit IP #3
   │                                     └────> gluetun_3 ── exit IP #4
   │                                              ▲ control server :8000 (apikey auth)
   └── POST /rotate · GET /metrics ──> chamosel-ctrl :8800 ─┘
```

## Features

- **Graceful rotation** — stops + starts the VPN inside gluetun, picking a new server without a container restart. The controller counts success only after the tunnel is healthy again with a changed public IP.
- **Authenticated gluetun control** — generates or reuses a local API key, wires it into each gluetun (`apikey` default role) and the controller. Works with gluetun v3.40+.
- **Local control surfaces by default** — controller/dashboard and HAProxy stats bind to `127.0.0.1` on the host unless you explicitly change the bind addresses.
- **API-version aware** — detects `/v1/vpn/status` (v3.41+) vs legacy `/v1/openvpn/status` per instance, cached after first success.
- **Health-aware pool** — HAProxy probes gluetun's health server (`:9999`), not the proxy port. A gluetun with a dead VPN still answers on the proxy port; chamosel evicts it properly.
- **Observable** — Prometheus `/metrics`, auto-refreshing dashboard at `/`, per-instance IP history, latest rotation outcome, and cooldown state persisted across controller restarts.
- **Cooldown** — prevents hammering the same instance after recent rotation or recovery failures; forced override is explicit on `/rotate/<name>`.
- **Mixed providers** — Surfshark, ProtonVPN, Mullvad, etc. in the same pool.

## Quick start

```bash
cp config.yml.example config.yml   # add your VPN credentials
python3 chamosel.py up             # generate configs, pull latest images, compose up

# Proxy:     http://localhost:8888
# Dashboard: http://localhost:8800       # bound to 127.0.0.1 by default
# Metrics:   http://localhost:8800/metrics
# Stats UI:  http://localhost:8404/stats # bound to 127.0.0.1 by default

curl -x http://localhost:8888 https://ipinfo.io/ip
```

## CLI

| Command | Description |
|---|---|
| `chamosel.py genkey` | Print a fresh gluetun control-server API key |
| `chamosel.py generate` | Render `docker-compose.yml` + `haproxy.cfg` (+ `.env`) |
| `chamosel.py up` | Generate, pull latest runtime images, build the controller image, and start the stack |
| `chamosel.py up --no-pull` | Start from local image cache without pulling newer runtime images |
| `chamosel.py down` | Stop the stack (volumes preserved) |
| `chamosel.py status` | Health + public IP + rotation count per instance |
| `chamosel.py rotate [name\|all]` | Ask the controller to rotate |
| `chamosel.py doctor` | Diagnose compose/controller/pool/stats/env/image freshness state |
| `chamosel.py doctor --repair` | Diagnose, then request one safe duplicate-IP repair action |
| `chamosel.py verify-leaks` | Verify backend proxy exit IPs do not expose the host IP |
| `chamosel.py verify-dns` | Verify backend DNS resolvers do not look suspicious |
| `chamosel.py stress` | Repeat leak-only or rotation stress validation |

## Doctor

`doctor` is the fast operator check for the running stack:

```bash
python3 chamosel.py doctor
python3 chamosel.py doctor --json
python3 chamosel.py doctor --repair
```

It checks Docker Compose visibility, controller `/health`, a fresh `/pool?fresh=1`, HAProxy stats port reachability, healthy backend count, image freshness mode, and whether `.env.local` exists. It reports paths and booleans only, not secret values. A fresh pool check also refreshes verified backend proxy exit IPs when their cache is expired. When the pool is degraded, `doctor` reports a `repair_decision`: duplicate verified proxy IPs can trigger controller repair, public-IP mismatch is monitored without rotation, and failed egress verification requires manual inspection.

`doctor` is read-only unless `--repair` is passed. With `--repair`, it diagnoses first and then calls the controller repair endpoint only when the decision is `repair_requested`. That repair is bounded to one non-forced duplicate-IP backend rotation. `public_ip_mismatch` remains monitor-only when verified proxy IPs are unique.

## Leak Verification

Run a local leak check before trusting the pool:

```bash
python3 chamosel.py verify-leaks
python3 chamosel.py verify-leaks --json
```

By default, the command checks `https://ifconfig.co/json`. You can tune the target and request timeout:

```bash
python3 chamosel.py verify-leaks --target https://ifconfig.co/json --timeout 30
```

The check verifies that:

- the direct host IP differs from every checked backend proxy exit IP
- each healthy backend can reach the target through its own VPN proxy path
- controller public IP, controller verified proxy IP, and live proxy verification are reported side by side

The check fails closed when the controller is unreachable, the host IP cannot be determined, a backend is unhealthy, a backend cannot proxy the target, a backend returns no public IP, or a backend returns the same IP as the host.

What it does not guarantee:

- Browser WebRTC leak prevention. Harden browsers separately.
- Clients that resolve DNS locally before using a proxy. HTTP proxy clients should send hostnames through the proxy path.
- SOCKS clients using local DNS. Use remote DNS behavior such as `socks5h://` when a SOCKS client is involved.
- Traffic that bypasses chamosel entirely.

## DNS Leak Verification

Run DNS leak verification after `doctor` and `verify-leaks`, without rotating tunnels:

```bash
python3 chamosel.py doctor
python3 chamosel.py verify-leaks
python3 chamosel.py verify-dns
python3 chamosel.py verify-dns --json
```

`verify-dns` uses the same backend proxy path as `verify-leaks`, but asks a DNS leak challenge service to report which DNS resolvers were observed for each backend. The report shows the backend connection IP, connection ASN, resolver count, resolver ASN values, and a result per backend.

A `suspected` or `resolver ASN differs from connection ASN` result is an investigation signal. It does not automatically rotate or repair anything. Some VPN providers can use DNS infrastructure with different metadata, so compare the result with provider documentation before changing live settings.

## Stress Validation

Leak-only stress repeats leak verification without rotating tunnels:

```bash
python3 chamosel.py stress --iterations 100 --mode leak-only
```

Rotation stress exercises batched `POST /rotate/all` and summarizes partial success, cooldown skips, and per-backend outcomes:

```bash
python3 chamosel.py stress --iterations 10 --mode rotation
```

Use `--out-dir ./stress-results` to write `summary.json`. Rotation stress verifies leaks after each rotation by default; add `--no-verify` when you only want to exercise controller rotation behavior.

Use the three validation commands for different jobs:

- `doctor`: fast local stack diagnostics, no external leak target.
- `verify-leaks`: one end-to-end proxy leak check for each healthy backend.
- `verify-dns`: one DNS resolver leak check for each healthy backend.
- `stress`: repeated validation, optionally with cautious rotation.

For Surfshark-style live testing, start conservatively with `num_containers: 5`, `rotate_cooldown: 60`, and `rotation_recovery_timeout: 60` to `90`. Larger pools can work, but frequent mass rotation may hit provider recovery limits. `rotate/all` skips backends in cooldown, rotates eligible backends in small batches, and continues when one backend times out. Duplicate verified proxy IPs are treated as degraded; after a fresh health check the controller schedules one background repair rotation for a duplicate backend when it is not in cooldown. If repair fails, `duplicate_repair_retry_cooldown` prevents immediate retry loops. If gluetun's control API public IP differs from the verified proxy exit IP, chamosel marks the pool degraded for visibility but does not rotate unless the verified proxy IP is duplicated.

## REST API (controller, port 8800)

| Method | Path | Description |
|---|---|---|
| GET | `/` | HTML dashboard (auto-refresh 5s) |
| GET | `/health` | Liveness |
| GET | `/pool` | Per-instance health, gluetun public IP, verified proxy IP, and pool state (cached snapshot) |
| GET | `/pool?fresh=1` | Force a live refresh first; refreshes verified proxy IPs when their TTL expired |
| GET | `/metrics` | Prometheus exposition format |
| POST | `/rotate` | Rotate one random eligible instance (respects cooldown) |
| POST | `/rotate/<name>` | Rotate a named instance (forced) |
| POST | `/rotate/all` | Rotate every eligible instance in bounded batches and summarize partial results |

```bash
curl localhost:8800/pool | jq
curl -X POST localhost:8800/rotate
curl localhost:8800/metrics
```

### Prometheus metrics

```
chamosel_instances_total
chamosel_instances_healthy
chamosel_pool_status{status="healthy|degraded|down"}
chamosel_pool_degraded_reason{reason="..."}
chamosel_state_fresh
chamosel_rotations_total
chamosel_rotation_errors_total
chamosel_rotation_errors_by_outcome_total{outcome="..."}
chamosel_instance_healthy{instance="..."}
chamosel_instance_status{instance="...",status="..."}
chamosel_instance_rotations_total{instance="..."}
chamosel_instance_rotation_errors_by_outcome_total{instance="...",outcome="..."}
chamosel_instance_rotation_outcome{instance="...",outcome="..."}
chamosel_instance_rotation_cooldown_active{instance="..."}
chamosel_instance_rotation_cooldown_remaining_seconds{instance="..."}
chamosel_instance_egress_state_fresh{instance="..."}
chamosel_instance_public_ip_mismatch{instance="..."}
```

## Config (`config.yml`)

```yaml
global_settings:
  proxy_port: 8888
  api_bind: 127.0.0.1       # use 0.0.0.0 only behind firewall/auth
  stats_port: 8404
  stats_bind: 127.0.0.1
  api_port: 8800
  # env_file: .env.local    # optional provider secrets file for gluetun services
  image: qmcgaw/gluetun:v3
  balance: roundrobin        # or leastconn
  auto_rotate_seconds: 0     # 0 = off; e.g. 1800 = rotate one every 30 min
  rotate_cooldown: 60        # min seconds between rotations of same instance
  rotation_recovery_timeout: 30
  rotate_all_batch_size: 2
  rotate_all_batch_delay_seconds: 2
  pool_degraded_min_healthy: auto
  auto_repair_duplicate_ips: true
  duplicate_repair_retry_cooldown: 300
  egress_verify_target: https://ifconfig.co/json
  egress_verify_timeout: 10
  egress_verify_ttl: 120
  egress_verify_on_fresh: true
  controller_auth_enabled: false
  # controller_auth_token: "" # optional; generated into .env when controller auth is enabled
  poll_interval: 15          # background health/IP poll interval
  # api_key: ""              # optional local gluetun control-server key

vpn_providers:
  surfshark:
    num_containers: 5
    env:
      VPN_TYPE: wireguard
      WIREGUARD_PRIVATE_KEY: "[YOUR_KEY]"
      WIREGUARD_ADDRESSES: "10.14.0.2/16"
      SERVER_COUNTRIES: "Germany,Netherlands,France,Poland"
```

Mix providers freely — each block becomes N gluetun instances in the pool.

## PHP integration

`examples/client.php` — `ChamoselClient` with `fetchWithRetry()` that rotates automatically on HTTP 403/429.

```php
$client = new ChamoselClient();
$res = $client->fetchWithRetry('https://example.com/products');
```

## Notes

- **Per-request IP rotation:** with `mode tcp`, one keep-alive connection pins one exit IP. Set `CURLOPT_FRESH_CONNECT` in PHP (already done in the example) or use `balance leastconn`.
- **After rotation:** the controller waits up to `rotation_recovery_timeout` seconds for a healthy tunnel and changed public IP. If recovery times out, `/rotate` returns `ok: false` with outcome `recovery_timeout` and starts a cooldown for mass/automatic rotation. If the tunnel is healthy but the IP did not change, the outcome is `healthy_ip_unchanged`.
- **Verified egress IP:** `/pool?fresh=1` verifies each healthy backend by requesting `egress_verify_target` through that backend's HTTP proxy and caches the resulting `verified_proxy_ip` for `egress_verify_ttl` seconds. Diversity checks prefer fresh verified proxy IPs over gluetun's `/v1/publicip/ip` value. A `public_ip_mismatch` is visible degraded state, but not an automatic repair trigger by itself.
- **Controller auth:** `controller_auth_enabled: true` protects the dashboard, `/pool`, `/metrics`, `/rotate*`, and `/repair/duplicate-ip` with `X-Chamosel-Auth`. The CLI reads `CONTROLLER_AUTH_TOKEN` from the environment, `.env`, or `global_settings.controller_auth_token` and sends the header automatically. `/health` remains public for liveness checks. If `api_bind` is not loopback, generation fails unless controller auth is enabled.
- **Pool status:** `/pool`, `/metrics`, `status`, and the dashboard expose `pool_status` as `healthy`, `degraded`, or `down`. The pool is degraded when state is stale after controller restart, too few backends are healthy, duplicate verified proxy IPs or fallback public IPs are detected, egress verification fails, public IP differs from verified proxy IP, or recent rotation recovery/proxy checks failed. With `auto_repair_duplicate_ips: true`, duplicate-IP detection after polling or `/pool?fresh=1` schedules one non-forced background rotation for a duplicate backend, respecting cooldown and `duplicate_repair_retry_cooldown`.
- **Mass rotation:** `/rotate/all` rotates eligible backends in batches. The defaults are `rotate_all_batch_size: 2` and `rotate_all_batch_delay_seconds: 2`; keep `rotate_cooldown > 0` for live providers so repeated recovery failures back off instead of hammering the same account.
- **Control API key:** `api_key` is not a paid gluetun key and not a provider subscription key. It is a local secret shared between gluetun's control server and the chamosel controller. If you set it in `config.yml`, `generate` writes the same value to `.env` so Docker Compose can pass it to the controller. If `.env` and `config.yml` disagree, generation fails instead of creating a split-brain auth setup.
- **Controller auth token:** `controller_auth_token` is separate from `api_key`. It is the operator-facing chamosel controller token, not a gluetun/provider key. When auth is enabled and no token is configured, `generate` creates one in `.env`.
- **Provider secrets:** keep VPN credentials out of `config.yml` when possible. Copy `.env.example` to `.env.local`, set `global_settings.env_file: .env.local`, and put values such as `WIREGUARD_PRIVATE_KEY` there. `.env.local` is ignored by Git.
- **Image freshness:** `chamosel.py up` runs `docker compose pull --ignore-buildable` before starting the stack so runtime images such as gluetun do not silently stay stale. Use `chamosel.py up --no-pull` when you intentionally want to use only local cached images.
- **Surfshark:** start live validation around `num_containers: 5` and increase carefully. Frequent `rotate/all` can run into provider recovery delays even when leak-only verification is stable.
- **API/dashboard exposure:** ports `8800` and `8404` bind to localhost by default. If you set `api_bind` to `0.0.0.0`, enable `controller_auth_enabled: true`; keep firewall/reverse-proxy controls in front of any public host bind. HAProxy stats still needs network-level protection if `stats_bind` is public.
- **Docker volumes:** `chamosel.py down` preserves volumes (gluetun servers cache + state). Use `docker compose down -v` to wipe everything.

## Requirements

- Docker + compose plugin
- Python 3.10+ with `pyyaml` and `jinja2` (CLI only; the controller is stdlib-only)
