#!/usr/bin/env python3
"""chamosel - orchestration service for a rotating gluetun VPN exit-IP pool.

Provisions a Docker Compose stack of gluetun VPN instances behind HAProxy,
plus a controller container exposing a REST API, Prometheus metrics and a
dashboard for live status and graceful IP rotation (no container restarts).

Container management modes:
  - compose (default): this CLI renders docker-compose.yml + haproxy.cfg and
    drives `docker compose`. Simple, declarative, what you want on a server.
  - The controller can additionally manage instances at runtime via the
    gluetun control server (rotation) without touching containers at all.

Usage:
    chamosel.py genkey            # print a fresh gluetun control-server API key
    chamosel.py generate          # render compose + haproxy.cfg (+ .env)
    chamosel.py up                # generate + docker compose up -d
    chamosel.py down              # docker compose down
    chamosel.py status            # call controller /pool for live status
    chamosel.py rotate [name|all] # ask the controller to rotate
"""

import argparse
import json
import logging
import os
import secrets
import subprocess
import sys
import urllib.request

import yaml
from jinja2 import Environment, FileSystemLoader

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = "config.yml"
COMPOSE_FILE = "docker-compose.yml"
HAPROXY_FILE = "haproxy.cfg"
ENV_FILE = ".env"

# In-container ports (fixed)
GLUETUN_PROXY_PORT = 8888
GLUETUN_HEALTH_PORT = 9999
GLUETUN_CONTROL_PORT = 8000
CONTROLLER_PORT = 8800

