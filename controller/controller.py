#!/usr/bin/env python3
"""chamosel controller - orchestration service for a gluetun VPN pool.

Runs as a sidecar on the same Docker network as the gluetun instances. Talks
to each gluetun control server (default :8000) to read public IP / health and
to trigger graceful IP rotation (stop -> start the VPN; gluetun picks a new
server WITHOUT a container restart).

Stdlib only - no pip dependencies.

Features:
  - API-key auth against gluetun's control server (v3.40+ requires auth).
  - Control-API version detection per instance (new /v1/vpn/* with fallback to
    legacy /v1/openvpn/*), cached after first success.
  - Background poller keeps a fresh snapshot so /metrics and the dashboard are
    cheap and don't hammer gluetun on every scrape.
  - Rotation cooldown to avoid hammering one instance.
  - Per-instance state: current IP, IP history, rotation count, timestamps;
    persisted to disk so it survives controller restarts.
  - Prometheus metrics at /metrics and an auto-refreshing HTML dashboard at /.

Environment:
  INSTANCES            comma-separated gluetun container names (DNS-resolvable)
  GLUETUN_CONTROL_PORT control server port inside each gluetun (default 8000)
  GLUETUN_API_KEY      api key sent as X-API-Key to each gluetun control server
  LISTEN_PORT          port this service listens on (default 8800)
  AUTO_ROTATE_SECONDS  if >0, rotate one instance every N seconds (default 0)
  ROTATE_COOLDOWN      min seconds between rotations of the same instance (60)
  ROTATION_RECOVERY_TIMEOUT seconds to wait for healthy+changed IP rotation (30)
  ROTATE_ALL_BATCH_SIZE max concurrent backends for /rotate/all batches (2)
  ROTATE_ALL_BATCH_DELAY_SECONDS delay between /rotate/all batches (2)
  POOL_DEGRADED_MIN_HEALTHY min healthy backends before pool is degraded (auto)
  AUTO_REPAIR_DUPLICATE_IPS rotate one duplicate-IP backend after refresh (true)
  DUPLICATE_REPAIR_RETRY_COOLDOWN seconds before retrying failed duplicate repair (300)
  EGRESS_VERIFY_TARGET target URL for backend proxy egress verification
  EGRESS_VERIFY_TIMEOUT per-backend egress verification timeout seconds (10)
  EGRESS_VERIFY_TTL max age for verified proxy IP cache seconds (120)
  EGRESS_VERIFY_ON_FRESH verify backend proxy egress during /pool?fresh=1 (true)
  POLL_INTERVAL        background health/IP poll interval seconds (default 15)
  POLL_WORKERS         max concurrent instance polls (default min(16, pool size))
  STATE_FILE           path to persist state JSON (default /data/state.json)

Endpoints:
  GET  /                         HTML dashboard
  GET  /health                   liveness
  GET  /pool                     per-instance health + public IP (cached)
  GET  /pool?fresh=1             force a live refresh first
  GET  /metrics                  Prometheus exposition format
  POST /rotate                   rotate one random eligible instance
  POST /rotate/<name>            rotate a named instance
  POST /rotate/all               rotate every eligible instance in bounded batches
"""

import hmac
import json
import os
import ipaddress
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

