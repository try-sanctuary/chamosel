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
- **Observable** — Prometheus `/metrics`, auto-refreshing dashboard at `/`, per-instance IP history persisted across controller restarts.
- **Cooldown** — prevents hammering the same instance; forced override on `/rotate/<name>` and `/rotate/all`.
- **Mixed providers** — Surfshark, ProtonVPN, Mullvad, etc. in the same pool.

## Quick start

```bash
cp config.yml.example config.yml   # add your VPN credentials
python3 chamosel.py up             # generates key + configs, docker compose up

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
| `chamosel.py up` | Generate, build the controller image, and start the stack |
| `chamosel.py down` | Stop the stack (volumes preserved) |
| `chamosel.py status` | Health + public IP + rotation count per instance |
| `chamosel.py rotate [name\|all]` | Ask the controller to rotate |

## REST API (controller, port 8800)

| Method | Path | Description |
|---|---|---|
| GET | `/` | HTML dashboard (auto-refresh 5s) |
| GET | `/health` | Liveness |
| GET | `/pool` | Per-instance health + public IP (cached snapshot) |
| GET | `/pool?fresh=1` | Force a live refresh first |
| GET | `/metrics` | Prometheus exposition format |
| POST | `/rotate` | Rotate one random eligible instance (respects cooldown) |
| POST | `/rotate/<name>` | Rotate a named instance (forced) |
| POST | `/rotate/all` | Rotate every instance sequentially (forced) |

```bash
curl localhost:8800/pool | jq
curl -X POST localhost:8800/rotate
curl localhost:8800/metrics
```

### Prometheus metrics

```
chamosel_instances_total
chamosel_instances_healthy
chamosel_rotations_total
chamosel_rotation_errors_total
chamosel_rotation_errors_by_outcome_total{outcome="..."}
chamosel_instance_healthy{instance="..."}
chamosel_instance_status{instance="...",status="..."}
chamosel_instance_rotations_total{instance="..."}
chamosel_instance_rotation_errors_by_outcome_total{instance="...",outcome="..."}
```

## Config (`config.yml`)

```yaml
global_settings:
  proxy_port: 8888
  api_bind: 127.0.0.1       # use 0.0.0.0 only behind firewall/auth
  stats_port: 8404
  stats_bind: 127.0.0.1
  api_port: 8800
  image: qmcgaw/gluetun:v3
  balance: roundrobin        # or leastconn
  auto_rotate_seconds: 0     # 0 = off; e.g. 1800 = rotate one every 30 min
  rotate_cooldown: 60        # min seconds between rotations of same instance
  rotation_recovery_timeout: 30
  poll_interval: 15          # background health/IP poll interval
  # api_key: ""              # optional local gluetun control-server key

vpn_providers:
  surfshark:
    num_containers: 4
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
- **After rotation:** the controller waits up to `rotation_recovery_timeout` seconds for a healthy tunnel and changed public IP. If recovery times out, `/rotate` returns `ok: false` with outcome `recovery_timeout`.
- **Control API key:** `api_key` is not a paid gluetun key and not a provider subscription key. It is a local secret shared between gluetun's control server and the chamosel controller. If you set it in `config.yml`, `generate` writes the same value to `.env` so Docker Compose can pass it to the controller. If `.env` and `config.yml` disagree, generation fails instead of creating a split-brain auth setup.
- **Surfshark:** caps simultaneous connections per plan. Size `num_containers` accordingly.
- **API/dashboard exposure:** ports `8800` and `8404` bind to localhost by default. If you set `api_bind` or `stats_bind` to `0.0.0.0`, put them behind firewall/reverse-proxy auth.
- **Docker volumes:** `chamosel.py down` preserves volumes (gluetun servers cache + state). Use `docker compose down -v` to wipe everything.

## Requirements

- Docker + compose plugin
- Python 3.10+ with `pyyaml` and `jinja2` (CLI only; the controller is stdlib-only)