DEFAULTS = {
    "proxy_port": 8888,
    "stats_port": 8404,
    "api_port": 8800,
    "image": "qmcgaw/gluetun:v3",
    "haproxy_image": "haproxy:3.0-alpine",
    "balance": "roundrobin",
    "auto_rotate_seconds": 0,
    "rotate_cooldown": 60,
    "poll_interval": 15,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("chamosel")

jinja = Environment(
    loader=FileSystemLoader(os.path.join(HERE, "templates")),
    trim_blocks=True, lstrip_blocks=True,
)


def gen_api_key() -> str:
    """Base58 key compatible with gluetun's apikey auth (no padding chars)."""
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "".join(secrets.choice(alphabet) for _ in range(22))


def load_config(path: str) -> dict:
    try:
        cfg = yaml.safe_load(open(path)) or {}
    except FileNotFoundError:
        log.error("Config not found: %s (copy config.yml.example)", path)
        sys.exit(1)
    except yaml.YAMLError as e:
        log.error("Invalid YAML: %s", e)
        sys.exit(1)
    if not cfg.get("vpn_providers"):
        log.error("Define at least one provider under 'vpn_providers'")
        sys.exit(1)
    return cfg


def gset(cfg: dict, key: str):
    return cfg.get("global_settings", {}).get(key, DEFAULTS[key])


def iter_instances(cfg: dict):
    for pkey, prov in cfg["vpn_providers"].items():
        for i in range(int(prov.get("num_containers", 1))):
            yield f"{pkey}_{i}", pkey, prov


def env_for(pkey: str, prov: dict) -> list:
    name = prov.get("provider_name", pkey.replace("_", " ").lower())
    out = [f"VPN_SERVICE_PROVIDER={name}"]
    for k, v in (prov.get("env") or {}).items():
        out.append(f"{k}={v}")
    return out


def resolve_api_key(cfg: dict) -> str:
    """Order: env GLUETUN_API_KEY -> .env file -> config -> generate + persist."""
    key = os.environ.get("GLUETUN_API_KEY", "").strip()
    if key:
        return key
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if line.startswith("GLUETUN_API_KEY="):
                return line.split("=", 1)[1].strip()
    key = gset(cfg, "api_key") if cfg.get("global_settings", {}).get("api_key") else ""
    if not key:
        key = gen_api_key()
        with open(ENV_FILE, "a") as fh:
            fh.write(f"GLUETUN_API_KEY={key}\n")
        log.info("Generated API key, saved to %s", ENV_FILE)
    return key


def generate(cfg: dict):
    api_key = resolve_api_key(cfg)
    # gluetun v3.41+ default-role apikey auth via env (no config.toml mount needed)
    auth_role = json.dumps({"auth": "apikey", "apikey": api_key}, separators=(",", ":"))
    instances = list(iter_instances(cfg))
    names = [n for n, _, _ in instances]

    compose = jinja.get_template("docker-compose.yml.j2").render(
        instances=[{"name": n, "env": env_for(pk, pv)} for n, pk, pv in instances],
        names=names,
        image=gset(cfg, "image"),
        haproxy_image=gset(cfg, "haproxy_image"),
        proxy_port=gset(cfg, "proxy_port"),
        stats_port=gset(cfg, "stats_port"),
        api_port=gset(cfg, "api_port"),
        auto_rotate=gset(cfg, "auto_rotate_seconds"),
        rotate_cooldown=gset(cfg, "rotate_cooldown"),
        poll_interval=gset(cfg, "poll_interval"),
        auth_default_role=auth_role,
        gluetun_health_port=GLUETUN_HEALTH_PORT,
        gluetun_control_port=GLUETUN_CONTROL_PORT,
        controller_port=CONTROLLER_PORT,
    )
    open(COMPOSE_FILE, "w").write(compose)

    haproxy = jinja.get_template("haproxy.cfg.j2").render(
        names=names,
        proxy_port=gset(cfg, "proxy_port"),
        stats_port=gset(cfg, "stats_port"),
        balance=gset(cfg, "balance"),
        gluetun_proxy_port=GLUETUN_PROXY_PORT,
        gluetun_health_port=GLUETUN_HEALTH_PORT,
    )
    open(HAPROXY_FILE, "w").write(haproxy)
    log.info("Generated %s (%d instances) and %s", COMPOSE_FILE, len(names), HAPROXY_FILE)


def compose_cmd(args: list, capture=False):
    try:
        r = subprocess.run(["docker", "compose", "-f", COMPOSE_FILE] + args,
                            text=True, capture_output=capture, check=True)
        return r.stdout if capture else ""
    except FileNotFoundError:
        log.error("docker not found"); sys.exit(1)
    except subprocess.CalledProcessError as e:
        log.error("compose %s failed: %s", " ".join(args), e.stderr or e.stdout); sys.exit(1)


def api_call(cfg: dict, method: str, path: str):
    url = f"http://localhost:{gset(cfg, 'api_port')}{path}"
    req = urllib.request.Request(url, method=method)
    try:
        return json.load(urllib.request.urlopen(req, timeout=15))
    except Exception as e:
        log.error("controller call %s %s failed: %s", method, path, e); sys.exit(1)


def cmd_up(cfg):
    generate(cfg)
    compose_cmd(["up", "-d", "--build", "--remove-orphans"])
    log.info("Pool up. Proxy http://localhost:%s | API+dashboard http://localhost:%s | Stats http://localhost:%s/stats",
             gset(cfg, "proxy_port"), gset(cfg, "api_port"), gset(cfg, "stats_port"))


def cmd_status(cfg):
    data = api_call(cfg, "GET", "/pool")
    print(f"{'INSTANCE':<28} {'HEALTHY':<8} {'ROT':<5} PUBLIC IP")
    for it in data.get("instances", []):
        print(f"{it['name']:<28} {str(it['healthy']):<8} {it['rotations']:<5} {it.get('public_ip') or '-'}")
    print(f"\nhealthy {data.get('healthy')}/{data.get('count')}  rotations {data.get('rotations_total')}")


def cmd_rotate(cfg, target):
    path = "/rotate" if not target else ("/rotate/all" if target == "all" else f"/rotate/{target}")
    print(json.dumps(api_call(cfg, "POST", path), indent=2))


def main():
    p = argparse.ArgumentParser(description="chamosel - spin the wheel, change the skin")
    p.add_argument("action", choices=["genkey", "generate", "up", "down", "status", "rotate"])
    p.add_argument("target", nargs="?", help="for rotate: instance name or 'all'")
    p.add_argument("-c", "--config", default=CONFIG_FILE)
    a = p.parse_args()
    if a.action == "genkey":
        print(gen_api_key()); return
    cfg = load_config(a.config)
    if a.action == "generate": generate(cfg)
    elif a.action == "up": cmd_up(cfg)
    elif a.action == "down": compose_cmd(["down"])
    elif a.action == "status": cmd_status(cfg)
    elif a.action == "rotate": cmd_rotate(cfg, a.target)


if __name__ == "__main__":
    main()
