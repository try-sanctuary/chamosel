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
from dataclasses import dataclass
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
    "api_bind": "127.0.0.1",
    "stats_bind": "127.0.0.1",
    "stats_port": 8404,
    "api_port": 8800,
    "image": "qmcgaw/gluetun:v3",
    "haproxy_image": "haproxy:3.0-alpine",
    "balance": "roundrobin",
    "auto_rotate_seconds": 0,
    "rotate_cooldown": 60,
    "rotation_recovery_timeout": 30,
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
        with open(path) as fh:
            cfg = yaml.safe_load(fh) or {}
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


def env_for(pkey: str, prov: dict) -> dict:
    name = prov.get("provider_name", pkey.replace("_", " ").lower())
    out = {"VPN_SERVICE_PROVIDER": str(name)}
    for k, v in (prov.get("env") or {}).items():
        out[str(k)] = "" if v is None else str(v)
    return out


@dataclass(frozen=True)
class ApiKeyResolution:
    key: str
    source: str


def read_env_api_key(path: str = ENV_FILE) -> str:
    try:
        with open(path) as fh:
            for line in fh:
                if line.startswith("GLUETUN_API_KEY="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        return ""
    return ""


def write_env_api_key(key: str, path: str = ENV_FILE):
    lines = []
    found = False
    try:
        with open(path) as fh:
            for line in fh:
                if line.startswith("GLUETUN_API_KEY="):
                    lines.append(f"GLUETUN_API_KEY={key}\n")
                    found = True
                else:
                    lines.append(line)
    except FileNotFoundError:
        pass
    if not found:
        lines.append(f"GLUETUN_API_KEY={key}\n")
    with open(path, "w") as fh:
        fh.writelines(lines)


def resolve_api_key_info(cfg: dict, env_path: str = ENV_FILE) -> ApiKeyResolution:
    """Resolve and persist one control API key shared by gluetun and controller."""
    env_key = os.environ.get("GLUETUN_API_KEY", "").strip()
    file_key = read_env_api_key(env_path)
    cfg_key = cfg.get("global_settings", {}).get("api_key") or ""
    cfg_key = str(cfg_key).strip()

    if file_key and cfg_key and file_key != cfg_key:
        log.error(
            "Conflicting GLUETUN_API_KEY values in %s and global_settings.api_key; "
            "remove one or make them identical.",
            env_path,
        )
        sys.exit(1)
    if env_key:
        return ApiKeyResolution(env_key, "environment")
    if file_key:
        return ApiKeyResolution(file_key, env_path)
    if cfg_key:
        write_env_api_key(cfg_key, env_path)
        return ApiKeyResolution(cfg_key, "config")

    key = gen_api_key()
    write_env_api_key(key, env_path)
    log.info("Generated API key, saved to %s", env_path)
    return ApiKeyResolution(key, "generated")


def resolve_api_key(cfg: dict) -> str:
    """Backward-compatible key-only wrapper for callers."""
    return resolve_api_key_info(cfg).key


def write_text(path: str, content: str):
    with open(path, "w") as fh:
        fh.write(content)


def generate(cfg: dict):
    api_key_info = resolve_api_key_info(cfg)
    api_key = api_key_info.key
    if api_key_info.source == "config":
        log.info("Persisted global_settings.api_key to %s for controller interpolation", ENV_FILE)
    # gluetun v3.41+ default-role apikey auth via env (no config.toml mount needed)
    auth_role = json.dumps({"auth": "apikey", "apikey": api_key}, separators=(",", ":"))
    instances = list(iter_instances(cfg))
    names = [n for n, _, _ in instances]

    compose = jinja.get_template("docker-compose.yml.j2").render(
        instances=[{"name": n, "env": env_for(pk, pv)} for n, pk, pv in instances],
        names=names,
        image=gset(cfg, "image"),
        haproxy_image=gset(cfg, "haproxy_image"),
        api_bind=gset(cfg, "api_bind"),
        stats_bind=gset(cfg, "stats_bind"),
        proxy_port=gset(cfg, "proxy_port"),
        stats_port=gset(cfg, "stats_port"),
        api_port=gset(cfg, "api_port"),
        auto_rotate=gset(cfg, "auto_rotate_seconds"),
        rotate_cooldown=gset(cfg, "rotate_cooldown"),
        rotation_recovery_timeout=gset(cfg, "rotation_recovery_timeout"),
        poll_interval=gset(cfg, "poll_interval"),
        auth_default_role=auth_role,
        gluetun_health_port=GLUETUN_HEALTH_PORT,
        gluetun_control_port=GLUETUN_CONTROL_PORT,
        controller_port=CONTROLLER_PORT,
    )
    write_text(COMPOSE_FILE, compose)

    haproxy = jinja.get_template("haproxy.cfg.j2").render(
        names=names,
        proxy_port=gset(cfg, "proxy_port"),
        stats_port=gset(cfg, "stats_port"),
        balance=gset(cfg, "balance"),
        gluetun_proxy_port=GLUETUN_PROXY_PORT,
        gluetun_health_port=GLUETUN_HEALTH_PORT,
    )
    write_text(HAPROXY_FILE, haproxy)
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
    print(f"{'INSTANCE':<28} {'STATUS':<20} {'HEALTHY':<8} {'ROT':<5} PUBLIC IP")
    for it in data.get("instances", []):
        status = it.get("status") or ("healthy" if it.get("healthy") else "down")
        print(
            f"{it['name']:<28} {status:<20} {str(it['healthy']):<8} "
            f"{it['rotations']:<5} {it.get('public_ip') or '-'}"
        )
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
