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
    chamosel.py up                # generate + pull images + docker compose up -d
    chamosel.py up --no-pull      # generate + docker compose up -d using local images
    chamosel.py down              # docker compose down
    chamosel.py status            # call controller /pool for live status
    chamosel.py rotate [name|all] # ask the controller to rotate
    chamosel.py verify-dns        # check backend DNS resolver leak signals
"""

import argparse
from dataclasses import dataclass
import ipaddress
import json
import logging
import os
import socket
import secrets
import subprocess
import sys
import time
import urllib.request

import yaml
from jinja2 import Environment, FileSystemLoader

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = "config.yml"
COMPOSE_FILE = "docker-compose.yml"
HAPROXY_FILE = "haproxy.cfg"
ENV_FILE = ".env"
DEFAULT_LEAK_TARGET = "https://ifconfig.co/json"
DEFAULT_DNS_LEAK_SERVICE = "bash.ws"
DEFAULT_DNS_LEAK_QUERIES = 10
DEFAULT_DNS_VERIFICATION_POLICY = "external-ok"
DEFAULT_LEAK_TIMEOUT = 30
DEFAULT_STRESS_ITERATIONS = 100

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
    "env_file": "",
    "image": "qmcgaw/gluetun:v3",
    "haproxy_image": "haproxy:3.0-alpine",
    "balance": "roundrobin",
    "auto_rotate_seconds": 0,
    "rotate_cooldown": 60,
    "rotation_recovery_timeout": 30,
    "rotate_all_batch_size": 2,
    "rotate_all_batch_delay_seconds": 2,
    "pool_degraded_min_healthy": "auto",
    "auto_repair_duplicate_ips": True,
    "duplicate_repair_retry_cooldown": 300,
    "egress_verify_target": DEFAULT_LEAK_TARGET,
    "egress_verify_timeout": 10,
    "egress_verify_ttl": 120,
    "egress_verify_on_fresh": True,
    "dashboard_refresh_seconds": 5,
    "dns_upstream_resolver_type": "",
    "dns_upstream_resolvers": "",
    "dns_upstream_plain_addresses": "",
    "controller_auth_enabled": False,
    "controller_auth_token": "",
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


def truthy(value) -> bool:
    return str(value).strip().lower() not in ("", "0", "false", "no", "off", "none")


def is_loopback_bind(value: str) -> bool:
    value = str(value or "").strip().lower()
    return value in ("127.0.0.1", "localhost", "::1")


def iter_instances(cfg: dict):
    for pkey, prov in cfg["vpn_providers"].items():
        for i in range(int(prov.get("num_containers", 1))):
            yield f"{pkey}_{i}", pkey, prov


def gluetun_dns_env_overrides(cfg: dict) -> dict:
    """Optional gluetun DNS upstream overrides; empty values keep gluetun defaults."""
    resolver_type = str(gset(cfg, "dns_upstream_resolver_type") or "").strip()
    resolvers = str(gset(cfg, "dns_upstream_resolvers") or "").strip()
    plain_addresses = str(gset(cfg, "dns_upstream_plain_addresses") or "").strip()

    out = {}
    if plain_addresses and not resolver_type:
        resolver_type = "plain"
    if resolver_type:
        out["DNS_UPSTREAM_RESOLVER_TYPE"] = resolver_type
    if resolvers:
        out["DNS_UPSTREAM_RESOLVERS"] = resolvers
    if plain_addresses:
        out["DNS_UPSTREAM_PLAIN_ADDRESSES"] = plain_addresses
    return out


def env_for(pkey: str, prov: dict, global_env: dict | None = None) -> dict:
    name = prov.get("provider_name", pkey.replace("_", " ").lower())
    out = {"VPN_SERVICE_PROVIDER": str(name)}
    for k, v in (prov.get("env") or {}).items():
        out[str(k)] = "" if v is None else str(v)
    for k, v in (global_env or {}).items():
        out.setdefault(k, "" if v is None else str(v))
    return out


@dataclass(frozen=True)
class ApiKeyResolution:
    key: str
    source: str


def read_env_value(name: str, path: str = ENV_FILE) -> str:
    prefix = f"{name}="
    try:
        with open(path) as fh:
            for line in fh:
                if line.startswith(prefix):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        return ""
    return ""


def write_env_value(name: str, value: str, path: str = ENV_FILE):
    prefix = f"{name}="
    lines = []
    found = False
    try:
        with open(path) as fh:
            for line in fh:
                if line.startswith(prefix):
                    lines.append(f"{name}={value}\n")
                    found = True
                else:
                    lines.append(line)
    except FileNotFoundError:
        pass
    if not found:
        lines.append(f"{name}={value}\n")
    with open(path, "w") as fh:
        fh.writelines(lines)


def read_env_api_key(path: str = ENV_FILE) -> str:
    return read_env_value("GLUETUN_API_KEY", path)


def write_env_api_key(key: str, path: str = ENV_FILE):
    write_env_value("GLUETUN_API_KEY", key, path)


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


def controller_auth_enabled(cfg: dict) -> bool:
    return truthy(gset(cfg, "controller_auth_enabled"))


def controller_auth_secret_file_paths(cfg: dict, env_path: str = ENV_FILE) -> list[str]:
    configured_env_file = str(gset(cfg, "env_file") or "").strip()
    paths: list[str] = []
    for path in (configured_env_file, ".env.local", env_path):
        if path and path not in paths:
            paths.append(path)
    return paths


def read_controller_auth_token(cfg: dict, env_path: str = ENV_FILE) -> str:
    env_token = os.environ.get("CONTROLLER_AUTH_TOKEN", "").strip()
    if env_token:
        return env_token
    for path in controller_auth_secret_file_paths(cfg, env_path):
        file_token = read_env_value("CONTROLLER_AUTH_TOKEN", path)
        if file_token:
            return file_token
    return str(cfg.get("global_settings", {}).get("controller_auth_token") or "").strip()


def resolve_controller_auth_info(cfg: dict, env_path: str = ENV_FILE) -> ApiKeyResolution:
    """Resolve and persist the controller API token when controller auth is enabled."""
    if not controller_auth_enabled(cfg):
        return ApiKeyResolution("", "disabled")

    env_token = os.environ.get("CONTROLLER_AUTH_TOKEN", "").strip()
    cfg_token = str(cfg.get("global_settings", {}).get("controller_auth_token") or "").strip()
    secret_file_tokens = []
    for path in controller_auth_secret_file_paths(cfg, env_path):
        token = read_env_value("CONTROLLER_AUTH_TOKEN", path)
        if token:
            secret_file_tokens.append((path, token))

    user_secret_tokens = [(path, token) for path, token in secret_file_tokens if path != env_path]
    distinct_user_secret_tokens = {token for _, token in user_secret_tokens}
    generated_file_token = read_env_value("CONTROLLER_AUTH_TOKEN", env_path)

    if len(distinct_user_secret_tokens) > 1:
        log.error(
            "Conflicting CONTROLLER_AUTH_TOKEN values in controller auth secret files; "
            "remove duplicates or make them identical."
        )
        sys.exit(1)
    if distinct_user_secret_tokens and cfg_token and next(iter(distinct_user_secret_tokens)) != cfg_token:
        log.error(
            "Conflicting CONTROLLER_AUTH_TOKEN values in controller auth secret file and "
            "global_settings.controller_auth_token; remove one or make them identical."
        )
        sys.exit(1)
    if generated_file_token and cfg_token and generated_file_token != cfg_token and not distinct_user_secret_tokens:
        log.error(
            "Conflicting CONTROLLER_AUTH_TOKEN values in %s and global_settings.controller_auth_token; "
            "remove one or make them identical.",
            env_path,
        )
        sys.exit(1)
    if env_token:
        return ApiKeyResolution(env_token, "environment")
    if distinct_user_secret_tokens:
        token = next(iter(distinct_user_secret_tokens))
        write_env_value("CONTROLLER_AUTH_TOKEN", token, env_path)
        source = next(path for path, value in user_secret_tokens if value == token)
        return ApiKeyResolution(token, source)
    if generated_file_token:
        return ApiKeyResolution(generated_file_token, env_path)
    if cfg_token:
        write_env_value("CONTROLLER_AUTH_TOKEN", cfg_token, env_path)
        return ApiKeyResolution(cfg_token, "config")

    token = gen_api_key()
    write_env_value("CONTROLLER_AUTH_TOKEN", token, env_path)
    log.info("Generated controller auth token, saved to %s", env_path)
    return ApiKeyResolution(token, "generated")


def controller_auth_headers(cfg: dict) -> dict:
    if not controller_auth_enabled(cfg):
        return {}
    token = read_controller_auth_token(cfg)
    return {"X-Chamosel-Auth": token} if token else {}


def validate_controller_exposure(cfg: dict):
    if is_loopback_bind(gset(cfg, "api_bind")) or controller_auth_enabled(cfg):
        return
    log.error(
        "Refusing to publish the controller API on %s without controller_auth_enabled=true. "
        "Use api_bind: 127.0.0.1 for local-only access or enable controller auth.",
        gset(cfg, "api_bind"),
    )
    sys.exit(1)


def write_text(path: str, content: str):
    with open(path, "w") as fh:
        fh.write(content)


def display_host(value: str, fallback: str = "localhost") -> str:
    value = str(value or "").strip()
    if value in ("", "0.0.0.0", "::"):
        return fallback
    if ":" in value and not value.startswith("["):
        return f"[{value}]"
    return value


def generate(cfg: dict):
    validate_controller_exposure(cfg)
    api_key_info = resolve_api_key_info(cfg)
    controller_auth_info = resolve_controller_auth_info(cfg)
    api_key = api_key_info.key
    if api_key_info.source == "config":
        log.info("Persisted global_settings.api_key to %s for controller interpolation", ENV_FILE)
    if controller_auth_info.source == "config":
        log.info("Persisted global_settings.controller_auth_token to %s for controller interpolation", ENV_FILE)
    # gluetun v3.41+ default-role apikey auth via env (no config.toml mount needed)
    auth_role = json.dumps({"auth": "apikey", "apikey": api_key}, separators=(",", ":"))
    instances = list(iter_instances(cfg))
    names = [n for n, _, _ in instances]

    gluetun_global_env = gluetun_dns_env_overrides(cfg)
    stats_url = f"http://{display_host(gset(cfg, 'stats_bind'))}:{gset(cfg, 'stats_port')}/stats"
    compose = jinja.get_template("docker-compose.yml.j2").render(
        instances=[{"name": n, "env": env_for(pk, pv, gluetun_global_env)} for n, pk, pv in instances],
        names=names,
        image=gset(cfg, "image"),
        haproxy_image=gset(cfg, "haproxy_image"),
        env_file=gset(cfg, "env_file"),
        api_bind=gset(cfg, "api_bind"),
        stats_bind=gset(cfg, "stats_bind"),
        proxy_port=gset(cfg, "proxy_port"),
        stats_port=gset(cfg, "stats_port"),
        api_port=gset(cfg, "api_port"),
        auto_rotate=gset(cfg, "auto_rotate_seconds"),
        rotate_cooldown=gset(cfg, "rotate_cooldown"),
        rotation_recovery_timeout=gset(cfg, "rotation_recovery_timeout"),
        rotate_all_batch_size=gset(cfg, "rotate_all_batch_size"),
        rotate_all_batch_delay_seconds=gset(cfg, "rotate_all_batch_delay_seconds"),
        pool_degraded_min_healthy=gset(cfg, "pool_degraded_min_healthy"),
        auto_repair_duplicate_ips=str(gset(cfg, "auto_repair_duplicate_ips")).lower(),
        duplicate_repair_retry_cooldown=gset(cfg, "duplicate_repair_retry_cooldown"),
        egress_verify_target=gset(cfg, "egress_verify_target"),
        egress_verify_timeout=gset(cfg, "egress_verify_timeout"),
        egress_verify_ttl=gset(cfg, "egress_verify_ttl"),
        egress_verify_on_fresh=str(gset(cfg, "egress_verify_on_fresh")).lower(),
        dashboard_refresh_seconds=gset(cfg, "dashboard_refresh_seconds"),
        dashboard_stats_url=stats_url,
        controller_auth_enabled=str(controller_auth_enabled(cfg)).lower(),
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


def sanitize_tool_output(text: str) -> str:
    lines = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "Location of client config files" in line:
            line = "Location of client config files (default /home/example/.docker)"
        lines.append(line)
    return "\n".join(lines)


_COMPOSE_AVAILABLE = None


def ensure_compose_available():
    global _COMPOSE_AVAILABLE
    if _COMPOSE_AVAILABLE:
        return
    try:
        r = subprocess.run(
            ["docker", "compose", "version"],
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        log.error("docker not found")
        sys.exit(1)
    if r.returncode != 0:
        rendered = sanitize_tool_output(r.stderr or r.stdout)
        if "unknown shorthand flag" in rendered or "is not a docker command" in rendered:
            rendered = (
                "Docker Compose v2 plugin is not available or not recognized. "
                "Install docker-compose-plugin, then verify with `docker compose version`."
            )
        log.error("docker compose unavailable: %s", rendered or "no output")
        sys.exit(1)
    _COMPOSE_AVAILABLE = True


def compose_cmd(args: list, capture=False):
    ensure_compose_available()
    try:
        capture_output = bool(capture)
        r = subprocess.run(["docker", "compose", "-f", COMPOSE_FILE] + args,
                            text=True, capture_output=capture_output, check=True)
        return r.stdout if capture else ""
    except FileNotFoundError:
        log.error("docker not found"); sys.exit(1)
    except subprocess.CalledProcessError as e:
        rendered = sanitize_tool_output(e.stderr or e.stdout)
        log.error("compose %s failed: %s", " ".join(args), rendered or "no output")
        sys.exit(1)


def compose_check(args: list, timeout: int = 15) -> dict:
    try:
        r = subprocess.run(
            ["docker", "compose", "-f", COMPOSE_FILE] + args,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        return {
            "ok": r.returncode == 0,
            "returncode": r.returncode,
            "stdout": (r.stdout or "").strip(),
            "stderr": (r.stderr or "").strip(),
        }
    except FileNotFoundError:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": "docker not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": "docker compose timed out"}


class LeakVerificationError(Exception):
    """Operator-safe verification failure."""


def api_timeout_for_rotation(cfg: dict) -> int:
    count = max(1, sum(1 for _ in iter_instances(cfg)))
    return max(15, int(gset(cfg, "rotation_recovery_timeout")) * count + 15)


def api_call(cfg: dict, method: str, path: str, timeout: int = 15):
    url = f"http://localhost:{gset(cfg, 'api_port')}{path}"
    req = urllib.request.Request(url, method=method, headers=controller_auth_headers(cfg))
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except Exception as e:
        log.error("controller call %s %s failed: %s", method, path, e); sys.exit(1)


def api_call_result(cfg: dict, method: str, path: str, timeout: int = 15) -> dict:
    url = f"http://localhost:{gset(cfg, 'api_port')}{path}"
    req = urllib.request.Request(url, method=method, headers=controller_auth_headers(cfg))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"ok": True, "status": resp.status, "payload": json.load(resp), "error": None}
    except Exception as e:
        return {"ok": False, "status": None, "payload": None, "error": str(e)}


def tcp_check(host: str, port: int, timeout: int = 2) -> dict:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return {"ok": True, "error": None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return False
    return ip.is_global


def extract_public_ip(payload: dict) -> str:
    if not isinstance(payload, dict):
        raise LeakVerificationError("response is not a JSON object")
    for key in ("ip", "query", "public_ip"):
        value = payload.get(key)
        if value and is_public_ip(str(value)):
            return str(value).strip()
    raise LeakVerificationError("response does not contain a public IP")


def validate_timeout(timeout) -> int:
    try:
        value = int(timeout)
    except (TypeError, ValueError):
        raise LeakVerificationError("timeout must be a positive integer")
    if value <= 0:
        raise LeakVerificationError("timeout must be a positive integer")
    return value


def validate_target(target: str) -> str:
    target = (target or "").strip()
    if not target.startswith(("http://", "https://")):
        raise LeakVerificationError("target must start with http:// or https://")
    return target


def fetch_json_url(url: str, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "accept": "application/json",
            "user-agent": "chamosel leak verifier",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def fetch_direct_ip(target: str, timeout: int) -> tuple[str, dict]:
    payload = fetch_json_url(target, timeout)
    return extract_public_ip(payload), payload


def fetch_pool_state(cfg: dict) -> dict:
    url = f"http://localhost:{gset(cfg, 'api_port')}/pool?fresh=1"
    req = urllib.request.Request(url, method="GET", headers=controller_auth_headers(cfg))
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except Exception as e:
        raise LeakVerificationError(f"controller unreachable or returned invalid pool state: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("instances"), list):
        raise LeakVerificationError("controller returned malformed pool state")
    return data


PROBE_SCRIPT = r"""
import json
import sys
import urllib.request

