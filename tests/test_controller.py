import importlib.util
import os
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_controller(tmpdir, instances="vpn_0,vpn_1"):
    old_env = os.environ.copy()
    os.environ.update(
        {
            "INSTANCES": instances,
            "STATE_FILE": str(Path(tmpdir) / "state.json"),
            "GLUETUN_API_KEY": "secret",
            "POLL_WORKERS": "8",
            "ROTATION_RECOVERY_TIMEOUT": "1",
        }
    )
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

        def slow_refresh(instance):
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

        def fake_refresh():
            called["refresh"] = True
            self.ctrl.STATE.update_health("vpn_0", True, "9.9.9.9", status=self.ctrl.STATUS_HEALTHY)

        handler = self.ctrl.Handler.__new__(self.ctrl.Handler)
        handler.path = "/pool?fresh=1"
        handler._json = lambda code, payload: captured.update({"code": code, "payload": payload})
        self.ctrl.refresh_instances = fake_refresh

        handler.do_GET()

        self.assertTrue(called["refresh"])
        self.assertEqual(200, captured["code"])
        self.assertEqual("9.9.9.9", captured["payload"]["instances"][0]["public_ip"])

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
        self.assertIn(
            'chamosel_instance_rotation_errors_by_outcome_total{instance="vpn_1",outcome="recovery_timeout"} 1',
            metrics,
        )


if __name__ == "__main__":
    unittest.main()
