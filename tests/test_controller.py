import importlib.util
import os
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_controller(tmpdir, instances="vpn_0,vpn_1", env_overrides=None):
    old_env = os.environ.copy()
    env = {
        "INSTANCES": instances,
        "STATE_FILE": str(Path(tmpdir) / "state.json"),
        "GLUETUN_API_KEY": "secret",
        "POLL_WORKERS": "8",
        "ROTATION_RECOVERY_TIMEOUT": "1",
        "ROTATE_ALL_BATCH_SIZE": "2",
        "ROTATE_ALL_BATCH_DELAY_SECONDS": "0",
    }
    if env_overrides:
        env.update(env_overrides)
    os.environ.update(env)
    spec = importlib.util.spec_from_file_location(
        f"controller_under_test_{time.time_ns()}",
        ROOT / "controller" / "controller.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    os.environ.clear()
    os.environ.update(old_env)
    return module


def http_error(code):
    return urllib.error.HTTPError("http://example.test", code, "boom", {}, None)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctrl = load_controller(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stale_status_path_is_re_detected_after_404(self):
        calls = []
        vpn_status_calls = {"count": 0}

        def fake_ctrl(method, instance, path, body=None):
            calls.append((method, path))
            if path == "/v1/vpn/status":
                vpn_status_calls["count"] += 1
                if vpn_status_calls["count"] <= 2:
                    return {"status": "running"}
                raise http_error(404)
            if path == "/v1/openvpn/status":
                return {"status": "running"}
            raise AssertionError(path)

        self.ctrl._ctrl = fake_ctrl

        self.assertTrue(self.ctrl.is_healthy("vpn_0"))
        self.assertEqual("/v1/vpn/status", self.ctrl.STATE.get_status_path("vpn_0"))

        self.assertTrue(self.ctrl.is_healthy("vpn_0"))
        self.assertEqual("/v1/openvpn/status", self.ctrl.STATE.get_status_path("vpn_0"))

    def test_unauthorized_status_does_not_retry_alternate_paths(self):
        calls = []

        def fake_ctrl(method, instance, path, body=None):
            calls.append(path)
            raise http_error(401)

        self.ctrl._ctrl = fake_ctrl

        self.assertFalse(self.ctrl.is_healthy("vpn_0"))
        state = self.ctrl.STATE.snapshot()["instances"][0]
        self.assertEqual(self.ctrl.STATUS_UNAUTHORIZED, state["status"])
        self.assertEqual(["/v1/vpn/status"], calls)

    def test_unsupported_control_sets_operator_visible_error(self):
        def fake_ctrl(method, instance, path, body=None):
            raise http_error(404)

        self.ctrl._ctrl = fake_ctrl

        self.assertFalse(self.ctrl.is_healthy("vpn_0"))
        state = self.ctrl.STATE.snapshot()["instances"][0]
        self.assertEqual(self.ctrl.STATUS_UNSUPPORTED_CONTROL, state["status"])
        self.assertIn("supported status endpoint", state["last_error"])

    def test_polling_refreshes_instances_in_parallel(self):
        self.ctrl.INSTANCES[:] = [f"vpn_{i}" for i in range(4)]
        self.ctrl.POLL_WORKERS = 4
        self.ctrl.STATE = self.ctrl.State()

        def slow_refresh(instance, verify_egress=False, force_egress=False):
            time.sleep(0.2)
            return {"instance": instance}

        self.ctrl.refresh_instance = slow_refresh
        started = time.monotonic()
        results = self.ctrl.refresh_instances(self.ctrl.INSTANCES)
        elapsed = time.monotonic() - started

        self.assertEqual(4, len(results))
        self.assertLess(elapsed, 0.55)

    def test_pool_fresh_uses_bounded_refresh_helper(self):
        called = {"refresh": False}
        captured = {}

        def fake_refresh(verify_egress=False, force_egress=False):
            called["refresh"] = True
            captured["verify_egress"] = verify_egress
            self.ctrl.STATE.update_health("vpn_0", True, "9.9.9.9", status=self.ctrl.STATUS_HEALTHY)

        handler = self.ctrl.Handler.__new__(self.ctrl.Handler)
        handler.path = "/pool?fresh=1"
        handler._json = lambda code, payload: captured.update({"code": code, "payload": payload})
        self.ctrl.refresh_instances = fake_refresh

        handler.do_GET()

        self.assertTrue(called["refresh"])
        self.assertTrue(captured["verify_egress"])
        self.assertEqual(200, captured["code"])
        self.assertEqual("9.9.9.9", captured["payload"]["instances"][0]["public_ip"])

    def test_controller_auth_rejects_protected_get_without_token(self):
        ctrl = load_controller(
            self.tmp.name,
            env_overrides={"CONTROLLER_AUTH_ENABLED": "true", "CONTROLLER_AUTH_TOKEN": "controller-token"},
        )
        called = {"refresh": False}
        captured = {}

        handler = ctrl.Handler.__new__(ctrl.Handler)
        handler.path = "/pool?fresh=1"
        handler.headers = {}
        handler._json = lambda code, payload: captured.update({"code": code, "payload": payload})
        ctrl.refresh_instances = lambda *args, **kwargs: called.update({"refresh": True})

        handler.do_GET()

        self.assertEqual(401, captured["code"])
        self.assertEqual({"error": "unauthorized"}, captured["payload"])
        self.assertFalse(called["refresh"])

    def test_controller_auth_allows_protected_get_with_token(self):
        ctrl = load_controller(
            self.tmp.name,
            env_overrides={"CONTROLLER_AUTH_ENABLED": "true", "CONTROLLER_AUTH_TOKEN": "controller-token"},
        )
        captured = {}

        handler = ctrl.Handler.__new__(ctrl.Handler)
        handler.path = "/pool"
        handler.headers = {"X-Chamosel-Auth": "controller-token"}
        handler._json = lambda code, payload: captured.update({"code": code, "payload": payload})

        handler.do_GET()

        self.assertEqual(200, captured["code"])
        self.assertIn("instances", captured["payload"])

    def test_controller_health_remains_public_when_auth_enabled(self):
        ctrl = load_controller(
            self.tmp.name,
            env_overrides={"CONTROLLER_AUTH_ENABLED": "true", "CONTROLLER_AUTH_TOKEN": "controller-token"},
        )
        captured = {}

        handler = ctrl.Handler.__new__(ctrl.Handler)
        handler.path = "/health"
        handler.headers = {}
        handler._json = lambda code, payload: captured.update({"code": code, "payload": payload})

        handler.do_GET()

        self.assertEqual(200, captured["code"])
        self.assertEqual("ok", captured["payload"]["status"])

    def test_controller_auth_rejects_protected_post_without_token(self):
        ctrl = load_controller(
            self.tmp.name,
            env_overrides={"CONTROLLER_AUTH_ENABLED": "true", "CONTROLLER_AUTH_TOKEN": "controller-token"},
        )
        captured = {}
        calls = []

        handler = ctrl.Handler.__new__(ctrl.Handler)
        handler.path = "/rotate"
        handler.headers = {}
        handler._json = lambda code, payload: captured.update({"code": code, "payload": payload})
        ctrl.rotate_one_random = lambda *args, **kwargs: calls.append("rotate") or {"ok": True}

        handler.do_POST()

        self.assertEqual(401, captured["code"])
        self.assertEqual([], calls)

    def test_rotation_success_waits_for_recovered_new_ip(self):
        commands = []
        health_calls = {"count": 0}

        def fake_ctrl(method, instance, path, body=None):
            if method == "GET" and path in self.ctrl.STATUS_PATHS:
                return {"status": "running"}
            if method == "PUT":
                commands.append(body["status"])
                return {}
            raise AssertionError((method, path))

        def fake_healthy(instance):
            health_calls["count"] += 1
            return health_calls["count"] >= 2

        self.ctrl._ctrl = fake_ctrl
        self.ctrl.get_public_ip = lambda instance: "2.2.2.2" if health_calls["count"] >= 2 else "1.1.1.1"
        self.ctrl.is_healthy = fake_healthy
        self.ctrl.refresh_verified_proxy_ip = lambda instance, force=False: {"verified_proxy_ip": "2.2.2.2"}
        self.ctrl.sleep = lambda seconds: None

        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        result = self.ctrl.rotate_instance("vpn_0", force=True)

        self.assertEqual(["stopped", "running"], commands)
        self.assertTrue(result["ok"])
        self.assertEqual(self.ctrl.OUTCOME_SUCCESS, result["outcome"])
        self.assertIn("elapsed_seconds", result)
        self.assertIn("message", result)
        self.assertEqual("2.2.2.2", result["new_ip"])
        self.assertEqual(1, self.ctrl.STATE.snapshot()["rotations_total"])

    def test_rotation_timeout_is_error_not_success(self):
        def fake_ctrl(method, instance, path, body=None):
            if method == "GET" and path in self.ctrl.STATUS_PATHS:
                return {"status": "running"}
            if method == "PUT":
                return {}
            raise AssertionError((method, path))

        self.ctrl._ctrl = fake_ctrl
        self.ctrl.is_healthy = lambda instance: False
        self.ctrl.sleep = lambda seconds: None

        result = self.ctrl.rotate_instance("vpn_0", force=True)

        snap = self.ctrl.STATE.snapshot()
        self.assertFalse(result["ok"])
        self.assertEqual(self.ctrl.OUTCOME_RECOVERY_TIMEOUT, result["outcome"])
        self.assertEqual(0, snap["rotations_total"])
        self.assertEqual(1, snap["rotation_errors_total"])
        self.assertEqual(1, snap["rotation_errors_by_outcome"][self.ctrl.OUTCOME_RECOVERY_TIMEOUT])

    def test_rotation_command_error_is_not_success(self):
        def fake_ctrl(method, instance, path, body=None):
            if method == "GET" and path in self.ctrl.STATUS_PATHS:
                return {"status": "running"}
            if method == "PUT":
                raise RuntimeError("boom")
            raise AssertionError((method, path))

        self.ctrl._ctrl = fake_ctrl

        result = self.ctrl.rotate_instance("vpn_0", force=True)
        snap = self.ctrl.STATE.snapshot()

        self.assertFalse(result["ok"])
        self.assertEqual(self.ctrl.OUTCOME_COMMAND_ERROR, result["outcome"])
        self.assertEqual(0, snap["rotations_total"])
        self.assertEqual(1, snap["rotation_errors_by_outcome"][self.ctrl.OUTCOME_COMMAND_ERROR])

    def test_unknown_instance_does_not_change_counters(self):
        result = self.ctrl.rotate_instance("missing", force=True)
        snap = self.ctrl.STATE.snapshot()

        self.assertFalse(result["ok"])
        self.assertEqual(self.ctrl.OUTCOME_UNKNOWN_INSTANCE, result["outcome"])
        self.assertEqual(0, snap["rotations_total"])
        self.assertEqual(0, snap["rotation_errors_total"])

    def test_rotation_metrics_expose_success_and_failure_outcome_labels(self):
        self.ctrl.STATE.record_rotation("vpn_0", self.ctrl.OUTCOME_SUCCESS)
        self.ctrl.STATE.record_rotation("vpn_1", self.ctrl.OUTCOME_RECOVERY_TIMEOUT)

        metrics = self.ctrl.render_metrics()

        self.assertIn("chamosel_rotations_total 1", metrics)
        self.assertIn("chamosel_rotation_errors_total 1", metrics)
        self.assertIn(
            'chamosel_rotation_errors_by_outcome_total{outcome="recovery_timeout"} 1',
            metrics,
        )

    def test_new_rotation_state_defaults_and_persistence(self):
        snap = self.ctrl.STATE.snapshot()
        state = snap["instances"][0]

        self.assertEqual(0.0, state["last_rotation_attempted"])
        self.assertIsNone(state["last_rotation_message"])
        self.assertIsNone(state["last_rotation_old_ip"])
        self.assertIsNone(state["last_rotation_new_ip"])
        self.assertEqual(0.0, state["cooldown_until"])
        self.assertEqual(0.0, state["cooldown_remaining_seconds"])
        self.assertIsNone(state["cooldown_reason"])
        self.assertEqual(0, state["forced_bypass_count"])
        self.assertFalse(state["state_fresh"])
        self.assertFalse(snap["state_fresh"])

        self.ctrl.STATE.start_cooldown("vpn_0", self.ctrl.OUTCOME_RECOVERY_TIMEOUT)
        self.ctrl.STATE.record_rotation(
            "vpn_0",
            self.ctrl.OUTCOME_RECOVERY_TIMEOUT,
            message="safe message",
            old_ip="1.1.1.1",
            new_ip=None,
        )

        reloaded = self.ctrl.State()
        persisted = reloaded.snapshot()["instances"][0]
        self.assertEqual(self.ctrl.OUTCOME_RECOVERY_TIMEOUT, persisted["last_rotation_outcome"])
        self.assertEqual("safe message", persisted["last_rotation_message"])
        self.assertEqual("1.1.1.1", persisted["last_rotation_old_ip"])
        self.assertGreater(persisted["cooldown_until"], time.time())
        self.assertEqual(self.ctrl.OUTCOME_RECOVERY_TIMEOUT, persisted["cooldown_reason"])
        self.assertFalse(persisted["state_fresh"])

    def test_loaded_state_is_stale_until_refreshed(self):
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_health("vpn_1", True, "2.2.2.2", status=self.ctrl.STATUS_HEALTHY)

        reloaded = self.ctrl.State()
        stale = reloaded.snapshot()
        self.assertFalse(stale["state_fresh"])
        self.assertIn(self.ctrl.DEGRADED_STALE_STATE, stale["degraded_reasons"])

        reloaded.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        reloaded.update_health("vpn_1", True, "2.2.2.2", status=self.ctrl.STATUS_HEALTHY)
        fresh = reloaded.snapshot()
        self.assertTrue(fresh["state_fresh"])
        self.assertNotIn(self.ctrl.DEGRADED_STALE_STATE, fresh["degraded_reasons"])

    def test_expired_failure_cooldown_is_not_active_after_restart(self):
        self.ctrl.STATE.start_cooldown("vpn_0", self.ctrl.OUTCOME_RECOVERY_TIMEOUT, duration=0)
        self.ctrl.STATE.record_rotation("vpn_0", self.ctrl.OUTCOME_RECOVERY_TIMEOUT)

        reloaded = self.ctrl.State()
        state = reloaded.snapshot()["instances"][0]

        self.assertEqual(0.0, state["cooldown_remaining_seconds"])
        self.assertIsNone(state["cooldown_reason"])
        self.assertEqual(0.0, state["cooldown_until"])

    def test_duplicate_public_ip_marks_pool_degraded(self):
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_health("vpn_1", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)

        snap = self.ctrl.STATE.snapshot()

        self.assertEqual(self.ctrl.POOL_STATUS_DEGRADED, snap["pool_status"])
        self.assertIn(self.ctrl.DEGRADED_DUPLICATE_PUBLIC_IP, snap["degraded_reasons"])

    def test_verified_proxy_ip_preferred_over_duplicate_public_ip(self):
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_health("vpn_1", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_verified_proxy_ip("vpn_0", "45.134.140.5")
        self.ctrl.STATE.update_verified_proxy_ip("vpn_1", "89.187.163.10")

        snap = self.ctrl.STATE.snapshot()

        self.assertEqual(self.ctrl.POOL_STATUS_DEGRADED, snap["pool_status"])
        self.assertIn(self.ctrl.DEGRADED_PUBLIC_IP_MISMATCH, snap["degraded_reasons"])
        self.assertNotIn(self.ctrl.DEGRADED_DUPLICATE_PUBLIC_IP, snap["degraded_reasons"])
        self.assertNotIn(self.ctrl.DEGRADED_VERIFIED_DUPLICATE_PROXY_IP, snap["degraded_reasons"])

    def test_duplicate_verified_proxy_ip_marks_pool_degraded(self):
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_health("vpn_1", True, "2.2.2.2", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_verified_proxy_ip("vpn_0", "45.134.140.5")
        self.ctrl.STATE.update_verified_proxy_ip("vpn_1", "45.134.140.5")

        snap = self.ctrl.STATE.snapshot()

        self.assertEqual(self.ctrl.POOL_STATUS_DEGRADED, snap["pool_status"])
        self.assertIn(self.ctrl.DEGRADED_VERIFIED_DUPLICATE_PROXY_IP, snap["degraded_reasons"])

    def test_failed_egress_probe_sets_error_and_degrades_pool(self):
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.probe_verified_proxy_ip = lambda instance: (None, "proxy refused")

        result = self.ctrl.refresh_verified_proxy_ip("vpn_0", force=True)
        snap = self.ctrl.STATE.snapshot()

        self.assertEqual("proxy refused", result["error"])
        self.assertEqual("proxy refused", snap["instances"][0]["verified_proxy_ip_error"])
        self.assertIn(self.ctrl.DEGRADED_EGRESS_VERIFICATION_FAILED, snap["degraded_reasons"])

    def test_refresh_verified_proxy_ip_uses_ttl_cache(self):
        calls = []
        self.ctrl.EGRESS_VERIFY_TTL = 120
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_verified_proxy_ip("vpn_0", "45.134.140.5")
        self.ctrl.probe_verified_proxy_ip = lambda instance: calls.append(instance) or ("89.187.163.10", None)

        cached = self.ctrl.refresh_verified_proxy_ip("vpn_0")
        self.assertTrue(cached["cached"])
        self.assertEqual([], calls)

        with self.ctrl.STATE.lock:
            self.ctrl.STATE.inst["vpn_0"]["verified_proxy_ip_seen_at"] = time.time() - 121
        refreshed = self.ctrl.refresh_verified_proxy_ip("vpn_0")

        self.assertEqual("89.187.163.10", refreshed["verified_proxy_ip"])
        self.assertEqual(["vpn_0"], calls)

    def test_extract_verified_proxy_ip_accepts_ifconfig_json(self):
        self.assertEqual("45.134.140.5", self.ctrl.extract_verified_proxy_ip({"ip": "45.134.140.5"}))

    def test_public_ip_mismatch_does_not_schedule_repair_when_verified_ips_unique(self):
        calls = []
        self.ctrl.rotate_instance = lambda instance, force=False: calls.append(instance) or {"ok": True}
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_health("vpn_1", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_verified_proxy_ip("vpn_0", "45.134.140.5")
        self.ctrl.STATE.update_verified_proxy_ip("vpn_1", "89.187.163.10")

        self.ctrl.maybe_schedule_duplicate_ip_repair()

        self.assertEqual([], calls)

    def test_duplicate_ip_repair_once_rotates_one_verified_duplicate(self):
        calls = []
        self.ctrl.rotate_instance = lambda instance, force=False: calls.append((instance, force)) or {
            "instance": instance,
            "ok": True,
            "outcome": self.ctrl.OUTCOME_SUCCESS,
        }
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_health("vpn_1", True, "2.2.2.2", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_verified_proxy_ip("vpn_0", "45.134.140.5")
        self.ctrl.STATE.update_verified_proxy_ip("vpn_1", "45.134.140.5")

        result = self.ctrl.repair_duplicate_ip_once()

        self.assertTrue(result["ok"])
        self.assertTrue(result["attempted"])
        self.assertEqual("vpn_1", result["target"])
        self.assertEqual([("vpn_1", False)], calls)
        self.assertEqual([], result["duplicate_repair"]["in_flight"])

    def test_duplicate_ip_repair_once_does_not_rotate_mismatch_only(self):
        calls = []
        self.ctrl.rotate_instance = lambda instance, force=False: calls.append((instance, force)) or {"ok": True}
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_health("vpn_1", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_verified_proxy_ip("vpn_0", "45.134.140.5")
        self.ctrl.STATE.update_verified_proxy_ip("vpn_1", "89.187.163.10")

        result = self.ctrl.repair_duplicate_ip_once()

        self.assertTrue(result["ok"])
        self.assertFalse(result["attempted"])
        self.assertEqual("no_duplicate_egress_ip", result["reason"])
        self.assertEqual([], calls)

    def test_repair_endpoint_requires_auth_and_returns_result(self):
        ctrl = load_controller(
            self.tmp.name,
            env_overrides={"CONTROLLER_AUTH_ENABLED": "true", "CONTROLLER_AUTH_TOKEN": "controller-token"},
        )
        captured = {}

        handler = ctrl.Handler.__new__(ctrl.Handler)
        handler.path = "/repair/duplicate-ip"
        handler.headers = {"X-Chamosel-Auth": "controller-token"}
        handler._json = lambda code, payload: captured.update({"code": code, "payload": payload})
        ctrl.repair_duplicate_ip_once = lambda: {"ok": True, "attempted": False, "outcome": "none"}

        handler.do_POST()

        self.assertEqual(200, captured["code"])
        self.assertEqual("none", captured["payload"]["outcome"])

    def test_duplicate_verified_proxy_ip_refresh_schedules_one_repair_rotation(self):
        calls = []

        class ImmediateThread:
            def __init__(self, target, args=(), daemon=None):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        original_thread = self.ctrl.threading.Thread
        try:
            self.ctrl.threading.Thread = ImmediateThread
            self.ctrl.rotate_instance = lambda instance, force=False: calls.append((instance, force)) or {
                "instance": instance,
                "ok": True,
                "outcome": self.ctrl.OUTCOME_SUCCESS,
            }
            self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
            self.ctrl.STATE.update_health("vpn_1", True, "2.2.2.2", status=self.ctrl.STATUS_HEALTHY)
            self.ctrl.STATE.update_verified_proxy_ip("vpn_0", "45.134.140.5")
            self.ctrl.STATE.update_verified_proxy_ip("vpn_1", "45.134.140.5")

            self.ctrl.maybe_schedule_duplicate_ip_repair()
        finally:
            self.ctrl.threading.Thread = original_thread

        self.assertEqual([("vpn_1", False)], calls)
        self.assertEqual(1, self.ctrl.duplicate_repair_snapshot()["scheduled_total"])

    def test_duplicate_public_ip_refresh_schedules_one_repair_rotation(self):
        calls = []

        class ImmediateThread:
            def __init__(self, target, args=(), daemon=None):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        original_thread = self.ctrl.threading.Thread
        try:
            self.ctrl.threading.Thread = ImmediateThread
            self.ctrl.rotate_instance = lambda instance, force=False: calls.append((instance, force)) or {
                "instance": instance,
                "ok": True,
                "outcome": self.ctrl.OUTCOME_SUCCESS,
            }
            self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
            self.ctrl.STATE.update_health("vpn_1", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)

            self.ctrl.maybe_schedule_duplicate_ip_repair()
        finally:
            self.ctrl.threading.Thread = original_thread

        self.assertEqual([("vpn_1", False)], calls)
        self.assertEqual(1, self.ctrl.duplicate_repair_snapshot()["scheduled_total"])

    def test_duplicate_public_ip_repair_respects_cooldown(self):
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_health("vpn_1", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.start_cooldown("vpn_1", self.ctrl.OUTCOME_RECOVERY_TIMEOUT)

        self.ctrl.maybe_schedule_duplicate_ip_repair()

        self.assertEqual([], self.ctrl.duplicate_repair_snapshot()["in_flight"])
        self.assertEqual(0, self.ctrl.duplicate_repair_snapshot()["scheduled_total"])

    def test_failed_duplicate_public_ip_repair_sets_retry_backoff(self):
        calls = []

        class ImmediateThread:
            def __init__(self, target, args=(), daemon=None):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        original_thread = self.ctrl.threading.Thread
        try:
            self.ctrl.threading.Thread = ImmediateThread
            self.ctrl.DUPLICATE_REPAIR_RETRY_COOLDOWN = 300
            self.ctrl.rotate_instance = lambda instance, force=False: calls.append((instance, force)) or {
                "instance": instance,
                "ok": False,
                "outcome": self.ctrl.OUTCOME_RECOVERY_TIMEOUT,
            }
            self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
            self.ctrl.STATE.update_health("vpn_1", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)

            self.ctrl.maybe_schedule_duplicate_ip_repair()
            self.ctrl.maybe_schedule_duplicate_ip_repair()
        finally:
            self.ctrl.threading.Thread = original_thread

        self.assertEqual([("vpn_1", False)], calls)
        repair = self.ctrl.duplicate_repair_snapshot()
        self.assertEqual(1, repair["scheduled_total"])
        self.assertGreater(repair["backoff_remaining"]["vpn_1"], 0)

    def test_recovery_timeout_starts_cooldown(self):
        def fake_ctrl(method, instance, path, body=None):
            if method == "GET" and path in self.ctrl.STATUS_PATHS:
                return {"status": "running"}
            if method == "PUT":
                return {}
            raise AssertionError((method, path))

        self.ctrl._ctrl = fake_ctrl
        self.ctrl.is_healthy = lambda instance: False
        self.ctrl.sleep = lambda seconds: None

        result = self.ctrl.rotate_instance("vpn_0", force=True)
        state = self.ctrl.STATE.snapshot()["instances"][0]

        self.assertFalse(result["ok"])
        self.assertEqual(self.ctrl.OUTCOME_RECOVERY_TIMEOUT, result["outcome"])
        self.assertGreater(state["cooldown_remaining_seconds"], 0)
        self.assertEqual(self.ctrl.OUTCOME_RECOVERY_TIMEOUT, state["cooldown_reason"])

    def test_rotate_all_skips_cooling_backends_and_rotates_eligible(self):
        calls = []

        def fake_rotate(instance, force=False):
            calls.append((instance, force))
            if self.ctrl.STATE.cooldown_remaining(instance) > 0:
                return self.ctrl.rotation_response(
                    instance,
                    False,
                    self.ctrl.OUTCOME_COOLDOWN,
                    time.monotonic(),
                    cooldown_remaining_seconds=round(self.ctrl.STATE.cooldown_remaining(instance), 3),
                )
            return self.ctrl.rotation_response(instance, True, self.ctrl.OUTCOME_SUCCESS, time.monotonic())

        self.ctrl.STATE.start_cooldown("vpn_0", self.ctrl.OUTCOME_RECOVERY_TIMEOUT)
        self.ctrl.rotate_instance = fake_rotate

        result = self.ctrl.rotate_all()

        self.assertFalse(result["ok"])
        self.assertEqual(self.ctrl.AGG_OUTCOME_PARTIAL_SUCCESS, result["outcome"])
        self.assertEqual(1, result["eligible_count"])
        self.assertEqual(1, result["skipped_count"])
        self.assertEqual(1, result["batch_count"])
        self.assertEqual(0, result["timed_out_count"])
        self.assertEqual(1, result["success_count"])
        self.assertEqual(1, result["cooldown_count"])
        self.assertEqual([("vpn_1", False)], calls)
        self.assertEqual(self.ctrl.OUTCOME_COOLDOWN, result["results"][0]["outcome"])

    def test_rotate_all_batches_eligible_backends_and_counts_timeouts(self):
        ctrl = load_controller(self.tmp.name, instances="vpn_0,vpn_1,vpn_2,vpn_3,vpn_4")
        ctrl.ROTATE_ALL_BATCH_SIZE = 2
        ctrl.ROTATE_ALL_BATCH_DELAY_SECONDS = 0
        calls = []

        def fake_rotate(instance, force=False):
            calls.append(instance)
            outcome = ctrl.OUTCOME_RECOVERY_TIMEOUT if instance == "vpn_3" else ctrl.OUTCOME_SUCCESS
            return ctrl.rotation_response(instance, outcome == ctrl.OUTCOME_SUCCESS, outcome, time.monotonic())

        ctrl.STATE.start_cooldown("vpn_0", ctrl.OUTCOME_RECOVERY_TIMEOUT)
        ctrl.rotate_instance = fake_rotate

        result = ctrl.rotate_all()

        self.assertEqual(4, result["eligible_count"])
        self.assertEqual(1, result["skipped_count"])
        self.assertEqual(2, result["batch_count"])
        self.assertEqual(1, result["timed_out_count"])
        self.assertEqual({"vpn_1", "vpn_2", "vpn_3", "vpn_4"}, set(calls))

    def test_named_force_bypasses_cooldown_and_reports_bypass(self):
        def fake_ctrl(method, instance, path, body=None):
            if method == "GET" and path in self.ctrl.STATUS_PATHS:
                return {"status": "running"}
            if method == "PUT":
                return {}
            raise AssertionError((method, path))

        self.ctrl._ctrl = fake_ctrl
        self.ctrl.STATE.start_cooldown("vpn_0", self.ctrl.OUTCOME_RECOVERY_TIMEOUT)
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.is_healthy = lambda instance: True
        self.ctrl.get_public_ip = lambda instance: "2.2.2.2"
        self.ctrl.refresh_verified_proxy_ip = lambda instance, force=False: {"verified_proxy_ip": "2.2.2.2"}
        self.ctrl.sleep = lambda seconds: None

        result = self.ctrl.rotate_instance("vpn_0", force=True)
        state = self.ctrl.STATE.snapshot()["instances"][0]

        self.assertTrue(result["ok"])
        self.assertTrue(result["forced_bypass"])
        self.assertEqual(1, state["forced_bypass_count"])

    def test_healthy_ip_unchanged_outcome_is_degraded_not_success(self):
        def fake_ctrl(method, instance, path, body=None):
            if method == "GET" and path in self.ctrl.STATUS_PATHS:
                return {"status": "running"}
            if method == "PUT":
                return {}
            raise AssertionError((method, path))

        self.ctrl._ctrl = fake_ctrl
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.is_healthy = lambda instance: True
        self.ctrl.get_public_ip = lambda instance: "1.1.1.1"
        self.ctrl.sleep = lambda seconds: None

        result = self.ctrl.rotate_instance("vpn_0", force=True)
        snap = self.ctrl.STATE.snapshot()

        self.assertFalse(result["ok"])
        self.assertEqual(self.ctrl.OUTCOME_HEALTHY_IP_UNCHANGED, result["outcome"])
        self.assertEqual(0, snap["rotations_total"])
        self.assertEqual(1, snap["rotation_errors_by_outcome"][self.ctrl.OUTCOME_HEALTHY_IP_UNCHANGED])

    def test_proxy_failure_outcome_when_recovered_proxy_probe_fails(self):
        def fake_ctrl(method, instance, path, body=None):
            if method == "GET" and path in self.ctrl.STATUS_PATHS:
                return {"status": "running"}
            if method == "PUT":
                return {}
            raise AssertionError((method, path))

        self.ctrl._ctrl = fake_ctrl
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.is_healthy = lambda instance: True
        self.ctrl.get_public_ip = lambda instance: "2.2.2.2"
        self.ctrl.verify_proxy_after_rotation = lambda instance: (False, "proxy refused")
        self.ctrl.sleep = lambda seconds: None

        result = self.ctrl.rotate_instance("vpn_0", force=True)

        self.assertFalse(result["ok"])
        self.assertEqual(self.ctrl.OUTCOME_PROXY_FAILURE, result["outcome"])
        self.assertIn("proxy refused", result["message"])

    def test_metrics_expose_latest_outcome_and_cooldown(self):
        self.ctrl.STATE.start_cooldown("vpn_0", self.ctrl.OUTCOME_RECOVERY_TIMEOUT)
        self.ctrl.STATE.record_rotation("vpn_0", self.ctrl.OUTCOME_RECOVERY_TIMEOUT)

        metrics = self.ctrl.render_metrics()

        self.assertIn('chamosel_instance_rotation_outcome{instance="vpn_0",outcome="recovery_timeout"} 1', metrics)
        self.assertIn('chamosel_instance_rotation_cooldown_active{instance="vpn_0"} 1', metrics)
        self.assertIn('chamosel_instance_rotation_cooldown_remaining_seconds{instance="vpn_0"}', metrics)

    def test_metrics_expose_pool_status_and_state_freshness(self):
        self.ctrl.STATE.update_health("vpn_0", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)
        self.ctrl.STATE.update_health("vpn_1", True, "1.1.1.1", status=self.ctrl.STATUS_HEALTHY)

        metrics = self.ctrl.render_metrics()

        self.assertIn('chamosel_pool_status{status="degraded"} 1', metrics)
        self.assertIn('chamosel_pool_degraded_reason{reason="duplicate_public_ip"} 1', metrics)
        self.assertIn("chamosel_state_fresh 1", metrics)
        self.assertIn("chamosel_duplicate_ip_repair_scheduled_total", metrics)
        self.assertIn("chamosel_duplicate_ip_repair_in_flight", metrics)

    def test_dashboard_exposes_latest_outcome_and_cooldown(self):
        self.ctrl.STATE.start_cooldown("vpn_0", self.ctrl.OUTCOME_RECOVERY_TIMEOUT)
        self.ctrl.STATE.record_rotation("vpn_0", self.ctrl.OUTCOME_RECOVERY_TIMEOUT)

        html = self.ctrl.render_dashboard()

        self.assertIn("recovery_timeout", html)
        self.assertIn("cooldown", html)


if __name__ == "__main__":
    unittest.main()