target, proxy, timeout = sys.argv[1], sys.argv[2], int(sys.argv[3])
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": proxy, "https": proxy})
)
req = urllib.request.Request(
    target,
    headers={"accept": "application/json", "user-agent": "chamosel leak verifier"},
)
try:
    with opener.open(req, timeout=timeout) as resp:
        payload = json.load(resp)
    print(json.dumps({"ok": True, "payload": payload}, separators=(",", ":")))
except Exception as exc:
    print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
    sys.exit(1)
""".strip()


DNS_PROBE_SCRIPT = r"""
import json
import sys
import urllib.request

service, proxy, timeout, query_count = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": proxy, "https": proxy})
)
headers = {"user-agent": "chamosel dns leak verifier"}

def read_text(url, request_timeout=timeout):
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=request_timeout) as resp:
        return resp.read().decode("utf-8").strip()

try:
    leak_id = read_text(f"https://{service}/id")
    trigger_timeout = max(1, min(3, timeout))
    for idx in range(query_count):
        try:
            read_text(f"http://{idx}.{leak_id}.{service}/chamosel-dns-leak-test.png", trigger_timeout)
        except Exception:
            pass
    raw = read_text(f"https://{service}/dnsleak/test/{leak_id}?json")
    payload = json.loads(raw)
    print(json.dumps({"ok": True, "payload": payload}, separators=(",", ":")))
