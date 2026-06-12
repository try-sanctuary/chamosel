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
  POST /rotate/all               rotate every instance (sequential)
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

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
POLL_WORKERS = int(os.environ.get("POLL_WORKERS", str(max(1, min(16, len(INSTANCES) or 1)))))

STATUS_HEALTHY = "healthy"
STATUS_RECONNECTING = "reconnecting"
STATUS_UNREACHABLE = "unreachable"
STATUS_UNAUTHORIZED = "unauthorized"
STATUS_UNSUPPORTED_CONTROL = "unsupported_control"

OUTCOME_SUCCESS = "success"
OUTCOME_COOLDOWN = "cooldown"
OUTCOME_UNKNOWN_INSTANCE = "unknown_instance"
OUTCOME_UNAUTHORIZED = "unauthorized"
OUTCOME_UNSUPPORTED_CONTROL = "unsupported_control"
OUTCOME_CONTROL_UNREACHABLE = "control_unreachable"
OUTCOME_COMMAND_ERROR = "command_error"
OUTCOME_RECOVERY_TIMEOUT = "recovery_timeout"

# New control API (gluetun v3.41+) first, then legacy (v3.40 and older).
STATUS_PATHS = ("/v1/vpn/status", "/v1/openvpn/status")


def log(msg: str):
    print(f"[chamosel] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def sleep(seconds: float):
    time.sleep(seconds)


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
                "last_error": None,
                "public_ip": None,
                "ip_history": [],          # most-recent-first
                "rotations": 0,
                "rotation_errors": 0,
                "last_rotated": 0.0,
                "last_seen": 0.0,
                "last_rotation_outcome": None,
                "status_path": None,       # cached working control path
                "rotation_errors_by_outcome": {},
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
                              "rotation_errors_by_outcome"):
                        if k in s:
                            self.inst[name][k] = s[k]
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
            s["last_error"] = error
            s["last_seen"] = time.time()
            if ip and ip != s["public_ip"]:
                s["public_ip"] = ip
                if not s["ip_history"] or s["ip_history"][0] != ip:
                    s["ip_history"].insert(0, ip)
                    del s["ip_history"][IP_HISTORY_MAX:]
            self._save_locked()

    def record_rotation(self, name: str, outcome: str):
        with self.lock:
            s = self.inst[name]
            s["last_rotation_outcome"] = outcome
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

    def mark_rotation_outcome(self, name: str, outcome: str):
        with self.lock:
            self.inst[name]["last_rotation_outcome"] = outcome
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
            s["last_error"] = error
            s["last_seen"] = time.time()
            self._save_locked()

    def cooldown_remaining(self, name: str) -> float:
        with self.lock:
            elapsed = time.time() - self.inst[name]["last_rotated"]
            return max(0.0, ROTATE_COOLDOWN - elapsed)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "count": len(INSTANCES),
                "healthy": sum(1 for s in self.inst.values() if s["healthy"]),
                "rotations_total": self.rotations_total,
                "rotation_errors_total": self.rotation_errors_total,
                "rotation_errors_by_outcome": dict(self.rotation_errors_by_outcome),
                "instances": [dict(s) for s in self.inst.values()],
            }


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


def refresh_instance(instance: str) -> dict:
    healthy, status, error = read_health(instance)
    ip = get_public_ip(instance) if healthy else None
    STATE.update_health(instance, healthy, ip, status=status, error=error)
    return {"instance": instance, "healthy": healthy, "status": status, "error": error, "public_ip": ip}


def refresh_instances(instances=None):
    instances = list(instances or INSTANCES)
    if not instances:
        return []
    workers = max(1, min(POLL_WORKERS, len(instances)))
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(refresh_instance, inst): inst for inst in instances}
        for fut in as_completed(future_map):
            inst = future_map[fut]
            try:
                results.append(fut.result())
            except Exception as e:
                STATE.update_health(inst, False, None, status=STATUS_UNREACHABLE, error=str(e))
                results.append({"instance": inst, "healthy": False, "status": STATUS_UNREACHABLE, "error": str(e)})
    return results


def wait_for_recovery(instance: str, old_ip, timeout: int = ROTATION_RECOVERY_TIMEOUT) -> tuple[bool, str | None]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        h = is_healthy(instance)
        if h:
            new_ip = get_public_ip(instance)
            if new_ip and new_ip != old_ip:
                STATE.update_health(instance, True, new_ip, status=STATUS_HEALTHY)
                return True, new_ip
        sleep(1)
    return False, None


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