INSTANCES = [s.strip() for s in os.environ.get("INSTANCES", "").split(",") if s.strip()]
CONTROL_PORT = int(os.environ.get("GLUETUN_CONTROL_PORT", "8000"))
API_KEY = os.environ.get("GLUETUN_API_KEY", "").strip()
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8800"))
AUTO_ROTATE = int(os.environ.get("AUTO_ROTATE_SECONDS", "0"))
ROTATE_COOLDOWN = int(os.environ.get("ROTATE_COOLDOWN", "60"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "15"))
STATE_FILE = os.environ.get("STATE_FILE", "/data/state.json")
HTTP_TIMEOUT = 8
IP_HISTORY_MAX = 10
ROTATION_RECOVERY_TIMEOUT = int(os.environ.get("ROTATION_RECOVERY_TIMEOUT", "30"))
ROTATE_ALL_BATCH_SIZE = max(1, int(os.environ.get("ROTATE_ALL_BATCH_SIZE", "2")))
ROTATE_ALL_BATCH_DELAY_SECONDS = max(0.0, float(os.environ.get("ROTATE_ALL_BATCH_DELAY_SECONDS", "2")))
POOL_DEGRADED_MIN_HEALTHY = os.environ.get("POOL_DEGRADED_MIN_HEALTHY", "auto").strip().lower()
AUTO_REPAIR_DUPLICATE_IPS = os.environ.get("AUTO_REPAIR_DUPLICATE_IPS", "true").strip().lower() not in ("0", "false", "no", "off")
DUPLICATE_REPAIR_RETRY_COOLDOWN = max(0, int(os.environ.get("DUPLICATE_REPAIR_RETRY_COOLDOWN", "300")))
GLUETUN_PROXY_PORT = int(os.environ.get("GLUETUN_PROXY_PORT", "8888"))
EGRESS_VERIFY_TARGET = os.environ.get("EGRESS_VERIFY_TARGET", "https://ifconfig.co/json").strip()
EGRESS_VERIFY_TIMEOUT = max(1, int(os.environ.get("EGRESS_VERIFY_TIMEOUT", "10")))
EGRESS_VERIFY_TTL = max(0, int(os.environ.get("EGRESS_VERIFY_TTL", "120")))
EGRESS_VERIFY_ON_FRESH = os.environ.get("EGRESS_VERIFY_ON_FRESH", "true").strip().lower() not in ("0", "false", "no", "off")
CONTROLLER_AUTH_ENABLED = os.environ.get("CONTROLLER_AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
CONTROLLER_AUTH_TOKEN = os.environ.get("CONTROLLER_AUTH_TOKEN", "").strip()
CONTROLLER_AUTH_HEADER = "X-Chamosel-Auth"
CONTROLLER_AUTH_COOKIE = "chamosel_auth"
POLL_WORKERS = int(os.environ.get("POLL_WORKERS", str(max(1, min(16, len(INSTANCES) or 1)))))

STATUS_HEALTHY = "healthy"
STATUS_RECONNECTING = "reconnecting"
STATUS_UNREACHABLE = "unreachable"
STATUS_UNAUTHORIZED = "unauthorized"
STATUS_UNSUPPORTED_CONTROL = "unsupported_control"

OUTCOME_SUCCESS = "success"
OUTCOME_HEALTHY_IP_UNCHANGED = "healthy_ip_unchanged"
OUTCOME_PROXY_FAILURE = "proxy_failure"
OUTCOME_COOLDOWN = "cooldown"
OUTCOME_UNKNOWN_INSTANCE = "unknown_instance"
OUTCOME_UNHEALTHY = "unhealthy"
OUTCOME_UNAUTHORIZED = "unauthorized"
OUTCOME_UNSUPPORTED_CONTROL = "unsupported_control"
OUTCOME_CONTROL_UNREACHABLE = "control_unreachable"
OUTCOME_COMMAND_ERROR = "command_error"
OUTCOME_RECOVERY_TIMEOUT = "recovery_timeout"

AGG_OUTCOME_SUCCESS = "success"
AGG_OUTCOME_PARTIAL_SUCCESS = "partial_success"
AGG_OUTCOME_ALL_SKIPPED = "all_skipped"
AGG_OUTCOME_FAILED = "failed"

POOL_STATUS_HEALTHY = "healthy"
POOL_STATUS_DEGRADED = "degraded"
POOL_STATUS_DOWN = "down"

DEGRADED_STALE_STATE = "stale_state"
DEGRADED_DUPLICATE_PUBLIC_IP = "duplicate_public_ip"
DEGRADED_VERIFIED_DUPLICATE_PROXY_IP = "verified_duplicate_proxy_ip"
DEGRADED_PUBLIC_IP_MISMATCH = "public_ip_mismatch"
DEGRADED_EGRESS_VERIFICATION_FAILED = "egress_verification_failed"
DEGRADED_TOO_FEW_HEALTHY = "too_few_healthy_backends"
DEGRADED_RECOVERY_TIMEOUT = "recovery_timeout"
DEGRADED_PROXY_FAILURE = "proxy_failure"
DEGRADED_HEALTHY_IP_UNCHANGED = "healthy_ip_unchanged"

DUPLICATE_REPAIR_LOCK = threading.Lock()
DUPLICATE_REPAIR_IN_FLIGHT = set()
DUPLICATE_REPAIR_BACKOFF_UNTIL = {}
DUPLICATE_REPAIR_SCHEDULED_TOTAL = 0

# New control API (gluetun v3.41+) first, then legacy (v3.40 and older).
STATUS_PATHS = ("/v1/vpn/status", "/v1/openvpn/status")


def log(msg: str):
    print(f"[chamosel] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def sleep(seconds: float):
    time.sleep(seconds)


def controller_auth_required() -> bool:
    return CONTROLLER_AUTH_ENABLED


def controller_auth_cookie(headers) -> str:
    raw = headers.get("Cookie", "")
    if not raw:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except Exception:
        return ""
    morsel = cookie.get(CONTROLLER_AUTH_COOKIE)
    return morsel.value if morsel else ""


def controller_auth_valid(headers) -> bool:
    if not controller_auth_required():
        return True
    if not CONTROLLER_AUTH_TOKEN:
        return False
    supplied = headers.get(CONTROLLER_AUTH_HEADER, "")
    if supplied and hmac.compare_digest(str(supplied), CONTROLLER_AUTH_TOKEN):
        return True
    cookie_token = controller_auth_cookie(headers)
    return bool(cookie_token) and hmac.compare_digest(str(cookie_token), CONTROLLER_AUTH_TOKEN)


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #

class State:
    """Thread-safe per-instance state with disk persistence."""

    def __init__(self):
        self.lock = threading.Lock()
        self.inst = {
            name: {
                "name": name,
                "healthy": False,
                "status": STATUS_UNREACHABLE,
                "state_fresh": False,
                "last_error": None,
                "public_ip": None,
                "verified_proxy_ip": None,
                "verified_proxy_ip_seen_at": 0.0,
                "verified_proxy_ip_error": None,
                "ip_history": [],          # most-recent-first
                "rotations": 0,
                "rotation_errors": 0,
                "last_rotated": 0.0,
                "last_rotation_attempted": 0.0,
                "last_rotation_message": None,
                "last_rotation_old_ip": None,
                "last_rotation_new_ip": None,
                "last_seen": 0.0,
                "last_rotation_outcome": None,
                "status_path": None,       # cached working control path
                "rotation_errors_by_outcome": {},
                "cooldown_started_at": 0.0,
                "cooldown_until": 0.0,
                "cooldown_reason": None,
                "cooldown_attempt_count": 0,
                "forced_bypass_count": 0,
            }
            for name in INSTANCES
        }
        self.rotations_total = 0
        self.rotation_errors_total = 0
        self.rotation_errors_by_outcome = {}
        self._load()

    def _load(self):
        try:
            with open(STATE_FILE) as fh:
                saved = json.load(fh)
            for name, s in saved.get("inst", {}).items():
                if name in self.inst:
                    for k in ("ip_history", "rotations", "rotation_errors",
                              "last_rotated", "public_ip", "status_path",
                              "status", "last_error", "last_rotation_outcome",
                              "rotation_errors_by_outcome", "last_rotation_attempted",
                              "last_rotation_message", "last_rotation_old_ip",
                              "last_rotation_new_ip", "cooldown_started_at",
                              "cooldown_until", "cooldown_reason",
                              "cooldown_attempt_count", "forced_bypass_count",
                              "verified_proxy_ip", "verified_proxy_ip_seen_at",
                              "verified_proxy_ip_error"):
                        if k in s:
                            self.inst[name][k] = s[k]
                    self.inst[name]["state_fresh"] = False
            self.rotations_total = saved.get("rotations_total", 0)
            self.rotation_errors_total = saved.get("rotation_errors_total", 0)
            self.rotation_errors_by_outcome = saved.get("rotation_errors_by_outcome", {})
            log(f"loaded state from {STATE_FILE}")
        except FileNotFoundError:
            pass
        except Exception as e:
            log(f"could not load state: {e}")

    def _save_locked(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({
                    "inst": self.inst,
                    "rotations_total": self.rotations_total,
                    "rotation_errors_total": self.rotation_errors_total,
                    "rotation_errors_by_outcome": self.rotation_errors_by_outcome,
                }, fh)
            os.replace(tmp, STATE_FILE)
        except Exception as e:
            log(f"could not save state: {e}")

    def update_health(self, name: str, healthy: bool, ip=None, status: str | None = None, error: str | None = None):
        with self.lock:
            s = self.inst[name]
            s["healthy"] = healthy
            s["status"] = status or (STATUS_HEALTHY if healthy else STATUS_UNREACHABLE)
            s["state_fresh"] = True
            s["last_error"] = error
            s["last_seen"] = time.time()
            if ip and ip != s["public_ip"]:
                s["public_ip"] = ip
                if not s["ip_history"] or s["ip_history"][0] != ip:
                    s["ip_history"].insert(0, ip)
                    del s["ip_history"][IP_HISTORY_MAX:]
            self._save_locked()

    def update_verified_proxy_ip(self, name: str, ip: str | None, error: str | None = None):
        with self.lock:
            s = self.inst[name]
            if ip:
                s["verified_proxy_ip"] = ip
                s["verified_proxy_ip_seen_at"] = time.time()
                s["verified_proxy_ip_error"] = None
            else:
                s["verified_proxy_ip_error"] = error or "egress verification failed"
            self._save_locked()

    def record_rotation(
        self,
        name: str,
        outcome: str,
        message: str | None = None,
        old_ip: str | None = None,
        new_ip: str | None = None,
    ):
        with self.lock:
            s = self.inst[name]
            s["last_rotation_outcome"] = outcome
            s["last_rotation_attempted"] = time.time()
            if message is not None:
                s["last_rotation_message"] = message
            s["last_rotation_old_ip"] = old_ip
            s["last_rotation_new_ip"] = new_ip
            if outcome == OUTCOME_SUCCESS:
                s["rotations"] += 1
                s["last_rotated"] = time.time()
                self.rotations_total += 1
            else:
                s["rotation_errors"] += 1
                self.rotation_errors_total += 1
                s["rotation_errors_by_outcome"][outcome] = s["rotation_errors_by_outcome"].get(outcome, 0) + 1
                self.rotation_errors_by_outcome[outcome] = self.rotation_errors_by_outcome.get(outcome, 0) + 1
            self._save_locked()

    def mark_rotation_outcome(
        self,
        name: str,
        outcome: str,
        message: str | None = None,
        old_ip: str | None = None,
        new_ip: str | None = None,
    ):
        with self.lock:
            s = self.inst[name]
            s["last_rotation_outcome"] = outcome
            s["last_rotation_attempted"] = time.time()
            if message is not None:
                s["last_rotation_message"] = message
            s["last_rotation_old_ip"] = old_ip
            s["last_rotation_new_ip"] = new_ip
            self._save_locked()

    def set_status_path(self, name: str, path: str):
        with self.lock:
            self.inst[name]["status_path"] = path

    def clear_status_path(self, name: str):
        with self.lock:
            self.inst[name]["status_path"] = None

    def get_status_path(self, name: str):
        with self.lock:
            return self.inst[name]["status_path"]

    def set_status(self, name: str, status: str, error: str | None = None):
        with self.lock:
            s = self.inst[name]
            s["healthy"] = status == STATUS_HEALTHY
            s["status"] = status
            s["state_fresh"] = True
            s["last_error"] = error
            s["last_seen"] = time.time()
            self._save_locked()

    def cooldown_remaining(self, name: str) -> float:
        with self.lock:
            s = self.inst[name]
            now = time.time()
            success_elapsed = now - s["last_rotated"] if s["last_rotated"] else ROTATE_COOLDOWN
            success_remaining = max(0.0, ROTATE_COOLDOWN - success_elapsed)
            failure_remaining = max(0.0, float(s.get("cooldown_until") or 0.0) - now)
            return max(success_remaining, failure_remaining)

    def cooldown_info(self, name: str) -> dict:
        with self.lock:
            s = self.inst[name]
            now = time.time()
            success_elapsed = now - s["last_rotated"] if s["last_rotated"] else ROTATE_COOLDOWN
            success_remaining = max(0.0, ROTATE_COOLDOWN - success_elapsed)
            failure_remaining = max(0.0, float(s.get("cooldown_until") or 0.0) - now)
            remaining = max(success_remaining, failure_remaining)
            reason = s.get("cooldown_reason")
            if remaining > 0 and not reason and s.get("last_rotated"):
                reason = OUTCOME_COOLDOWN
            if remaining <= 0:
                reason = None
            return {
                "cooldown_started_at": s.get("cooldown_started_at", 0.0),
                "cooldown_until": s.get("cooldown_until", 0.0) if remaining > 0 else 0.0,
                "cooldown_remaining_seconds": round(remaining, 3),
                "cooldown_reason": reason,
                "cooldown_attempt_count": s.get("cooldown_attempt_count", 0),
                "forced_bypass_count": s.get("forced_bypass_count", 0),
            }

    def start_cooldown(self, name: str, reason: str, duration: int | None = None):
        with self.lock:
            s = self.inst[name]
            now = time.time()
            s["cooldown_started_at"] = now
            s["cooldown_until"] = now + (ROTATE_COOLDOWN if duration is None else duration)
            s["cooldown_reason"] = reason
            s["cooldown_attempt_count"] = int(s.get("cooldown_attempt_count") or 0) + 1
            self._save_locked()

    def record_forced_bypass(self, name: str):
        with self.lock:
            self.inst[name]["forced_bypass_count"] = int(self.inst[name].get("forced_bypass_count") or 0) + 1
            self._save_locked()

    def snapshot(self) -> dict:
        with self.lock:
            now = time.time()
            instances = []
            for state in self.inst.values():
                s = dict(state)
                success_elapsed = now - s["last_rotated"] if s["last_rotated"] else ROTATE_COOLDOWN
                success_remaining = max(0.0, ROTATE_COOLDOWN - success_elapsed)
                failure_remaining = max(0.0, float(s.get("cooldown_until") or 0.0) - now)
                remaining = max(success_remaining, failure_remaining)
                if remaining > 0 and not s.get("cooldown_reason") and s.get("last_rotated"):
                    s["cooldown_reason"] = OUTCOME_COOLDOWN
                if remaining <= 0:
                    s["cooldown_until"] = 0.0
                    s["cooldown_reason"] = None
                s["cooldown_remaining_seconds"] = round(remaining, 3)
                seen_at = float(s.get("verified_proxy_ip_seen_at") or 0.0)
                egress_fresh = (
                    bool(s.get("verified_proxy_ip"))
                    and not s.get("verified_proxy_ip_error")
                    and EGRESS_VERIFY_TTL > 0
                    and now - seen_at <= EGRESS_VERIFY_TTL
                )
                s["egress_state_fresh"] = egress_fresh
                s["public_ip_mismatch"] = bool(
                    s.get("healthy")
                    and s.get("public_ip")
                    and s.get("verified_proxy_ip")
                    and egress_fresh
                    and s.get("public_ip") != s.get("verified_proxy_ip")
                )
                instances.append(s)
            pool_status, degraded_reasons, state_fresh = pool_summary(instances)
            return {
                "count": len(INSTANCES),
                "healthy": sum(1 for s in self.inst.values() if s["healthy"]),
                "pool_status": pool_status,
                "state_fresh": state_fresh,
                "degraded_reasons": degraded_reasons,
                "duplicate_repair": duplicate_repair_snapshot(),
                "rotations_total": self.rotations_total,
                "rotation_errors_total": self.rotation_errors_total,
                "rotation_errors_by_outcome": dict(self.rotation_errors_by_outcome),
                "instances": instances,
            }


def min_healthy_threshold() -> int:
    if not INSTANCES:
        return 0
    if POOL_DEGRADED_MIN_HEALTHY in ("", "auto"):
        return len(INSTANCES)
    try:
        return max(1, min(len(INSTANCES), int(POOL_DEGRADED_MIN_HEALTHY)))
    except ValueError:
        return len(INSTANCES)


def pool_identity_ip(s: dict) -> tuple[str | None, str | None]:
    if not s.get("healthy"):
        return None, None
    if s.get("verified_proxy_ip") and s.get("egress_state_fresh"):
        return s.get("verified_proxy_ip"), "verified"
    if s.get("public_ip"):
        return s.get("public_ip"), "public"
    return None, None


def duplicate_identity_groups(instances: list[dict]) -> dict[tuple[str, str], list[str]]:
    groups = {}
    for s in instances:
        ip, source = pool_identity_ip(s)
        if not ip or not source:
            continue
        groups.setdefault((source, ip), []).append(s["name"])
    return {key: names for key, names in groups.items() if len(names) > 1}


def verified_duplicate_proxy_ips(instances: list[dict]) -> set[str]:
    return {
        ip
        for (source, ip), names in duplicate_identity_groups(instances).items()
        if source == "verified"
    }


def duplicate_public_ips(instances: list[dict]) -> set[str]:
    return {
        ip
        for (source, ip), names in duplicate_identity_groups(instances).items()
        if source == "public"
    }


def duplicate_repair_snapshot() -> dict:
    now = time.time()
    with DUPLICATE_REPAIR_LOCK:
        return {
            "enabled": AUTO_REPAIR_DUPLICATE_IPS,
            "in_flight": sorted(DUPLICATE_REPAIR_IN_FLIGHT),
            "retry_cooldown_seconds": DUPLICATE_REPAIR_RETRY_COOLDOWN,
            "backoff_remaining": {
                name: round(max(0.0, until - now), 3)
                for name, until in sorted(DUPLICATE_REPAIR_BACKOFF_UNTIL.items())
                if until > now
            },
            "scheduled_total": DUPLICATE_REPAIR_SCHEDULED_TOTAL,
        }


def pool_summary(instances: list[dict]) -> tuple[str, list[str], bool]:
    state_fresh = bool(instances) and all(bool(s.get("state_fresh")) for s in instances)
    healthy_count = sum(1 for s in instances if s.get("healthy"))
    reasons = []

    if not state_fresh:
        reasons.append(DEGRADED_STALE_STATE)
    if verified_duplicate_proxy_ips(instances):
        reasons.append(DEGRADED_VERIFIED_DUPLICATE_PROXY_IP)
    if duplicate_public_ips(instances):
        reasons.append(DEGRADED_DUPLICATE_PUBLIC_IP)
    if any(s.get("public_ip_mismatch") for s in instances):
        reasons.append(DEGRADED_PUBLIC_IP_MISMATCH)
    if any(s.get("healthy") and s.get("verified_proxy_ip_error") and not s.get("egress_state_fresh") for s in instances):
        reasons.append(DEGRADED_EGRESS_VERIFICATION_FAILED)
    if healthy_count < min_healthy_threshold():
        reasons.append(DEGRADED_TOO_FEW_HEALTHY)

    latest_outcomes = {s.get("last_rotation_outcome") for s in instances}
    if OUTCOME_RECOVERY_TIMEOUT in latest_outcomes:
        reasons.append(DEGRADED_RECOVERY_TIMEOUT)
    if OUTCOME_PROXY_FAILURE in latest_outcomes:
        reasons.append(DEGRADED_PROXY_FAILURE)
    if OUTCOME_HEALTHY_IP_UNCHANGED in latest_outcomes:
        reasons.append(DEGRADED_HEALTHY_IP_UNCHANGED)

    if healthy_count == 0:
        return POOL_STATUS_DOWN, sorted(set(reasons)), state_fresh
    if reasons:
        return POOL_STATUS_DEGRADED, sorted(set(reasons)), state_fresh
    return POOL_STATUS_HEALTHY, [], state_fresh


STATE = State()


# --------------------------------------------------------------------------- #
# gluetun control-server client
# --------------------------------------------------------------------------- #

def _ctrl(method: str, instance: str, path: str, body: dict | None = None):
    url = f"http://{instance}:{CONTROL_PORT}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def get_public_ip(instance: str):
    try:
        return _ctrl("GET", instance, "/v1/publicip/ip").get("public_ip") or None
    except Exception:
        return None


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return False
    return ip.is_global


def extract_verified_proxy_ip(payload: dict) -> str:
    if not isinstance(payload, dict):
        raise ValueError("response is not a JSON object")
    for key in ("ip", "query", "public_ip"):
        value = payload.get(key)
        if value and is_public_ip(str(value)):
            return str(value).strip()
    raise ValueError("response does not contain a public IP")


def probe_verified_proxy_ip(instance: str) -> tuple[str | None, str | None]:
    if not EGRESS_VERIFY_TARGET:
        return None, "egress verification target is empty"
    proxy = f"http://{instance}:{GLUETUN_PROXY_PORT}"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    req = urllib.request.Request(
        EGRESS_VERIFY_TARGET,
        headers={"accept": "application/json", "user-agent": "chamosel controller egress verifier"},
    )
    try:
        with opener.open(req, timeout=EGRESS_VERIFY_TIMEOUT) as resp:
            payload = json.load(resp)
        return extract_verified_proxy_ip(payload), None
    except Exception as e:
        return None, str(e)


def verified_proxy_ip_expired(s: dict) -> bool:
    if not s.get("verified_proxy_ip") or s.get("verified_proxy_ip_error"):
        return True
    if EGRESS_VERIFY_TTL <= 0:
        return True
    return time.time() - float(s.get("verified_proxy_ip_seen_at") or 0.0) > EGRESS_VERIFY_TTL


def refresh_verified_proxy_ip(instance: str, force: bool = False) -> dict:
    current = next((s for s in STATE.snapshot()["instances"] if s["name"] == instance), {})
    if not current.get("healthy"):
        return {"instance": instance, "verified_proxy_ip": current.get("verified_proxy_ip"), "skipped": "unhealthy"}
    if not force and not verified_proxy_ip_expired(current):
        return {"instance": instance, "verified_proxy_ip": current.get("verified_proxy_ip"), "cached": True}
    ip, error = probe_verified_proxy_ip(instance)
    STATE.update_verified_proxy_ip(instance, ip, error)
    return {"instance": instance, "verified_proxy_ip": ip, "error": error}


def detect_status_path(instance: str, force: bool = False):
    """Find the working status path for this gluetun version, cache it."""
    cached = STATE.get_status_path(instance)
    if cached and not force:
        return cached
    if force:
        STATE.clear_status_path(instance)
    saw_http = False
    for path in STATUS_PATHS:
        try:
            _ctrl("GET", instance, path)
            STATE.set_status_path(instance, path)
            STATE.set_status(instance, STATUS_RECONNECTING)
            return path
        except urllib.error.HTTPError as e:
            if e.code == 401:
                log(f"{instance}: 401 Unauthorized - check GLUETUN_API_KEY / role config")
                STATE.set_status(instance, STATUS_UNAUTHORIZED, "gluetun returned HTTP 401")
                return None
            saw_http = True
            if e.code in (404, 405):
                continue
            STATE.set_status(instance, STATUS_UNREACHABLE, f"gluetun returned HTTP {e.code}")
            return None
        except Exception:
            continue
    if saw_http:
        STATE.set_status(instance, STATUS_UNSUPPORTED_CONTROL, "no supported status endpoint")
    else:
        STATE.set_status(instance, STATUS_UNREACHABLE, "control server unreachable")
    return None


def status_to_rotation_outcome(status: str) -> str:
    return {
        STATUS_UNAUTHORIZED: OUTCOME_UNAUTHORIZED,
        STATUS_UNSUPPORTED_CONTROL: OUTCOME_UNSUPPORTED_CONTROL,
        STATUS_UNREACHABLE: OUTCOME_CONTROL_UNREACHABLE,
    }.get(status, OUTCOME_CONTROL_UNREACHABLE)


def read_health(instance: str, retry_stale_path: bool = True) -> tuple[bool, str, str | None]:
    path = detect_status_path(instance)
    if not path:
        snap = STATE.snapshot()["instances"]
        status = next((s["status"] for s in snap if s["name"] == instance), STATUS_UNREACHABLE)
        error = next((s["last_error"] for s in snap if s["name"] == instance), None)
        return False, status, error
    try:
        healthy = _ctrl("GET", instance, path).get("status", "") == "running"
        return healthy, STATUS_HEALTHY if healthy else STATUS_RECONNECTING, None
    except urllib.error.HTTPError as e:
        if e.code == 401:
            STATE.set_status(instance, STATUS_UNAUTHORIZED, "gluetun returned HTTP 401")
            return False, STATUS_UNAUTHORIZED, "gluetun returned HTTP 401"
        if retry_stale_path and e.code in (404, 405):
            STATE.clear_status_path(instance)
            fresh = detect_status_path(instance, force=True)
            if fresh and fresh != path:
                return read_health(instance, retry_stale_path=False)
            STATE.set_status(instance, STATUS_UNSUPPORTED_CONTROL, "cached status endpoint no longer works")
            return False, STATUS_UNSUPPORTED_CONTROL, "cached status endpoint no longer works"
        STATE.set_status(instance, STATUS_UNREACHABLE, f"gluetun returned HTTP {e.code}")
        return False, STATUS_UNREACHABLE, f"gluetun returned HTTP {e.code}"
    except Exception as e:
        STATE.set_status(instance, STATUS_UNREACHABLE, str(e))
        return False, STATUS_UNREACHABLE, str(e)


def is_healthy(instance: str) -> bool:
    healthy, status, error = read_health(instance)
    STATE.update_health(instance, healthy, None, status=status, error=error)
    return healthy


def refresh_instance(instance: str, verify_egress: bool = False, force_egress: bool = False) -> dict:
    healthy, status, error = read_health(instance)
    ip = get_public_ip(instance) if healthy else None
    STATE.update_health(instance, healthy, ip, status=status, error=error)
    result = {"instance": instance, "healthy": healthy, "status": status, "error": error, "public_ip": ip}
    if healthy and verify_egress:
        result["egress"] = refresh_verified_proxy_ip(instance, force=force_egress)
    return result


def select_duplicate_repair_candidate(snap: dict) -> tuple[str | None, str | None]:
    instances = snap.get("instances") or []
    by_name = {s["name"]: s for s in instances}
    now = time.time()
    for (source, ip), names in sorted(duplicate_identity_groups(instances).items()):
        candidates = names[1:]
        candidates.sort(
            key=lambda name: (
                0 if by_name[name].get("last_rotation_outcome") != OUTCOME_SUCCESS else 1,
                by_name[name].get("last_rotated") or 0,
            )
        )
        for name in candidates:
            if STATE.cooldown_remaining(name) > 0:
                continue
            with DUPLICATE_REPAIR_LOCK:
                if name in DUPLICATE_REPAIR_IN_FLIGHT:
                    continue
                if DUPLICATE_REPAIR_BACKOFF_UNTIL.get(name, 0.0) > now:
                    continue
            return name, ip
    return None, None


def duplicate_repair_worker(instance: str, duplicate_ip: str):
    try:
        log(f"duplicate-egress repair: rotating {instance} from duplicated IP {duplicate_ip}")
        result = rotate_instance(instance, force=False, repair_duplicate_ip=duplicate_ip)
        log(f"duplicate-egress repair result: {result}")
        with DUPLICATE_REPAIR_LOCK:
            if result.get("ok"):
                DUPLICATE_REPAIR_BACKOFF_UNTIL.pop(instance, None)
            elif DUPLICATE_REPAIR_RETRY_COOLDOWN > 0:
                DUPLICATE_REPAIR_BACKOFF_UNTIL[instance] = time.time() + DUPLICATE_REPAIR_RETRY_COOLDOWN
    finally:
        with DUPLICATE_REPAIR_LOCK:
            DUPLICATE_REPAIR_IN_FLIGHT.discard(instance)


def repair_duplicate_ip_once() -> dict:
    global DUPLICATE_REPAIR_SCHEDULED_TOTAL
    if not AUTO_REPAIR_DUPLICATE_IPS:
        return {
            "ok": False,
            "attempted": False,
            "outcome": "blocked",
            "reason": "duplicate_repair_disabled",
            "message": "duplicate egress IP repair is disabled",
            "duplicate_repair": duplicate_repair_snapshot(),
        }

    snap = STATE.snapshot()
    reasons = snap.get("degraded_reasons") or []
    duplicate_reason = None
    if DEGRADED_VERIFIED_DUPLICATE_PROXY_IP in reasons:
        duplicate_reason = DEGRADED_VERIFIED_DUPLICATE_PROXY_IP
    elif DEGRADED_DUPLICATE_PUBLIC_IP in reasons:
        duplicate_reason = DEGRADED_DUPLICATE_PUBLIC_IP
    if duplicate_reason is None:
        return {
            "ok": True,
            "attempted": False,
            "outcome": "none",
            "reason": "no_duplicate_egress_ip",
            "message": "no duplicate verified proxy IP or public IP is repairable",
            "duplicate_repair": duplicate_repair_snapshot(),
        }

    instance, duplicate_ip = select_duplicate_repair_candidate(snap)
    if not instance:
        return {
            "ok": False,
            "attempted": False,
            "outcome": "blocked",
            "reason": duplicate_reason,
            "message": "duplicate egress IP exists, but no backend is currently eligible for repair",
            "duplicate_repair": duplicate_repair_snapshot(),
        }

    with DUPLICATE_REPAIR_LOCK:
        if instance in DUPLICATE_REPAIR_IN_FLIGHT:
            in_progress = True
        else:
            in_progress = False
            DUPLICATE_REPAIR_IN_FLIGHT.add(instance)
            DUPLICATE_REPAIR_SCHEDULED_TOTAL += 1
    if in_progress:
        return {
            "ok": False,
            "attempted": False,
            "outcome": "repair_in_progress",
            "reason": duplicate_reason,
            "target": instance,
            "duplicate_ip": duplicate_ip,
            "duplicate_repair": duplicate_repair_snapshot(),
        }

    result = None
    try:
        result = rotate_instance(instance, force=False, repair_duplicate_ip=duplicate_ip)
        with DUPLICATE_REPAIR_LOCK:
            if result.get("ok"):
                DUPLICATE_REPAIR_BACKOFF_UNTIL.pop(instance, None)
            elif DUPLICATE_REPAIR_RETRY_COOLDOWN > 0:
                DUPLICATE_REPAIR_BACKOFF_UNTIL[instance] = time.time() + DUPLICATE_REPAIR_RETRY_COOLDOWN
    finally:
        with DUPLICATE_REPAIR_LOCK:
            DUPLICATE_REPAIR_IN_FLIGHT.discard(instance)
    return {
        "ok": bool(result.get("ok")),
        "attempted": True,
        "outcome": "repair_attempted",
        "reason": duplicate_reason,
        "target": instance,
        "duplicate_ip": duplicate_ip,
        "rotation": result,
        "duplicate_repair": duplicate_repair_snapshot(),
    }


def maybe_schedule_duplicate_ip_repair():
    global DUPLICATE_REPAIR_SCHEDULED_TOTAL
    if not AUTO_REPAIR_DUPLICATE_IPS:
        return
    snap = STATE.snapshot()
    if not any(
        reason in snap.get("degraded_reasons", [])
        for reason in (DEGRADED_VERIFIED_DUPLICATE_PROXY_IP, DEGRADED_DUPLICATE_PUBLIC_IP)
    ):
        return
    instance, duplicate_ip = select_duplicate_repair_candidate(snap)
    if not instance:
        return
    with DUPLICATE_REPAIR_LOCK:
        if instance in DUPLICATE_REPAIR_IN_FLIGHT:
            return
        DUPLICATE_REPAIR_IN_FLIGHT.add(instance)
        DUPLICATE_REPAIR_SCHEDULED_TOTAL += 1
    threading.Thread(
        target=duplicate_repair_worker,
        args=(instance, duplicate_ip),
        daemon=True,
    ).start()


def refresh_instances(instances=None, verify_egress: bool = False, force_egress: bool = False):
    instances = list(instances or INSTANCES)
    if not instances:
        return []
    workers = max(1, min(POLL_WORKERS, len(instances)))
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(refresh_instance, inst, verify_egress, force_egress): inst
            for inst in instances
        }
        for fut in as_completed(future_map):
            inst = future_map[fut]
            try:
                results.append(fut.result())
            except Exception as e:
                STATE.update_health(inst, False, None, status=STATUS_UNREACHABLE, error=str(e))
                results.append({"instance": inst, "healthy": False, "status": STATUS_UNREACHABLE, "error": str(e)})
    maybe_schedule_duplicate_ip_repair()
    return results


def verify_proxy_after_rotation(instance: str) -> tuple[bool, str | None]:
    """Hook point for post-rotation proxy verification before egress probing."""
    return True, None


def wait_for_recovery(
    instance: str,
    old_ip,
    timeout: int = ROTATION_RECOVERY_TIMEOUT,
    repair_duplicate_ip: str | None = None,
) -> tuple[str, str | None, str | None, str | None]:
    deadline = time.time() + timeout
    last_new_ip = None
    last_verified_ip = None
    while time.time() < deadline:
        h = is_healthy(instance)
        if h:
            new_ip = get_public_ip(instance)
            if new_ip:
                last_new_ip = new_ip
                STATE.update_health(instance, True, new_ip, status=STATUS_HEALTHY)
            if repair_duplicate_ip:
                proxy_ok, proxy_error = verify_proxy_after_rotation(instance)
                if not proxy_ok:
                    return OUTCOME_PROXY_FAILURE, new_ip, last_verified_ip, proxy_error
                verified = refresh_verified_proxy_ip(instance, force=True)
                last_verified_ip = verified.get("verified_proxy_ip")
                if verified.get("error"):
                    return OUTCOME_PROXY_FAILURE, new_ip, last_verified_ip, verified.get("error")
                if last_verified_ip and last_verified_ip != repair_duplicate_ip:
                    return OUTCOME_SUCCESS, new_ip, last_verified_ip, None
                if new_ip and new_ip != repair_duplicate_ip:
                    return OUTCOME_SUCCESS, new_ip, last_verified_ip, None
                sleep(1)
                continue
            if new_ip and new_ip != old_ip:
                proxy_ok, proxy_error = verify_proxy_after_rotation(instance)
                if not proxy_ok:
                    return OUTCOME_PROXY_FAILURE, new_ip, last_verified_ip, proxy_error
                verified = refresh_verified_proxy_ip(instance, force=True)
                last_verified_ip = verified.get("verified_proxy_ip")
                if verified.get("error"):
                    return OUTCOME_PROXY_FAILURE, new_ip, last_verified_ip, verified.get("error")
                return OUTCOME_SUCCESS, new_ip, last_verified_ip, None
            if new_ip and old_ip and new_ip == old_ip:
                return OUTCOME_HEALTHY_IP_UNCHANGED, new_ip, last_verified_ip, None
        sleep(1)
    return OUTCOME_RECOVERY_TIMEOUT, last_new_ip, last_verified_ip, None


def rotation_response(instance: str | None, ok: bool, outcome: str, started_at: float, **extra) -> dict:
    payload = {
        "instance": instance,
        "ok": ok,
        "outcome": outcome,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "message": extra.pop("message", outcome.replace("_", " ")),
    }
    payload.update(extra)
    return payload


def skipped_cooldown_response(instance: str, started_at: float, bypassed: bool = False) -> dict:
    info = STATE.cooldown_info(instance)
    STATE.mark_rotation_outcome(
        instance,
        OUTCOME_COOLDOWN,
        message=f"cooldown: {info['cooldown_remaining_seconds']:.0f}s remaining",
    )
    return rotation_response(
        instance,
        False,
        OUTCOME_COOLDOWN,
        started_at,
        message=f"cooldown: {info['cooldown_remaining_seconds']:.0f}s remaining",
        forced_bypass=bypassed,
        **info,
    )


def rotate_instance(instance: str, force: bool = False, repair_duplicate_ip: str | None = None) -> dict:
    """Graceful rotation: PUT status stopped, then running. New server, no
    container restart. HAProxy drops the instance via health checks while it
    reconnects and re-adds it on recovery."""
    started_at = time.monotonic()
    if instance not in INSTANCES:
        return rotation_response(instance, False, OUTCOME_UNKNOWN_INSTANCE, started_at,
                                 message="unknown instance")
    forced_bypass = False
    if force and STATE.cooldown_remaining(instance) > 0:
        STATE.record_forced_bypass(instance)
        forced_bypass = True
    if not force:
        cd = STATE.cooldown_remaining(instance)
        if cd > 0:
            return skipped_cooldown_response(instance, started_at)
    path = detect_status_path(instance)
    if not path:
        current = next((s for s in STATE.snapshot()["instances"] if s["name"] == instance), {})
        outcome = status_to_rotation_outcome(current.get("status", STATUS_UNREACHABLE))
        STATE.record_rotation(instance, outcome, message="control server unreachable/unauthorized")
        return rotation_response(instance, False, outcome, started_at,
                                 message="control server unreachable/unauthorized",
                                 forced_bypass=forced_bypass)
    old_ip = STATE.inst[instance]["public_ip"] or get_public_ip(instance)
    try:
        _ctrl("PUT", instance, path, {"status": "stopped"})
        sleep(1)
        _ctrl("PUT", instance, path, {"status": "running"})
    except Exception as e:
        STATE.record_rotation(instance, OUTCOME_COMMAND_ERROR, message=str(e), old_ip=old_ip)
        return rotation_response(instance, False, OUTCOME_COMMAND_ERROR, started_at,
                                 old_ip=old_ip, message=str(e),
                                 forced_bypass=forced_bypass)
    STATE.update_health(instance, False, old_ip, status=STATUS_RECONNECTING)
    outcome, new_ip, verified_ip, recovery_error = wait_for_recovery(
        instance,
        old_ip,
        repair_duplicate_ip=repair_duplicate_ip,
    )
    if outcome != OUTCOME_SUCCESS:
        if outcome in (OUTCOME_RECOVERY_TIMEOUT, OUTCOME_PROXY_FAILURE):
            STATE.start_cooldown(instance, outcome)
        message = {
            OUTCOME_HEALTHY_IP_UNCHANGED: "VPN recovered but public IP did not change",
            OUTCOME_PROXY_FAILURE: f"VPN recovered but proxy verification failed: {recovery_error}",
            OUTCOME_RECOVERY_TIMEOUT: f"VPN did not recover with a new IP within {ROTATION_RECOVERY_TIMEOUT}s",
        }.get(outcome, outcome.replace("_", " "))
        STATE.record_rotation(instance, outcome, message=message, old_ip=old_ip, new_ip=new_ip)
        return rotation_response(
            instance,
            False,
            outcome,
            started_at,
            old_ip=old_ip,
            new_ip=new_ip,
            verified_proxy_ip=verified_ip,
            repair_duplicate_ip=repair_duplicate_ip,
            message=message,
            forced_bypass=forced_bypass,
            **STATE.cooldown_info(instance),
        )
    if repair_duplicate_ip and verified_ip and verified_ip != repair_duplicate_ip:
        message = "rotation recovered with a changed verified proxy IP"
    else:
        message = "rotation recovered with a changed public IP"
    STATE.record_rotation(instance, OUTCOME_SUCCESS, message=message, old_ip=old_ip, new_ip=new_ip)
    log(f"rotated {instance} ({old_ip} -> {new_ip})")
    return rotation_response(instance, True, OUTCOME_SUCCESS, started_at,
                             old_ip=old_ip, new_ip=new_ip,
                             verified_proxy_ip=verified_ip,
                             repair_duplicate_ip=repair_duplicate_ip,
                             message=message,
                             forced_bypass=forced_bypass,
                             **STATE.cooldown_info(instance))


def rotate_one_random(force: bool = False) -> dict:
    """Pick an instance not in cooldown; prefer ones rotated longest ago."""
    candidates = [n for n in INSTANCES if force or STATE.cooldown_remaining(n) == 0]
    if not candidates:
        return rotation_response(None, False, OUTCOME_COOLDOWN, time.monotonic(),
                                 message="all instances in cooldown")
    candidates.sort(key=lambda n: STATE.inst[n]["last_rotated"])
    return rotate_instance(candidates[0], force=force)


def rotate_all(force: bool = False) -> dict:
    started_at = time.monotonic()
    results = []
    eligible = []
    skipped = []
    for inst in INSTANCES:
        if not force and STATE.cooldown_remaining(inst) > 0:
            skipped.append(skipped_cooldown_response(inst, started_at))
        else:
            eligible.append(inst)

    batches = [
        eligible[i:i + ROTATE_ALL_BATCH_SIZE]
        for i in range(0, len(eligible), ROTATE_ALL_BATCH_SIZE)
    ]
    for index, batch in enumerate(batches):
        with ThreadPoolExecutor(max_workers=max(1, len(batch))) as pool:
            future_map = {pool.submit(rotate_instance, inst, force=force): inst for inst in batch}
            for fut in as_completed(future_map):
                inst = future_map[fut]
                try:
                    results.append(fut.result())
                except Exception as e:
                    STATE.record_rotation(inst, OUTCOME_COMMAND_ERROR, message=str(e))
                    results.append(
                        rotation_response(inst, False, OUTCOME_COMMAND_ERROR, started_at, message=str(e))
                    )
        if index < len(batches) - 1 and ROTATE_ALL_BATCH_DELAY_SECONDS > 0:
            sleep(ROTATE_ALL_BATCH_DELAY_SECONDS)

    all_results = skipped + results
    success_count = sum(1 for r in all_results if r.get("outcome") == OUTCOME_SUCCESS)
    unchanged_count = sum(1 for r in all_results if r.get("outcome") == OUTCOME_HEALTHY_IP_UNCHANGED)
    skipped_count = sum(1 for r in all_results if r.get("outcome") == OUTCOME_COOLDOWN)
    failure_count = sum(1 for r in all_results if not r.get("ok") and r.get("outcome") != OUTCOME_COOLDOWN)
    timed_out_count = sum(1 for r in all_results if r.get("outcome") == OUTCOME_RECOVERY_TIMEOUT)
    cooldown_count = sum(1 for i in INSTANCES if STATE.cooldown_remaining(i) > 0)
    if all_results and success_count == len(all_results):
        outcome = AGG_OUTCOME_SUCCESS
        ok = True
    elif skipped_count == len(all_results) and all_results:
        outcome = AGG_OUTCOME_ALL_SKIPPED
        ok = False
    elif success_count or unchanged_count or skipped_count:
        outcome = AGG_OUTCOME_PARTIAL_SUCCESS
        ok = False
    else:
        outcome = AGG_OUTCOME_FAILED
        ok = False
    return {
        "ok": ok,
        "outcome": outcome,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "eligible_count": len(eligible),
        "skipped_count": skipped_count,
        "batch_count": len(batches),
        "batch_size": ROTATE_ALL_BATCH_SIZE,
        "batch_delay_seconds": ROTATE_ALL_BATCH_DELAY_SECONDS,
        "success_count": success_count,
        "unchanged_count": unchanged_count,
        "failure_count": failure_count,
        "timed_out_count": timed_out_count,
        "cooldown_count": cooldown_count,
        "results": all_results,
    }


# --------------------------------------------------------------------------- #
# Background loops
# --------------------------------------------------------------------------- #

def poll_loop():
    log(f"poller started, interval={POLL_INTERVAL}s")
    while True:
        refresh_instances()
        sleep(POLL_INTERVAL)


def auto_rotate_loop():
    log(f"auto-rotate every {AUTO_ROTATE}s")
    while True:
        sleep(AUTO_ROTATE)
        log(f"auto-rotate: {rotate_one_random()}")


# --------------------------------------------------------------------------- #
# Metrics + dashboard rendering
# --------------------------------------------------------------------------- #

def render_metrics() -> str:
    snap = STATE.snapshot()
    lines = [
        "# HELP chamosel_instances_total Number of gluetun instances in the pool.",
        "# TYPE chamosel_instances_total gauge",
        f"chamosel_instances_total {snap['count']}",
        "# HELP chamosel_instances_healthy Number of healthy instances.",
        "# TYPE chamosel_instances_healthy gauge",
        f"chamosel_instances_healthy {snap['healthy']}",
        "# HELP chamosel_pool_status Pool aggregate status label (1=current status).",
        "# TYPE chamosel_pool_status gauge",
        "# HELP chamosel_pool_degraded_reason Pool degraded reason labels (1=active reason).",
        "# TYPE chamosel_pool_degraded_reason gauge",
        "# HELP chamosel_state_fresh Whether every instance has been live-refreshed since controller start.",
        "# TYPE chamosel_state_fresh gauge",
        f"chamosel_state_fresh {1 if snap.get('state_fresh') else 0}",
        "# HELP chamosel_duplicate_ip_repair_in_flight Number of duplicate-IP repair rotations in flight.",
        "# TYPE chamosel_duplicate_ip_repair_in_flight gauge",
        f"chamosel_duplicate_ip_repair_in_flight {len((snap.get('duplicate_repair') or {}).get('in_flight') or [])}",
        "# HELP chamosel_duplicate_ip_repair_scheduled_total Total duplicate-IP repair rotations scheduled.",
        "# TYPE chamosel_duplicate_ip_repair_scheduled_total counter",
        f"chamosel_duplicate_ip_repair_scheduled_total {(snap.get('duplicate_repair') or {}).get('scheduled_total') or 0}",
        "# HELP chamosel_rotations_total Total successful rotations.",
        "# TYPE chamosel_rotations_total counter",
        f"chamosel_rotations_total {snap['rotations_total']}",
        "# HELP chamosel_rotation_errors_total Total failed rotations.",
        "# TYPE chamosel_rotation_errors_total counter",
        f"chamosel_rotation_errors_total {snap['rotation_errors_total']}",
        "# HELP chamosel_rotation_errors_by_outcome_total Failed rotations by outcome.",
        "# TYPE chamosel_rotation_errors_by_outcome_total counter",
        "# HELP chamosel_instance_healthy Per-instance health (1=healthy).",
        "# TYPE chamosel_instance_healthy gauge",
        "# HELP chamosel_instance_status Per-instance status label (1=current status).",
        "# TYPE chamosel_instance_status gauge",
        "# HELP chamosel_instance_rotations_total Per-instance rotation count.",
        "# TYPE chamosel_instance_rotations_total counter",
        "# HELP chamosel_instance_rotation_errors_by_outcome_total Per-instance failed rotations by outcome.",
        "# TYPE chamosel_instance_rotation_errors_by_outcome_total counter",
        "# HELP chamosel_instance_rotation_outcome Per-instance latest rotation outcome label.",
        "# TYPE chamosel_instance_rotation_outcome gauge",
        "# HELP chamosel_instance_rotation_cooldown_active Per-instance active rotation cooldown.",
        "# TYPE chamosel_instance_rotation_cooldown_active gauge",
        "# HELP chamosel_instance_rotation_cooldown_remaining_seconds Per-instance rotation cooldown remaining seconds.",
        "# TYPE chamosel_instance_rotation_cooldown_remaining_seconds gauge",
        "# HELP chamosel_instance_egress_state_fresh Per-instance verified proxy egress IP freshness.",
        "# TYPE chamosel_instance_egress_state_fresh gauge",
        "# HELP chamosel_instance_public_ip_mismatch Per-instance mismatch between gluetun public IP and verified proxy IP.",
        "# TYPE chamosel_instance_public_ip_mismatch gauge",
    ]
    for outcome, value in snap.get("rotation_errors_by_outcome", {}).items():
        lines.append(f'chamosel_rotation_errors_by_outcome_total{{outcome="{outcome}"}} {value}')
    for status in (POOL_STATUS_HEALTHY, POOL_STATUS_DEGRADED, POOL_STATUS_DOWN):
        lines.append(f'chamosel_pool_status{{status="{status}"}} {1 if snap.get("pool_status") == status else 0}')
    for reason in snap.get("degraded_reasons", []):
        lines.append(f'chamosel_pool_degraded_reason{{reason="{reason}"}} 1')
    for s in snap["instances"]:
        lines.append(f'chamosel_instance_healthy{{instance="{s["name"]}"}} {1 if s["healthy"] else 0}')
        lines.append(f'chamosel_instance_status{{instance="{s["name"]}",status="{s["status"]}"}} 1')
    for s in snap["instances"]:
        lines.append(f'chamosel_instance_rotations_total{{instance="{s["name"]}"}} {s["rotations"]}')
        for outcome, value in s.get("rotation_errors_by_outcome", {}).items():
            lines.append(
                f'chamosel_instance_rotation_errors_by_outcome_total'
                f'{{instance="{s["name"]}",outcome="{outcome}"}} {value}'
            )
        if s.get("last_rotation_outcome"):
            lines.append(
                f'chamosel_instance_rotation_outcome'
                f'{{instance="{s["name"]}",outcome="{s["last_rotation_outcome"]}"}} 1'
            )
        remaining = s.get("cooldown_remaining_seconds") or 0
        lines.append(f'chamosel_instance_rotation_cooldown_active{{instance="{s["name"]}"}} {1 if remaining > 0 else 0}')
        lines.append(f'chamosel_instance_rotation_cooldown_remaining_seconds{{instance="{s["name"]}"}} {remaining}')
        lines.append(f'chamosel_instance_egress_state_fresh{{instance="{s["name"]}"}} {1 if s.get("egress_state_fresh") else 0}')
        lines.append(f'chamosel_instance_public_ip_mismatch{{instance="{s["name"]}"}} {1 if s.get("public_ip_mismatch") else 0}')
    return "\n".join(lines) + "\n"


def render_login() -> str:
    cookie_name = quote(CONTROLLER_AUTH_COOKIE)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>chamosel auth</title>
<style>
  body{{font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:#0b0f19;color:#e5e7eb;margin:0;padding:24px}}
  main{{max-width:520px;margin:12vh auto;background:#111827;border:1px solid #1f2937;border-radius:10px;padding:24px}}
  h1{{font-size:18px;margin:0 0 8px}} p{{color:#9ca3af;margin:0 0 18px}}
  label{{display:block;color:#9ca3af;font-size:12px;text-transform:uppercase;margin-bottom:6px}}
  input{{box-sizing:border-box;width:100%;background:#020617;color:#e5e7eb;border:1px solid #334155;border-radius:8px;padding:10px 12px;font:inherit}}
  button{{margin-top:12px;background:#2563eb;color:#fff;border:0;border-radius:8px;padding:9px 14px;cursor:pointer;font:inherit}}
  button:hover{{background:#1d4ed8}} .err{{color:#f87171;margin-top:12px;display:none}}
</style></head><body>
<main>
  <h1>chamosel dashboard</h1>
  <p>Controller auth is enabled. Enter the controller token from your local secret file.</p>
  <form id="auth-form">
    <label for="token">Controller token</label>
    <input id="token" name="token" type="password" autocomplete="current-password" autofocus>
    <button type="submit">Unlock dashboard</button>
    <div class="err" id="err">Token was not accepted.</div>
  </form>
</main>
<script>
const cookieName = "{cookie_name}";
document.getElementById("auth-form").addEventListener("submit", async (event) => {{
  event.preventDefault();
  const token = document.getElementById("token").value.trim();
  if (!token) return;
  document.cookie = `${{cookieName}}=${{encodeURIComponent(token)}}; path=/; SameSite=Strict`;
  const response = await fetch("/pool", {{headers: {{"X-Chamosel-Auth": token}}}});
  if (response.ok) {{
    location.reload();
  }} else {{
    document.cookie = `${{cookieName}}=; path=/; SameSite=Strict; max-age=0`;
    document.getElementById("err").style.display = "block";
  }}
}});
</script></body></html>"""


def render_dashboard() -> str:
    snap = STATE.snapshot()
    now = time.time()
    rows = []
    pool_status = snap.get("pool_status", POOL_STATUS_DOWN)
    status_color = {
        POOL_STATUS_HEALTHY: "#22c55e",
        POOL_STATUS_DEGRADED: "#f59e0b",
        POOL_STATUS_DOWN: "#ef4444",
    }.get(pool_status, "#9ca3af")
    degraded = ", ".join(snap.get("degraded_reasons") or []) or "-"
    for s in snap["instances"]:
        dot = "#22c55e" if s["healthy"] else "#ef4444"
        last_rot = "never" if not s["last_rotated"] else f"{int(now - s['last_rotated'])}s ago"
        hist = ", ".join(s["ip_history"][:5]) or "-"
        state = s.get("status") or ("healthy" if s["healthy"] else "down")
        outcome = s.get("last_rotation_outcome") or "-"
        mismatch = "yes" if s.get("public_ip_mismatch") else "no"
        cooldown = s.get("cooldown_remaining_seconds") or 0
        cooldown_text = f"{cooldown:.0f}s ({s.get('cooldown_reason')})" if cooldown > 0 else "-"
        rows.append(
            f'<tr><td><span class="dot" style="background:{dot}"></span>{s["name"]}</td>'
            f'<td>{state}</td>'
            f'<td>{"yes" if s.get("state_fresh") else "no"}</td>'
            f'<td class="ip">{s["public_ip"] or "-"}</td>'
            f'<td class="ip">{s.get("verified_proxy_ip") or "-"}</td>'
            f'<td>{mismatch}</td>'
            f'<td>{s["rotations"]}</td><td>{last_rot}</td>'
            f'<td>{outcome}</td><td>{cooldown_text}</td>'
            f'<td class="hist">{hist}</td></tr>'
        )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="5"><title>chamosel</title>
<style>
  body{{font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:#0b0f19;color:#e5e7eb;margin:0;padding:24px}}
  h1{{font-size:18px;margin:0 0 4px}} .sub{{color:#9ca3af;margin:0 0 20px}}
  .cards{{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}}
  .card{{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:12px 16px;min-width:120px}}
  .card .n{{font-size:24px;font-weight:600}} .card .l{{color:#9ca3af;font-size:12px}}
  .status{{color:{status_color}}}
  table{{width:100%;border-collapse:collapse;background:#111827;border-radius:10px;overflow:hidden}}
  th,td{{text-align:left;padding:10px 14px;border-bottom:1px solid #1f2937}}
  th{{color:#9ca3af;font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
  .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px}}
  .ip{{color:#60a5fa}} .hist{{color:#6b7280;font-size:12px}}
  button{{background:#2563eb;color:#fff;border:0;border-radius:8px;padding:8px 14px;cursor:pointer;font:inherit}}
  button:hover{{background:#1d4ed8}}
</style></head><body>
<h1>chamosel</h1><p class="sub">spin the wheel, change the skin · auto-refresh 5s</p>
<div class="cards">
  <div class="card"><div class="n">{snap['count']}</div><div class="l">instances</div></div>
  <div class="card"><div class="n">{snap['healthy']}</div><div class="l">healthy</div></div>
  <div class="card"><div class="n status">{pool_status}</div><div class="l">pool</div></div>
  <div class="card"><div class="n">{"yes" if snap.get("state_fresh") else "no"}</div><div class="l">fresh</div></div>
  <div class="card"><div class="n">{snap['rotations_total']}</div><div class="l">rotations</div></div>
  <div class="card"><div class="n">{snap['rotation_errors_total']}</div><div class="l">rot. errors</div></div>
</div>
<p class="sub">degraded reasons: {degraded}</p>
<p><button onclick="fetch('/rotate',{{method:'POST'}}).then(()=>setTimeout(()=>location.reload(),1200))">Rotate one</button></p>
<table>
  <tr><th>instance</th><th>state</th><th>fresh</th><th>public ip</th><th>verified proxy ip</th><th>mismatch</th><th>rotations</th><th>last rotated</th><th>outcome</th><th>cooldown</th><th>recent ips</th></tr>
  {''.join(rows)}
</table></body></html>"""


# --------------------------------------------------------------------------- #
# HTTP server
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload: dict):
        self._raw(code, json.dumps(payload).encode(), "application/json")

    def _raw(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log(f"{self.address_string()} {fmt % args}")

    def _require_auth(self) -> bool:
        if controller_auth_valid(getattr(self, "headers", {})):
            return True
        self._json(401, {"error": "unauthorized"})
        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"status": "ok", "instances": len(INSTANCES)})
        elif parsed.path == "/":
            if not controller_auth_valid(getattr(self, "headers", {})):
                self._raw(401, render_login().encode(), "text/html; charset=utf-8")
                return
            self._raw(200, render_dashboard().encode(), "text/html; charset=utf-8")
        elif parsed.path == "/metrics":
            if not self._require_auth():
                return
            self._raw(200, render_metrics().encode(), "text/plain; version=0.0.4")
        elif parsed.path == "/pool":
            if not self._require_auth():
                return
            if parse_qs(parsed.query).get("fresh"):
                refresh_instances(verify_egress=EGRESS_VERIFY_ON_FRESH)
            self._json(200, STATE.snapshot())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._require_auth():
            return
        if not INSTANCES:
            return self._json(503, {"error": "no instances configured"})
        if self.path == "/rotate":
            self._json(200, rotate_one_random())
        elif self.path == "/rotate/all":
            self._json(200, rotate_all())
        elif self.path == "/repair/duplicate-ip":
            self._json(200, repair_duplicate_ip_once())
        elif self.path.startswith("/rotate/"):
            self._json(200, rotate_instance(self.path[len("/rotate/"):], force=True))
        else:
            self._json(404, {"error": "not found"})


def main():
    log(
        f"instances={INSTANCES} listen={LISTEN_PORT} "
        f"gluetun_auth={'on' if API_KEY else 'OFF'} "
        f"controller_auth={'on' if controller_auth_required() else 'OFF'}"
    )
    if not API_KEY:
        log("WARNING: GLUETUN_API_KEY not set; gluetun v3.40+ requires auth and will 401")
    if CONTROLLER_AUTH_ENABLED and not CONTROLLER_AUTH_TOKEN:
        log("WARNING: CONTROLLER_AUTH_ENABLED=true but CONTROLLER_AUTH_TOKEN is empty; protected routes will reject all requests")
    threading.Thread(target=poll_loop, daemon=True).start()
    if AUTO_ROTATE > 0:
        threading.Thread(target=auto_rotate_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