except Exception as exc:
    print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
    sys.exit(1)
""".strip()


def build_backend_probe_cmd(instance: str, target: str, timeout: int) -> list[str]:
    proxy = f"http://{instance}:{GLUETUN_PROXY_PORT}"
    return [
        "docker",
        "compose",
        "-f",
        COMPOSE_FILE,
        "exec",
        "-T",
        "controller",
        "python",
        "-c",
        PROBE_SCRIPT,
        target,
        proxy,
        str(timeout),
    ]


def build_backend_dns_probe_cmd(
    instance: str,
    timeout: int,
    service: str = DEFAULT_DNS_LEAK_SERVICE,
    query_count: int = DEFAULT_DNS_LEAK_QUERIES,
) -> list[str]:
    proxy = f"http://{instance}:{GLUETUN_PROXY_PORT}"
    return [
        "docker",
        "compose",
        "-f",
        COMPOSE_FILE,
        "exec",
        "-T",
        "controller",
        "python",
        "-c",
        DNS_PROBE_SCRIPT,
        service,
        proxy,
        str(timeout),
        str(query_count),
    ]


def run_backend_probe(instance: str, target: str, timeout: int) -> dict:
    cmd = build_backend_probe_cmd(instance, target, timeout)
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout + 5)
    except FileNotFoundError:
        raise LeakVerificationError("docker not found")
    except subprocess.TimeoutExpired:
        raise LeakVerificationError("backend probe timed out")

    stdout = (result.stdout or "").strip()
    if not stdout:
        raise LeakVerificationError("backend probe returned no output")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        raise LeakVerificationError("backend probe returned malformed JSON")
    if result.returncode != 0 or not data.get("ok"):
        raise LeakVerificationError(data.get("error") or "backend probe failed")
    return data.get("payload") or {}


def run_backend_dns_probe(instance: str, timeout: int) -> list[dict]:
    cmd = build_backend_dns_probe_cmd(instance, timeout)
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout + 10)
    except FileNotFoundError:
        raise LeakVerificationError("docker not found")
    except subprocess.TimeoutExpired:
        raise LeakVerificationError("dns probe timed out")

    stdout = (result.stdout or "").strip()
    if not stdout:
        raise LeakVerificationError("dns probe returned no output")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        raise LeakVerificationError("dns probe returned malformed JSON")
    if result.returncode != 0 or not data.get("ok"):
        raise LeakVerificationError(data.get("error") or "dns probe failed")
    payload = data.get("payload")
    if not isinstance(payload, list):
        raise LeakVerificationError("dns probe returned malformed payload")
    return payload


def normalize_probe_result(instance: dict, direct_ip: str, payload: dict, error: str | None = None) -> dict:
    proxy_ip = None
    proxy_ok = False
    leak_detected = False
    result_error = error

    if error is None:
        try:
            proxy_ip = extract_public_ip(payload)
            proxy_ok = True
            leak_detected = proxy_ip == direct_ip
            if leak_detected:
                result_error = "proxy IP equals direct host IP"
        except LeakVerificationError as e:
            result_error = str(e)

    metadata = payload if isinstance(payload, dict) else {}
    controller_verified_proxy_ip = instance.get("verified_proxy_ip")
    controller_public_ip = instance.get("public_ip")
    controller_proxy_ip_mismatch = bool(
        controller_verified_proxy_ip
        and proxy_ip
        and controller_verified_proxy_ip != proxy_ip
    )
    return {
        "name": instance.get("name") or "",
        "controller_status": instance.get("status") or ("healthy" if instance.get("healthy") else "down"),
        "controller_public_ip": controller_public_ip,
        "controller_verified_proxy_ip": controller_verified_proxy_ip,
        "controller_public_ip_mismatch": bool(instance.get("public_ip_mismatch")),
        "controller_proxy_ip_mismatch": controller_proxy_ip_mismatch,
        "controller_egress_state_fresh": bool(instance.get("egress_state_fresh")),
        "proxy_ok": proxy_ok and not leak_detected and result_error is None,
        "proxy_ip": proxy_ip,
        "country": metadata.get("country"),
        "region": metadata.get("region"),
        "city": metadata.get("city"),
        "asn": metadata.get("asn"),
        "asn_org": metadata.get("asn_org") or metadata.get("asn_org_name"),
        "leak_detected": leak_detected,
        "error": result_error,
    }


def normalize_dns_server(entry: dict) -> dict | None:
    ip = str(entry.get("ip") or "").strip()
    if not ip:
        return None
    return {
        "ip": ip,
        "country": entry.get("country_name") or entry.get("country"),
        "asn": entry.get("asn"),
    }


def dns_resolver_risk(ip: str) -> str | None:
    try:
        parsed = ipaddress.ip_address(str(ip))
    except ValueError:
        return "resolver IP is malformed"
    if not parsed.is_global:
        return "resolver IP is not globally routable"
    return None


def normalize_dns_probe_result(
    instance: dict,
    payload: list[dict],
    error: str | None = None,
    strict_asn: bool = False,
) -> dict:
    controller_status = instance.get("status") or ("healthy" if instance.get("healthy") else "down")
    connection = {}
    dns_servers = []
    conclusions = []
    warnings = []
    resolver_risks = []
    result_error = error

    if error is None:
        if not isinstance(payload, list):
            result_error = "dns probe returned malformed payload"
        else:
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                kind = entry.get("type")
                if kind == "ip" and not connection:
                    connection = entry
                elif kind == "dns":
                    server = normalize_dns_server(entry)
                    if server:
                        dns_servers.append(server)
                elif kind == "conclusion" and entry.get("ip"):
                    conclusions.append(str(entry["ip"]))
            if not dns_servers:
                result_error = "no DNS resolvers found"

    for server in dns_servers:
        risk = dns_resolver_risk(server.get("ip") or "")
        if risk:
            resolver_risks.append({"ip": server.get("ip"), "reason": risk})

    connection_asn = connection.get("asn")
    dns_asns = [s.get("asn") for s in dns_servers if s.get("asn")]
    asn_match = None
    if connection_asn and dns_asns:
        asn_match = all(asn == connection_asn for asn in dns_asns)

    if asn_match is False:
        warnings.append("resolver ASN differs from connection ASN")

    if resolver_risks and result_error is None:
        result_error = resolver_risks[0]["reason"]
    if strict_asn and asn_match is False and result_error is None:
        result_error = "resolver ASN differs from connection ASN"

    suspected_leak = result_error is not None and bool(dns_servers)
    dns_ok = result_error is None and bool(dns_servers)
    return {
        "name": instance.get("name") or "",
        "controller_status": controller_status,
        "healthy": bool(instance.get("healthy")),
        "connection_ip": connection.get("ip"),
        "connection_asn": connection_asn,
        "dns_servers": dns_servers,
        "resolver_count": len(dns_servers),
        "asn_match": asn_match,
        "suspected_leak": suspected_leak,
        "strict_asn": strict_asn,
        "warnings": warnings,
        "resolver_risks": resolver_risks,
        "dns_ok": dns_ok,
        "conclusions": conclusions,
        "error": result_error,
    }


def verify_leaks(cfg: dict, target: str = DEFAULT_LEAK_TARGET, timeout: int = DEFAULT_LEAK_TIMEOUT) -> dict:
    try:
        target = validate_target(target)
        timeout = validate_timeout(timeout)
        direct_ip, _ = fetch_direct_ip(target, timeout)
        pool = fetch_pool_state(cfg)
    except LeakVerificationError as e:
        return {
            "direct_ip": None,
            "target": target,
            "ok": False,
            "verified_count": 0,
            "total_count": 0,
            "error": str(e),
            "instances": [],
        }
    except Exception as e:
        return {
            "direct_ip": None,
            "target": target,
            "ok": False,
            "verified_count": 0,
            "total_count": 0,
            "error": f"verification failed: {e}",
            "instances": [],
        }

    results = []
    for instance in pool.get("instances", []):
        healthy = bool(instance.get("healthy"))
        status = instance.get("status") or ("healthy" if healthy else "down")
        if not healthy:
            results.append(normalize_probe_result(instance, direct_ip, {}, f"controller status is {status}"))
            continue
        try:
            payload = run_backend_probe(instance.get("name") or "", target, timeout)
            results.append(normalize_probe_result(instance, direct_ip, payload))
        except LeakVerificationError as e:
            results.append(normalize_probe_result(instance, direct_ip, {}, str(e)))

    verified_count = sum(1 for item in results if item["proxy_ok"] and not item["leak_detected"] and item["error"] is None)
    total_count = len(results)
    ok = total_count > 0 and verified_count == total_count
    return {
        "direct_ip": direct_ip,
        "target": target,
        "ok": ok,
        "verified_count": verified_count,
        "total_count": total_count,
        "error": None if ok else "one or more backends failed leak verification",
        "instances": results,
    }


def verify_dns_leaks(cfg: dict, timeout: int = DEFAULT_LEAK_TIMEOUT, strict_asn: bool = False) -> dict:
    policy = "strict-asn" if strict_asn else DEFAULT_DNS_VERIFICATION_POLICY
    try:
        timeout = validate_timeout(timeout)
        pool = fetch_pool_state(cfg)
    except LeakVerificationError as e:
        return {
            "ok": False,
            "target": DEFAULT_DNS_LEAK_SERVICE,
            "policy": policy,
            "verified_count": 0,
            "total_count": 0,
            "error": str(e),
            "instances": [],
        }
    except Exception as e:
        return {
            "ok": False,
            "target": DEFAULT_DNS_LEAK_SERVICE,
            "policy": policy,
            "verified_count": 0,
            "total_count": 0,
            "error": f"dns verification failed: {e}",
            "instances": [],
        }

    results = []
    for instance in pool.get("instances", []):
        healthy = bool(instance.get("healthy"))
        status = instance.get("status") or ("healthy" if healthy else "down")
        if not healthy:
            results.append(normalize_dns_probe_result(instance, [], f"controller status is {status}", strict_asn=strict_asn))
            continue
        try:
            payload = run_backend_dns_probe(instance.get("name") or "", timeout)
            results.append(normalize_dns_probe_result(instance, payload, strict_asn=strict_asn))
        except LeakVerificationError as e:
            results.append(normalize_dns_probe_result(instance, [], str(e), strict_asn=strict_asn))

    verified_count = sum(1 for item in results if item["dns_ok"])
    total_count = len(results)
    ok = total_count > 0 and verified_count == total_count
    return {
        "ok": ok,
        "target": DEFAULT_DNS_LEAK_SERVICE,
        "policy": policy,
        "verified_count": verified_count,
        "total_count": total_count,
        "error": None if ok else "one or more backends failed DNS leak verification",
        "instances": results,
    }


def render_leak_table(result: dict) -> str:
    lines = [f"Direct host IP: {result.get('direct_ip') or '-'}", ""]
    lines.append(
        f"{'INSTANCE':<28} {'STATUS':<20} {'CONTROLLER_IP':<16} "
        f"{'CTRL_VERIFIED':<16} {'PROXY_IP':<16} {'COUNTRY':<16} {'ASN':<12} RESULT"
    )
    for item in result.get("instances", []):
        reason = "ok" if item.get("proxy_ok") and not item.get("error") else (item.get("error") or "failed")
        lines.append(
            f"{item.get('name') or '-':<28} "
            f"{item.get('controller_status') or '-':<20} "
            f"{item.get('controller_public_ip') or '-':<16} "
            f"{item.get('controller_verified_proxy_ip') or '-':<16} "
            f"{item.get('proxy_ip') or '-':<16} "
            f"{item.get('country') or '-':<16} "
            f"{item.get('asn') or '-':<12} "
            f"{reason}"
        )
    if result.get("error") and not result.get("instances"):
        lines.append(result["error"])
    lines.append("")
    lines.append(f"Verified: {result.get('verified_count', 0)}/{result.get('total_count', 0)} backends")
    lines.append(f"Leak result: {'PASS' if result.get('ok') else 'FAIL'}")
    return "\n".join(lines)


def render_dns_table(result: dict) -> str:
    lines = [
        f"DNS leak service: {result.get('target') or '-'}",
        f"DNS policy: {result.get('policy') or DEFAULT_DNS_VERIFICATION_POLICY}",
        "",
    ]
    lines.append(
        f"{'INSTANCE':<28} {'STATUS':<16} {'CONNECTION_IP':<16} "
        f"{'CONN_ASN':<12} {'DNS_COUNT':<9} {'DNS_ASN':<18} RESULT"
    )
    for item in result.get("instances", []):
        dns_asns = sorted({server.get("asn") for server in item.get("dns_servers") or [] if server.get("asn")})
        warnings = item.get("warnings") or []
        reason = "ok" if item.get("dns_ok") and not item.get("error") else (item.get("error") or "failed")
        if item.get("dns_ok") and warnings:
            reason = "warning: " + "; ".join(warnings)
        lines.append(
            f"{item.get('name') or '-':<28} "
            f"{item.get('controller_status') or '-':<16} "
            f"{item.get('connection_ip') or '-':<16} "
            f"{item.get('connection_asn') or '-':<12} "
            f"{item.get('resolver_count') or 0:<9} "
            f"{','.join(dns_asns) or '-':<18} "
            f"{reason}"
        )
    if result.get("error") and not result.get("instances"):
        lines.append(result["error"])
    lines.append("")
    lines.append(f"DNS verified: {result.get('verified_count', 0)}/{result.get('total_count', 0)} backends")
    lines.append(f"DNS leak result: {'PASS' if result.get('ok') else 'FAIL'}")
    return "\n".join(lines)


def normalize_stress_mode(mode: str) -> str:
    mode = (mode or "leak-only").strip().lower().replace("_", "-")
    if mode == "leak-only":
        return "leak_only"
    if mode == "rotation":
        return "rotation"
    raise LeakVerificationError("mode must be leak-only or rotation")


def init_stress_report(iterations: int, mode: str) -> dict:
    return {
        "ok": True,
        "mode": mode,
        "iterations_requested": iterations,
        "iterations_completed": 0,
        "backend_count": 0,
        "verified_backend_checks": 0,
        "leak_failures": 0,
        "availability_failures": 0,
        "duplicate_ip_events": 0,
        "rotation_outcomes": {},
        "mass_rotation_attempts": 0,
        "partial_success_count": 0,
        "cooldown_skip_count": 0,
        "forced_bypass_count": 0,
        "started_at": None,
        "finished_at": None,
        "total_seconds": 0.0,
        "artifact_paths": [],
    }


def count_duplicate_proxy_ips(instances: list[dict]) -> int:
    seen = set()
    duplicates = 0
    for item in instances:
        ip = item.get("proxy_ip")
        if not ip:
            continue
        if ip in seen:
            duplicates += 1
        seen.add(ip)
    return duplicates


def update_stress_from_leak_result(report: dict, leak: dict):
    report["backend_count"] = max(report["backend_count"], int(leak.get("total_count") or 0))
    report["verified_backend_checks"] += int(leak.get("verified_count") or 0)
    instances = leak.get("instances") or []
    report["leak_failures"] += sum(1 for item in instances if item.get("leak_detected"))
    report["availability_failures"] += sum(1 for item in instances if item.get("error") and not item.get("leak_detected"))
    report["duplicate_ip_events"] += count_duplicate_proxy_ips(instances)
    if not leak.get("ok"):
        report["ok"] = False


def update_stress_from_rotation_result(report: dict, rotation: dict):
    report["mass_rotation_attempts"] += 1
    if rotation.get("outcome") == "partial_success":
        report["partial_success_count"] += 1
    for item in rotation.get("results") or []:
        outcome = item.get("outcome") or "unknown"
        report["rotation_outcomes"][outcome] = report["rotation_outcomes"].get(outcome, 0) + 1
        if outcome == "cooldown":
            report["cooldown_skip_count"] += 1
        if item.get("forced_bypass"):
            report["forced_bypass_count"] += 1
    if not rotation.get("ok") and rotation.get("outcome") not in ("partial_success",):
        report["ok"] = False


def render_stress_summary(report: dict) -> str:
    lines = [
        f"Mode: {report['mode']}",
        f"Iterations: {report['iterations_completed']}/{report['iterations_requested']}",
        f"Backend checks: {report['verified_backend_checks']}",
        f"Leak failures: {report['leak_failures']}",
        f"Availability failures: {report['availability_failures']}",
        f"Duplicate IP events: {report['duplicate_ip_events']}",
    ]
    if report["mode"] == "rotation":
        lines.extend(
            [
                f"Mass rotation attempts: {report['mass_rotation_attempts']}",
                f"Partial successes: {report['partial_success_count']}",
                f"Cooldown skips: {report['cooldown_skip_count']}",
                f"Rotation outcomes: {json.dumps(report['rotation_outcomes'], sort_keys=True)}",
            ]
        )
    lines.append(f"Total seconds: {report['total_seconds']:.3f}")
    lines.append(f"Stress result: {'PASS' if report.get('ok') else 'FAIL'}")
    return "\n".join(lines)


def run_stress(
    cfg: dict,
    iterations: int = DEFAULT_STRESS_ITERATIONS,
    mode: str = "leak-only",
    target: str = DEFAULT_LEAK_TARGET,
    timeout: int = DEFAULT_LEAK_TIMEOUT,
    verify_after_rotation: bool = True,
) -> dict:
    iterations = validate_timeout(iterations)
    timeout = validate_timeout(timeout)
    target = validate_target(target)
    mode = normalize_stress_mode(mode)
    report = init_stress_report(iterations, mode)
    started = time.time()
    report["started_at"] = started
    for _ in range(iterations):
        if mode == "rotation":
            rotation = api_call(cfg, "POST", "/rotate/all", timeout=api_timeout_for_rotation(cfg))
            update_stress_from_rotation_result(report, rotation)
            if verify_after_rotation:
                update_stress_from_leak_result(report, verify_leaks(cfg, target=target, timeout=timeout))
        else:
            update_stress_from_leak_result(report, verify_leaks(cfg, target=target, timeout=timeout))
        report["iterations_completed"] += 1
    finished = time.time()
    report["finished_at"] = finished
    report["total_seconds"] = round(finished - started, 3)
    return report


def doctor_report(cfg: dict, repair: bool = False) -> dict:
    configured_instances = sum(1 for _ in iter_instances(cfg))
    env_file = str(gset(cfg, "env_file") or "").strip()
    env_local_exists = os.path.exists(".env.local")
    configured_env_file_exists = bool(env_file) and os.path.exists(env_file)
    auth_enabled = controller_auth_enabled(cfg)
    auth_token_configured = bool(read_controller_auth_token(cfg))

    compose = compose_check(["ps"])
    health = api_call_result(cfg, "GET", "/health", timeout=5)
    pool = api_call_result(cfg, "GET", "/pool?fresh=1", timeout=15)
    stats = tcp_check("127.0.0.1", int(gset(cfg, "stats_port")), timeout=2)

    pool_payload = pool.get("payload") if isinstance(pool.get("payload"), dict) else {}
    healthy_count = int(pool_payload.get("healthy") or 0)
    backend_count = int(pool_payload.get("count") or configured_instances)
    pool_status = pool_payload.get("pool_status") or ("healthy" if healthy_count == backend_count and backend_count else "down")
    pool_fresh_ok = pool["ok"] and pool_status == "healthy" and bool(pool_payload.get("state_fresh"))
    repair_decision = doctor_repair_decision(pool["ok"], pool_payload)
    repair_result = None
    if repair:
        if repair_decision.get("action") == "repair_requested":
            repair_result = api_call_result(
                cfg,
                "POST",
                "/repair",
                timeout=max(15, int(gset(cfg, "rotation_recovery_timeout")) + 15),
            )
        else:
            repair_result = {
                "ok": True,
                "status": None,
                "payload": {
                    "attempted": False,
                    "outcome": "skipped",
                    "reason": repair_decision.get("reason"),
                    "message": "doctor repair skipped because no safe repair action was requested",
                },
                "error": None,
            }
    checks = {
        "compose_stack": {
            "ok": compose["ok"],
            "returncode": compose["returncode"],
            "error": compose["stderr"] if not compose["ok"] else None,
        },
        "controller_health": {
            "ok": health["ok"] and (health.get("payload") or {}).get("status") == "ok",
            "error": health["error"],
        },
        "pool_fresh": {
            "ok": pool_fresh_ok,
            "pool_status": pool_status,
            "state_fresh": bool(pool_payload.get("state_fresh")),
            "healthy_backends": healthy_count,
            "backend_count": backend_count,
            "degraded_reasons": pool_payload.get("degraded_reasons") or [],
            "error": pool["error"],
        },
        "haproxy_stats_port": {
            "ok": stats["ok"],
            "bind": "127.0.0.1",
            "port": int(gset(cfg, "stats_port")),
            "error": stats["error"],
        },
        "env_local": {
            "ok": env_local_exists,
            "path": ".env.local",
            "configured_env_file": env_file or None,
            "configured_env_file_exists": configured_env_file_exists,
        },
        "image_freshness": {
            "ok": True,
            "up_pulls_images_by_default": True,
            "skip_flag": "--no-pull",
        },
        "controller_auth": {
            "ok": (not auth_enabled) or auth_token_configured,
            "enabled": auth_enabled,
            "token_configured": auth_token_configured,
            "error": None if (not auth_enabled or auth_token_configured) else "controller auth is enabled but no token is configured",
        },
    }
    ok = (
        checks["compose_stack"]["ok"]
        and checks["controller_health"]["ok"]
        and checks["pool_fresh"]["ok"]
        and healthy_count > 0
        and checks["haproxy_stats_port"]["ok"]
        and checks["controller_auth"]["ok"]
    )
    return {
        "ok": ok,
        "configured_instances": configured_instances,
        "pool_status": pool_status,
        "healthy_backends": healthy_count,
        "backend_count": backend_count,
        "repair_decision": repair_decision,
        "repair_result": repair_result,
        "checks": checks,
    }


def doctor_repair_decision(pool_ok: bool, pool_payload: dict) -> dict:
    if not pool_ok:
        return {
            "action": "none",
            "reason": "pool_unavailable",
            "message": "pool state unavailable; repair decision not possible",
        }

    reasons = pool_payload.get("degraded_reasons") or []
    if pool_payload.get("pool_status") == "healthy" and not reasons:
        return {
            "action": "none",
            "reason": "pool_healthy",
            "message": "pool is healthy; no repair needed",
        }

    duplicate_repair = pool_payload.get("duplicate_repair") or {}
    duplicate_reason = None
    if "verified_duplicate_proxy_ip" in reasons:
        duplicate_reason = "verified_duplicate_proxy_ip"
    elif "duplicate_public_ip" in reasons:
        duplicate_reason = "duplicate_public_ip"

    if duplicate_reason:
        if not duplicate_repair.get("enabled", False):
            return {
                "action": "manual",
                "reason": "duplicate_repair_disabled",
                "message": "duplicate egress IP detected, but automatic repair is disabled",
            }
        in_flight = duplicate_repair.get("in_flight") or []
        if in_flight:
            return {
                "action": "repair_in_progress",
                "reason": duplicate_reason,
                "targets": in_flight,
                "message": "duplicate egress IP repair is already rotating one backend",
            }
        backoff = duplicate_repair.get("backoff_remaining") or {}
        if backoff:
            return {
                "action": "wait_backoff",
                "reason": duplicate_reason,
                "backoff_remaining": backoff,
                "message": "duplicate egress IP repair recently failed; waiting before retry",
            }
        return {
            "action": "repair_requested",
            "reason": duplicate_reason,
            "message": "fresh pool check requested duplicate egress IP repair",
        }

    if "egress_verification_failed" in reasons or "proxy_failure" in reasons:
        if not duplicate_repair.get("enabled", False):
            return {
                "action": "manual",
                "reason": "proxy_repair_disabled",
                "message": "proxy/egress failure detected, but automatic repair is disabled",
            }
        in_flight = duplicate_repair.get("in_flight") or []
        if in_flight:
            return {
                "action": "repair_in_progress",
                "reason": "proxy_failure",
                "targets": in_flight,
                "message": "pool repair is already rotating one backend",
            }
        backoff = duplicate_repair.get("backoff_remaining") or {}
        if backoff:
            return {
                "action": "wait_backoff",
                "reason": "proxy_failure",
                "backoff_remaining": backoff,
                "message": "pool repair recently failed; waiting before retry",
            }
        targets = [
            s.get("name")
            for s in pool_payload.get("instances") or []
            if s.get("healthy") and (
                s.get("last_rotation_outcome") == "proxy_failure"
                or (s.get("verified_proxy_ip_error") and not s.get("egress_state_fresh"))
            )
        ]
        if targets:
            return {
                "action": "repair_requested",
                "reason": "proxy_failure",
                "targets": targets,
                "message": "fresh pool check found proxy/egress failure; request one backend repair rotation",
            }
        return {
            "action": "manual",
            "reason": "egress_verification_failed",
            "message": "controller could not verify proxy egress; inspect backend proxy/network before rotating",
        }
    if "public_ip_mismatch" in reasons:
        return {
            "action": "monitor",
            "reason": "public_ip_mismatch",
            "message": "gluetun public IP differs from verified proxy IP; no rotation unless verified proxy IP is duplicated",
        }
    if "stale_state" in reasons:
        return {
            "action": "refresh_requested",
            "reason": "stale_state",
            "message": "fresh pool check requested a live state refresh",
        }
    if "too_few_healthy_backends" in reasons:
        return {
            "action": "manual",
            "reason": "too_few_healthy_backends",
            "message": "too few healthy backends; inspect unhealthy containers before rotating",
        }
    if "recovery_timeout" in reasons or "proxy_failure" in reasons:
        return {
            "action": "monitor",
            "reason": "recent_recovery_failure",
            "message": "recent recovery/proxy failure is degraded state; duplicate repair handles only duplicate IPs automatically",
        }
    return {
        "action": "manual",
        "reason": "degraded_pool",
        "message": "pool is degraded; no automatic repair action is available for these reasons",
    }


def render_doctor_report(report: dict) -> str:
    lines = [
        f"Doctor result: {'PASS' if report.get('ok') else 'FAIL'}",
        f"Pool status: {report.get('pool_status')} ({report.get('healthy_backends')}/{report.get('backend_count')} healthy)",
        f"Repair decision: {(report.get('repair_decision') or {}).get('action')} - {(report.get('repair_decision') or {}).get('message')}",
        "",
        f"{'CHECK':<24} {'OK':<5} DETAIL",
    ]
    for name, check in report.get("checks", {}).items():
        detail = check.get("error") or ""
        if name == "pool_fresh":
            reasons = ",".join(check.get("degraded_reasons") or []) or "-"
            detail = (
                f"status={check.get('pool_status')} fresh={check.get('state_fresh')} "
                f"healthy={check.get('healthy_backends')}/{check.get('backend_count')} reasons={reasons}"
            )
        elif name == "env_local":
            detail = (
                f".env.local={check.get('ok')} configured={check.get('configured_env_file') or '-'} "
                f"configured_exists={check.get('configured_env_file_exists')}"
            )
        elif name == "image_freshness":
            detail = "up pulls images by default; use --no-pull to skip"
        elif name == "controller_auth":
            detail = detail or f"enabled={check.get('enabled')} token_configured={check.get('token_configured')}"
        elif name == "haproxy_stats_port":
            detail = detail or f"{check.get('bind')}:{check.get('port')} reachable"
        lines.append(f"{name:<24} {str(bool(check.get('ok'))):<5} {detail}")
    repair_result = report.get("repair_result")
    if repair_result:
        payload = repair_result.get("payload") or {}
        lines.append("")
        lines.append(
            f"Repair result: {payload.get('outcome') or '-'} "
            f"attempted={payload.get('attempted')} ok={repair_result.get('ok')}"
        )
    return "\n".join(lines)


def cmd_up(cfg, pull_images: bool = True):
    generate(cfg)
    if pull_images:
        log.info("Pulling latest runtime images (use --no-pull to skip)")
        compose_cmd(["pull", "--ignore-buildable"])
    else:
        log.info("Skipping image pull (--no-pull)")
    compose_cmd(["up", "-d", "--build", "--remove-orphans"])
    proxy_host = display_host(gset(cfg, "api_bind"))
    api_host = display_host(gset(cfg, "api_bind"))
    stats_host = display_host(gset(cfg, "stats_bind"))
    log.info(
        "Pool up. Proxy http://%s:%s | API+dashboard http://%s:%s | Stats http://%s:%s/stats",
        proxy_host,
        gset(cfg, "proxy_port"),
        api_host,
        gset(cfg, "api_port"),
        stats_host,
        gset(cfg, "stats_port"),
    )


def cmd_status(cfg):
    data = api_call(cfg, "GET", "/pool")
    print(
        f"{'INSTANCE':<28} {'STATUS':<20} {'FRESH':<6} {'EGRESS':<6} {'HEALTHY':<8} "
        f"{'ROT':<5} {'OUTCOME':<22} {'COOLDOWN':<16} {'PUBLIC IP':<16} VERIFIED IP"
    )
    for it in data.get("instances", []):
        status = it.get("status") or ("healthy" if it.get("healthy") else "down")
        cooldown = float(it.get("cooldown_remaining_seconds") or 0)
        cooldown_text = f"{cooldown:.0f}s" if cooldown > 0 else "-"
        print(
            f"{it['name']:<28} {status:<20} {str(bool(it.get('state_fresh'))):<6} "
            f"{str(bool(it.get('egress_state_fresh'))):<6} {str(it['healthy']):<8} "
            f"{it['rotations']:<5} {it.get('last_rotation_outcome') or '-':<22} "
            f"{cooldown_text:<16} {it.get('public_ip') or '-':<16} {it.get('verified_proxy_ip') or '-'}"
        )
    print(
        f"\npool {data.get('pool_status', '-')} fresh {data.get('state_fresh', False)} "
        f"healthy {data.get('healthy')}/{data.get('count')}  rotations {data.get('rotations_total')}"
    )


def cmd_rotate(cfg, target):
    path = "/rotate" if not target else ("/rotate/all" if target == "all" else f"/rotate/{target}")
    timeout = api_timeout_for_rotation(cfg) if target == "all" else 15
    print(json.dumps(api_call(cfg, "POST", path, timeout=timeout), indent=2))


def cmd_verify_leaks(cfg, json_output: bool = False, timeout: int = DEFAULT_LEAK_TIMEOUT, target: str = DEFAULT_LEAK_TARGET):
    result = verify_leaks(cfg, target=target, timeout=timeout)
    if json_output:
        print(json.dumps(result, indent=2))
    else:
        print(render_leak_table(result))
    if not result.get("ok"):
        raise SystemExit(1)


def cmd_verify_dns(
    cfg,
    json_output: bool = False,
    timeout: int = DEFAULT_LEAK_TIMEOUT,
    strict_asn: bool = False,
):
    result = verify_dns_leaks(cfg, timeout=timeout, strict_asn=strict_asn)
    if json_output:
        print(json.dumps(result, indent=2))
    else:
        print(render_dns_table(result))
    if not result.get("ok"):
        raise SystemExit(1)


def cmd_stress(
    cfg: dict,
    iterations: int = DEFAULT_STRESS_ITERATIONS,
    mode: str = "leak-only",
    timeout: int = DEFAULT_LEAK_TIMEOUT,
    target: str = DEFAULT_LEAK_TARGET,
    out_dir: str | None = None,
    json_output: bool = False,
    verify_after_rotation: bool = True,
):
    result = run_stress(
        cfg,
        iterations=iterations,
        mode=mode,
        target=target,
        timeout=timeout,
        verify_after_rotation=verify_after_rotation,
    )
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        summary_path = os.path.join(out_dir, "summary.json")
        result["artifact_paths"].append(summary_path)
        write_text(summary_path, json.dumps(result, indent=2) + "\n")
    if json_output:
        print(json.dumps(result, indent=2))
    else:
        print(render_stress_summary(result))
    if not result.get("ok"):
        raise SystemExit(1)


def cmd_doctor(cfg: dict, json_output: bool = False, repair: bool = False):
    result = doctor_report(cfg, repair=repair)
    if json_output:
        print(json.dumps(result, indent=2))
    else:
        print(render_doctor_report(result))
    if not result.get("ok"):
        raise SystemExit(1)


def build_parser():
    p = argparse.ArgumentParser(description="chamosel - spin the wheel, change the skin")
    p.add_argument("action", choices=["genkey", "generate", "up", "down", "status", "rotate", "verify-leaks", "verify-dns", "stress", "doctor"])
    p.add_argument("rotate_target", nargs="?", help="for rotate: instance name or 'all'")
    p.add_argument("-c", "--config", default=CONFIG_FILE)
    p.add_argument("--no-pull", action="store_true",
                   help="for up: skip docker compose pull and use local images")
    p.add_argument("--json", dest="json_output", action="store_true",
                   help="for verify-leaks/verify-dns/stress/doctor: output one JSON object")
    p.add_argument("--timeout", type=int, default=DEFAULT_LEAK_TIMEOUT,
                   help=f"for verify-leaks/verify-dns: request timeout in seconds (default: {DEFAULT_LEAK_TIMEOUT})")
    p.add_argument("--target", dest="leak_target", default=DEFAULT_LEAK_TARGET,
                   help=f"for verify-leaks/stress: public-IP JSON target (default: {DEFAULT_LEAK_TARGET})")
    p.add_argument("--iterations", type=int, default=DEFAULT_STRESS_ITERATIONS,
                   help=f"for stress: iteration count (default: {DEFAULT_STRESS_ITERATIONS})")
    p.add_argument("--mode", dest="stress_mode", choices=["leak-only", "rotation"], default="leak-only",
                   help="for stress: leak-only or rotation")
    p.add_argument("--out-dir", default=None,
                   help="for stress: write summary.json to this directory")
    p.add_argument("--no-verify", action="store_true",
                   help="for stress --mode rotation: skip verify-leaks after each rotation")
    p.add_argument("--repair", action="store_true",
                   help="for doctor: after diagnosis, request one safe duplicate-IP repair action")
    p.add_argument("--strict-dns-asn", action="store_true",
                   help="for verify-dns: fail when resolver ASN differs from backend connection ASN")
    return p


def main():
    p = build_parser()
    a = p.parse_args()
    if a.action == "genkey":
        print(gen_api_key()); return
    cfg = load_config(a.config)
    if a.action == "generate": generate(cfg)
    elif a.action == "up": cmd_up(cfg, pull_images=not a.no_pull)
    elif a.action == "down": compose_cmd(["down"])
    elif a.action == "status": cmd_status(cfg)
    elif a.action == "rotate": cmd_rotate(cfg, a.rotate_target)
    elif a.action == "verify-leaks": cmd_verify_leaks(cfg, a.json_output, a.timeout, a.leak_target)
    elif a.action == "verify-dns": cmd_verify_dns(cfg, a.json_output, a.timeout, a.strict_dns_asn)
    elif a.action == "stress":
        cmd_stress(
            cfg,
            iterations=a.iterations,
            mode=a.stress_mode,
            timeout=a.timeout,
            target=a.leak_target,
            out_dir=a.out_dir,
            json_output=a.json_output,
            verify_after_rotation=not a.no_verify,
        )
    elif a.action == "doctor": cmd_doctor(cfg, a.json_output, repair=a.repair)


if __name__ == "__main__":
    main()