def rotate_instance(instance: str, force: bool = False) -> dict:
    """Graceful rotation: PUT status stopped, then running. New server, no
    container restart. HAProxy drops the instance via health checks while it
    reconnects and re-adds it on recovery."""
    started_at = time.monotonic()
    if instance not in INSTANCES:
        return rotation_response(instance, False, OUTCOME_UNKNOWN_INSTANCE, started_at,
                                 message="unknown instance")
    if not force:
        cd = STATE.cooldown_remaining(instance)
        if cd > 0:
            STATE.mark_rotation_outcome(instance, OUTCOME_COOLDOWN)
            return rotation_response(instance, False, OUTCOME_COOLDOWN, started_at,
                                     message=f"cooldown: {cd:.0f}s remaining")
    path = detect_status_path(instance)
    if not path:
        current = next((s for s in STATE.snapshot()["instances"] if s["name"] == instance), {})
        outcome = status_to_rotation_outcome(current.get("status", STATUS_UNREACHABLE))
        STATE.record_rotation(instance, outcome)
        return rotation_response(instance, False, outcome, started_at,
                                 message="control server unreachable/unauthorized")
    old_ip = STATE.inst[instance]["public_ip"] or get_public_ip(instance)
    try:
        _ctrl("PUT", instance, path, {"status": "stopped"})
        sleep(1)
        _ctrl("PUT", instance, path, {"status": "running"})
    except Exception as e:
        STATE.record_rotation(instance, OUTCOME_COMMAND_ERROR)
        return rotation_response(instance, False, OUTCOME_COMMAND_ERROR, started_at,
                                 old_ip=old_ip, message=str(e))
    STATE.update_health(instance, False, old_ip, status=STATUS_RECONNECTING)
    recovered, new_ip = wait_for_recovery(instance, old_ip)
    if not recovered:
        STATE.record_rotation(instance, OUTCOME_RECOVERY_TIMEOUT)
        return rotation_response(
            instance,
            False,
            OUTCOME_RECOVERY_TIMEOUT,
            started_at,
            old_ip=old_ip,
            new_ip=new_ip,
            message=f"VPN did not recover with a new IP within {ROTATION_RECOVERY_TIMEOUT}s",
        )
    STATE.record_rotation(instance, OUTCOME_SUCCESS)
    log(f"rotated {instance} ({old_ip} -> {new_ip})")
    return rotation_response(instance, True, OUTCOME_SUCCESS, started_at,
                             old_ip=old_ip, new_ip=new_ip,
                             message="rotation recovered with a changed public IP")


def rotate_one_random(force: bool = False) -> dict:
    """Pick an instance not in cooldown; prefer ones rotated longest ago."""
    candidates = [n for n in INSTANCES if force or STATE.cooldown_remaining(n) == 0]
    if not candidates:
        return rotation_response(None, False, OUTCOME_COOLDOWN, time.monotonic(),
                                 message="all instances in cooldown")
    candidates.sort(key=lambda n: STATE.inst[n]["last_rotated"])
    return rotate_instance(candidates[0], force=force)


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
    ]
    for outcome, value in snap.get("rotation_errors_by_outcome", {}).items():
        lines.append(f'chamosel_rotation_errors_by_outcome_total{{outcome="{outcome}"}} {value}')
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
    return "\n".join(lines) + "\n"


def render_dashboard() -> str:
    snap = STATE.snapshot()
    now = time.time()
    rows = []
    for s in snap["instances"]:
        dot = "#22c55e" if s["healthy"] else "#ef4444"
        last_rot = "never" if not s["last_rotated"] else f"{int(now - s['last_rotated'])}s ago"
        hist = ", ".join(s["ip_history"][:5]) or "-"
        state = s.get("status") or ("healthy" if s["healthy"] else "down")
        rows.append(
            f'<tr><td><span class="dot" style="background:{dot}"></span>{s["name"]}</td>'
            f'<td>{state}</td>'
            f'<td class="ip">{s["public_ip"] or "-"}</td>'
            f'<td>{s["rotations"]}</td><td>{last_rot}</td>'
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
  <div class="card"><div class="n">{snap['rotations_total']}</div><div class="l">rotations</div></div>
  <div class="card"><div class="n">{snap['rotation_errors_total']}</div><div class="l">rot. errors</div></div>
</div>
<p><button onclick="fetch('/rotate',{{method:'POST'}}).then(()=>setTimeout(()=>location.reload(),1200))">Rotate one</button></p>
<table>
  <tr><th>instance</th><th>state</th><th>public ip</th><th>rotations</th><th>last rotated</th><th>recent ips</th></tr>
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

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._raw(200, render_dashboard().encode(), "text/html; charset=utf-8")
        elif parsed.path == "/health":
            self._json(200, {"status": "ok", "instances": len(INSTANCES)})
        elif parsed.path == "/metrics":
            self._raw(200, render_metrics().encode(), "text/plain; version=0.0.4")
        elif parsed.path == "/pool":
            if parse_qs(parsed.query).get("fresh"):
                refresh_instances()
            self._json(200, STATE.snapshot())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if not INSTANCES:
            return self._json(503, {"error": "no instances configured"})
        if self.path == "/rotate":
            self._json(200, rotate_one_random())
        elif self.path == "/rotate/all":
            self._json(200, {"results": [rotate_instance(i, force=True) for i in INSTANCES]})
        elif self.path.startswith("/rotate/"):
            self._json(200, rotate_instance(self.path[len("/rotate/"):], force=True))
        else:
            self._json(404, {"error": "not found"})


def main():
    log(f"instances={INSTANCES} listen={LISTEN_PORT} auth={'on' if API_KEY else 'OFF'}")
    if not API_KEY:
        log("WARNING: GLUETUN_API_KEY not set; gluetun v3.40+ requires auth and will 401")
    threading.Thread(target=poll_loop, daemon=True).start()
    if AUTO_ROTATE > 0:
        threading.Thread(target=auto_rotate_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
