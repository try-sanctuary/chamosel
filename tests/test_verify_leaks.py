import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_chamosel():
    spec = importlib.util.spec_from_file_location("chamosel_verify_under_test", ROOT / "chamosel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VerifyLeakTests(unittest.TestCase):
    def setUp(self):
        self.old_controller_token = os.environ.pop("CONTROLLER_AUTH_TOKEN", None)
        self.old_cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self.chamosel = load_chamosel()
        self.cfg = {"global_settings": {"api_port": 8800}, "vpn_providers": {"surfshark": {}}}

    def tearDown(self):
        os.chdir(self.old_cwd)
        if self.old_controller_token is not None:
            os.environ["CONTROLLER_AUTH_TOKEN"] = self.old_controller_token
        else:
            os.environ.pop("CONTROLLER_AUTH_TOKEN", None)
        self.tmp.cleanup()

    def pool(self, healthy=True):
        return {
            "instances": [
                {
                    "name": "surfshark_0",
                    "healthy": healthy,
                    "status": "healthy" if healthy else "down",
                    "public_ip": "45.134.140.5" if healthy else None,
                    "verified_proxy_ip": "45.134.140.5" if healthy else None,
                    "egress_state_fresh": healthy,
                    "public_ip_mismatch": False,
                }
            ]
        }

    def test_extract_public_ip_accepts_ifconfig_json(self):
        self.assertEqual("45.134.140.5", self.chamosel.extract_public_ip({"ip": "45.134.140.5"}))

    def test_extract_public_ip_rejects_missing_malformed_and_private_values(self):
        for payload in ({}, {"ip": "not-an-ip"}, {"ip": "10.0.0.1"}):
            with self.subTest(payload=payload):
                with self.assertRaises(self.chamosel.LeakVerificationError):
                    self.chamosel.extract_public_ip(payload)

    def test_probe_command_does_not_embed_secret_values(self):
        cmd = self.chamosel.build_backend_probe_cmd(
            "surfshark_0",
            "https://ifconfig.co/json",
            30,
        )
        rendered = " ".join(cmd)

        self.assertIn("docker compose -f docker-compose.yml exec -T controller", rendered)
        self.assertIn("http://surfshark_0:8888", rendered)
        self.assertNotIn("GLUETUN_API_KEY", rendered)
        self.assertNotIn("WIREGUARD_PRIVATE_KEY", rendered)
        self.assertNotIn("vpn-password", rendered)

    def test_controller_auth_headers_use_config_token_without_output(self):
        cfg = {
            "global_settings": {
                "controller_auth_enabled": True,
                "controller_auth_token": "controller-secret",
            },
            "vpn_providers": {"surfshark": {}},
        }

        headers = self.chamosel.controller_auth_headers(cfg)

        self.assertEqual({"X-Chamosel-Auth": "controller-secret"}, headers)

    def test_verify_leaks_success_when_backend_ip_differs_from_host(self):
        self.chamosel.fetch_direct_ip = lambda target, timeout: ("149.232.250.241", {"ip": "149.232.250.241"})
        self.chamosel.fetch_pool_state = lambda cfg: self.pool()
        self.chamosel.run_backend_probe = lambda instance, target, timeout: {"ip": "45.134.140.5"}

        result = self.chamosel.verify_leaks(self.cfg)

        self.assertTrue(result["ok"])
        self.assertEqual("149.232.250.241", result["direct_ip"])
        self.assertEqual(1, result["verified_count"])
        self.assertFalse(result["instances"][0]["leak_detected"])
        self.assertEqual("45.134.140.5", result["instances"][0]["controller_verified_proxy_ip"])
        self.assertFalse(result["instances"][0]["controller_proxy_ip_mismatch"])

    def test_verify_leaks_reports_controller_mismatch_without_failing_proxy_result(self):
        self.chamosel.fetch_direct_ip = lambda target, timeout: ("149.232.250.241", {"ip": "149.232.250.241"})
        self.chamosel.fetch_pool_state = lambda cfg: {
            "instances": [
                {
                    "name": "surfshark_4",
                    "healthy": True,
                    "status": "healthy",
                    "public_ip": "1.1.1.1",
                    "verified_proxy_ip": "45.134.140.5",
                    "egress_state_fresh": True,
                    "public_ip_mismatch": True,
                }
            ]
        }
        self.chamosel.run_backend_probe = lambda instance, target, timeout: {"ip": "45.134.140.5"}

        result = self.chamosel.verify_leaks(self.cfg)

        self.assertTrue(result["ok"])
        item = result["instances"][0]
        self.assertEqual("1.1.1.1", item["controller_public_ip"])
        self.assertEqual("45.134.140.5", item["controller_verified_proxy_ip"])
        self.assertEqual("45.134.140.5", item["proxy_ip"])
        self.assertTrue(item["controller_public_ip_mismatch"])
        self.assertFalse(item["controller_proxy_ip_mismatch"])

    def test_verify_leaks_fails_when_backend_ip_equals_host(self):
        self.chamosel.fetch_direct_ip = lambda target, timeout: ("149.232.250.241", {"ip": "149.232.250.241"})
        self.chamosel.fetch_pool_state = lambda cfg: self.pool()
        self.chamosel.run_backend_probe = lambda instance, target, timeout: {"ip": "149.232.250.241"}

        result = self.chamosel.verify_leaks(self.cfg)

        self.assertFalse(result["ok"])
        self.assertTrue(result["instances"][0]["leak_detected"])
        self.assertIn("direct host IP", result["instances"][0]["error"])

    def test_verify_leaks_fails_when_direct_host_ip_unavailable(self):
        def fail_direct(target, timeout):
            raise self.chamosel.LeakVerificationError("response does not contain a public IP")

        self.chamosel.fetch_direct_ip = fail_direct

        result = self.chamosel.verify_leaks(self.cfg)

        self.assertFalse(result["ok"])
        self.assertEqual(0, result["total_count"])
        self.assertIn("public IP", result["error"])

    def test_verify_leaks_fails_when_controller_unreachable(self):
        self.chamosel.fetch_direct_ip = lambda target, timeout: ("149.232.250.241", {"ip": "149.232.250.241"})

        def fail_pool(cfg):
            raise self.chamosel.LeakVerificationError("controller unreachable")

        self.chamosel.fetch_pool_state = fail_pool

        result = self.chamosel.verify_leaks(self.cfg)

        self.assertFalse(result["ok"])
        self.assertEqual(0, result["total_count"])
        self.assertIn("controller unreachable", result["error"])

    def test_verify_leaks_fails_unhealthy_backend_by_default(self):
        self.chamosel.fetch_direct_ip = lambda target, timeout: ("149.232.250.241", {"ip": "149.232.250.241"})
        self.chamosel.fetch_pool_state = lambda cfg: self.pool(healthy=False)

        result = self.chamosel.verify_leaks(self.cfg)

        self.assertFalse(result["ok"])
        self.assertEqual(1, result["total_count"])
        self.assertIn("controller status is down", result["instances"][0]["error"])

    def test_metadata_mapping_in_backend_result(self):
        result = self.chamosel.normalize_probe_result(
            {"name": "surfshark_0", "healthy": True, "status": "healthy", "public_ip": "45.134.140.5"},
            "149.232.250.241",
            {
                "ip": "45.134.140.5",
                "country": "United States",
                "region": "New York",
                "city": "New York",
                "asn": "AS9009",
                "asn_org": "M247 Europe SRL",
            },
        )

        self.assertTrue(result["proxy_ok"])
        self.assertEqual("United States", result["country"])
        self.assertEqual("New York", result["region"])
        self.assertEqual("New York", result["city"])
        self.assertEqual("AS9009", result["asn"])
        self.assertEqual("M247 Europe SRL", result["asn_org"])

    def test_json_output_shape_and_nonzero_failure(self):
        self.chamosel.verify_leaks = lambda cfg, target, timeout: {
            "direct_ip": "149.232.250.241",
            "target": target,
            "ok": False,
            "verified_count": 0,
            "total_count": 1,
            "error": "one or more backends failed leak verification",
            "instances": [
                {
                    "name": "surfshark_0",
                    "controller_status": "healthy",
                    "controller_public_ip": "45.134.140.5",
                    "controller_verified_proxy_ip": "45.134.140.5",
                    "controller_public_ip_mismatch": False,
                    "controller_proxy_ip_mismatch": True,
                    "controller_egress_state_fresh": True,
                    "proxy_ok": False,
                    "proxy_ip": "149.232.250.241",
                    "country": None,
                    "region": None,
                    "city": None,
                    "asn": None,
                    "asn_org": None,
                    "leak_detected": True,
                    "error": "proxy IP equals direct host IP",
                }
            ],
        }

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as raised:
                self.chamosel.cmd_verify_leaks(self.cfg, json_output=True)
        payload = json.loads(buf.getvalue())

        self.assertEqual(1, raised.exception.code)
        self.assertFalse(payload["ok"])
        self.assertIn("direct_ip", payload)
        self.assertIn("target", payload)
        self.assertIn("verified_count", payload)
        self.assertIn("total_count", payload)
        self.assertIn("instances", payload)
        self.assertIn("error", payload["instances"][0])

    def test_human_output_table_contains_summary_and_rows(self):
        rendered = self.chamosel.render_leak_table(
            {
                "direct_ip": "149.232.250.241",
                "target": "https://ifconfig.co/json",
                "ok": True,
                "verified_count": 1,
                "total_count": 1,
                "error": None,
                "instances": [
                    {
                        "name": "surfshark_0",
                        "controller_status": "healthy",
                        "controller_public_ip": "45.134.140.5",
                        "controller_verified_proxy_ip": "45.134.140.5",
                        "proxy_ok": True,
                        "proxy_ip": "45.134.140.5",
                        "country": "United States",
                        "region": None,
                        "city": None,
                        "asn": "AS9009",
                        "asn_org": None,
                        "leak_detected": False,
                        "error": None,
                    }
                ],
            }
        )

        self.assertIn("Direct host IP: 149.232.250.241", rendered)
        self.assertIn("surfshark_0", rendered)
        self.assertIn("Verified: 1/1 backends", rendered)
        self.assertIn("Leak result: PASS", rendered)

    def test_cli_help_documents_verify_leaks_without_secrets(self):
        parser = self.chamosel.build_parser()
        help_text = parser.format_help()

        self.assertIn("verify-leaks", help_text)
        self.assertIn("stress", help_text)
        self.assertIn("doctor", help_text)
        self.assertIn("--json", help_text)
        self.assertIn("--timeout", help_text)
        self.assertIn("--target", help_text)
        self.assertIn("--iterations", help_text)
        self.assertIn("--mode", help_text)
        self.assertIn("--repair", help_text)
        self.assertNotIn("GLUETUN_API_KEY", help_text)
        self.assertNotIn("CONTROLLER_AUTH_TOKEN", help_text)
        self.assertNotIn("WIREGUARD_PRIVATE_KEY", help_text)

    def test_status_output_contains_latest_outcome_and_cooldown(self):
        self.chamosel.api_call = lambda cfg, method, path: {
            "healthy": 1,
            "count": 1,
            "rotations_total": 0,
            "instances": [
                {
                    "name": "surfshark_0",
                    "status": "healthy",
                    "healthy": True,
                    "rotations": 0,
                    "public_ip": "45.134.140.5",
                    "last_rotation_outcome": "recovery_timeout",
                    "cooldown_remaining_seconds": 42,
                    "cooldown_reason": "recovery_timeout",
                }
            ],
        }

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.chamosel.cmd_status(self.cfg)

        rendered = buf.getvalue()
        self.assertIn("OUTCOME", rendered)
        self.assertIn("COOLDOWN", rendered)
        self.assertIn("recovery_timeout", rendered)
        self.assertIn("42s", rendered)

    def test_doctor_json_does_not_expose_secrets(self):
        Path(".env.local").write_text("WIREGUARD_PRIVATE_KEY=super-secret\n")
        cfg = {
            "global_settings": {
                "api_port": 8800,
                "stats_port": 8404,
                "env_file": ".env.local",
                "api_key": "config-secret",
            },
            "vpn_providers": {"surfshark": {"num_containers": 1}},
        }
        self.chamosel.compose_check = lambda args: {"ok": True, "returncode": 0, "stdout": "ok", "stderr": ""}
        self.chamosel.tcp_check = lambda host, port, timeout=2: {"ok": True, "error": None}

        def fake_api(cfg, method, path, timeout=15):
            if path == "/health":
                return {"ok": True, "status": 200, "payload": {"status": "ok"}, "error": None}
            if path == "/pool?fresh=1":
                return {
                    "ok": True,
                    "status": 200,
                    "payload": {
                        "healthy": 1,
                        "count": 1,
                        "pool_status": "healthy",
                        "state_fresh": True,
                        "degraded_reasons": [],
                    },
                    "error": None,
                }
            raise AssertionError(path)

        self.chamosel.api_call_result = fake_api

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.chamosel.cmd_doctor(cfg, json_output=True)
        rendered = buf.getvalue()
        payload = json.loads(rendered)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["checks"]["env_local"]["ok"])
        self.assertEqual("none", payload["repair_decision"]["action"])
        self.assertNotIn("super-secret", rendered)
        self.assertNotIn("config-secret", rendered)
        self.assertNotIn("WIREGUARD_PRIVATE_KEY", rendered)

    def test_doctor_fails_when_pool_state_is_not_fresh(self):
        self.chamosel.compose_check = lambda args: {"ok": True, "returncode": 0, "stdout": "ok", "stderr": ""}
        self.chamosel.tcp_check = lambda host, port, timeout=2: {"ok": True, "error": None}

        def fake_api(cfg, method, path, timeout=15):
            if path == "/health":
                return {"ok": True, "status": 200, "payload": {"status": "ok"}, "error": None}
            if path == "/pool?fresh=1":
                return {
                    "ok": True,
                    "status": 200,
                    "payload": {
                        "healthy": 1,
                        "count": 1,
                        "pool_status": "healthy",
                        "state_fresh": False,
                        "degraded_reasons": ["stale_state"],
                    },
                    "error": None,
                }
            raise AssertionError(path)

        self.chamosel.api_call_result = fake_api

        report = self.chamosel.doctor_report(self.cfg)

        self.assertFalse(report["ok"])
        self.assertFalse(report["checks"]["pool_fresh"]["ok"])

    def test_doctor_reports_duplicate_ip_repair_in_progress(self):
        self.chamosel.compose_check = lambda args: {"ok": True, "returncode": 0, "stdout": "ok", "stderr": ""}
        self.chamosel.tcp_check = lambda host, port, timeout=2: {"ok": True, "error": None}

        def fake_api(cfg, method, path, timeout=15):
            if path == "/health":
                return {"ok": True, "status": 200, "payload": {"status": "ok"}, "error": None}
            if path == "/pool?fresh=1":
                return {
                    "ok": True,
                    "status": 200,
                    "payload": {
                        "healthy": 2,
                        "count": 2,
                        "pool_status": "degraded",
                        "state_fresh": True,
                        "degraded_reasons": ["duplicate_public_ip"],
                        "duplicate_repair": {
                            "enabled": True,
                            "in_flight": ["surfshark_4"],
                            "backoff_remaining": {},
                            "scheduled_total": 1,
                        },
                    },
                    "error": None,
                }
            raise AssertionError(path)

        self.chamosel.api_call_result = fake_api

        report = self.chamosel.doctor_report(self.cfg)
        rendered = self.chamosel.render_doctor_report(report)

        self.assertFalse(report["ok"])
        self.assertEqual("repair_in_progress", report["repair_decision"]["action"])
        self.assertEqual(["surfshark_4"], report["repair_decision"]["targets"])
        self.assertIn("Repair decision: repair_in_progress", rendered)

    def test_doctor_repair_calls_repair_endpoint_for_duplicate_ip(self):
        self.chamosel.compose_check = lambda args: {"ok": True, "returncode": 0, "stdout": "ok", "stderr": ""}
        self.chamosel.tcp_check = lambda host, port, timeout=2: {"ok": True, "error": None}
        calls = []
        cfg = {
            "global_settings": {
                "api_port": 8800,
                "stats_port": 8404,
                "controller_auth_enabled": True,
                "controller_auth_token": "controller-secret",
            },
            "vpn_providers": {"surfshark": {"num_containers": 2}},
        }

        def fake_api(cfg, method, path, timeout=15):
            calls.append((method, path))
            if path == "/health":
                return {"ok": True, "status": 200, "payload": {"status": "ok"}, "error": None}
            if path == "/pool?fresh=1":
                return {
                    "ok": True,
                    "status": 200,
                    "payload": {
                        "healthy": 2,
                        "count": 2,
                        "pool_status": "degraded",
                        "state_fresh": True,
                        "degraded_reasons": ["verified_duplicate_proxy_ip"],
                        "duplicate_repair": {
                            "enabled": True,
                            "in_flight": [],
                            "backoff_remaining": {},
                        },
                    },
                    "error": None,
                }
            if path == "/repair/duplicate-ip":
                return {
                    "ok": True,
                    "status": 200,
                    "payload": {"ok": True, "attempted": True, "outcome": "repair_attempted"},
                    "error": None,
                }
            raise AssertionError(path)

        self.chamosel.api_call_result = fake_api

        report = self.chamosel.doctor_report(cfg, repair=True)
        rendered = self.chamosel.render_doctor_report(report)

        self.assertIn(("POST", "/repair/duplicate-ip"), calls)
        self.assertEqual("repair_attempted", report["repair_result"]["payload"]["outcome"])
        self.assertIn("Repair result: repair_attempted", rendered)
        self.assertNotIn("controller-secret", json.dumps(report))

    def test_doctor_repair_skips_public_ip_mismatch_monitor_only(self):
        self.chamosel.compose_check = lambda args: {"ok": True, "returncode": 0, "stdout": "ok", "stderr": ""}
        self.chamosel.tcp_check = lambda host, port, timeout=2: {"ok": True, "error": None}
        calls = []

        def fake_api(cfg, method, path, timeout=15):
            calls.append((method, path))
            if path == "/health":
                return {"ok": True, "status": 200, "payload": {"status": "ok"}, "error": None}
            if path == "/pool?fresh=1":
                return {
                    "ok": True,
                    "status": 200,
                    "payload": {
                        "healthy": 2,
                        "count": 2,
                        "pool_status": "degraded",
                        "state_fresh": True,
                        "degraded_reasons": ["public_ip_mismatch"],
                        "duplicate_repair": {"enabled": True},
                    },
                    "error": None,
                }
            raise AssertionError(path)

        self.chamosel.api_call_result = fake_api

        report = self.chamosel.doctor_report(self.cfg, repair=True)

        self.assertNotIn(("POST", "/repair/duplicate-ip"), calls)
        self.assertEqual("monitor", report["repair_decision"]["action"])
        self.assertEqual("skipped", report["repair_result"]["payload"]["outcome"])

    def test_doctor_reports_verified_duplicate_ip_repair_requested(self):
        decision = self.chamosel.doctor_repair_decision(
            True,
            {
                "pool_status": "degraded",
                "degraded_reasons": ["verified_duplicate_proxy_ip"],
                "duplicate_repair": {
                    "enabled": True,
                    "in_flight": [],
                    "backoff_remaining": {},
                },
            },
        )

        self.assertEqual("repair_requested", decision["action"])
        self.assertEqual("verified_duplicate_proxy_ip", decision["reason"])

    def test_doctor_reports_public_ip_mismatch_as_monitor_only(self):
        decision = self.chamosel.doctor_repair_decision(
            True,
            {
                "pool_status": "degraded",
                "degraded_reasons": ["public_ip_mismatch"],
                "duplicate_repair": {"enabled": True},
            },
        )

        self.assertEqual("monitor", decision["action"])
        self.assertEqual("public_ip_mismatch", decision["reason"])

    def test_doctor_reports_egress_verification_failure_as_manual(self):
        decision = self.chamosel.doctor_repair_decision(
            True,
            {
                "pool_status": "degraded",
                "degraded_reasons": ["egress_verification_failed"],
                "duplicate_repair": {"enabled": True},
            },
        )

        self.assertEqual("manual", decision["action"])
        self.assertEqual("egress_verification_failed", decision["reason"])

    def test_doctor_reports_duplicate_ip_repair_backoff(self):
        decision = self.chamosel.doctor_repair_decision(
            True,
            {
                "pool_status": "degraded",
                "degraded_reasons": ["duplicate_public_ip"],
                "duplicate_repair": {
                    "enabled": True,
                    "in_flight": [],
                    "backoff_remaining": {"surfshark_4": 120.0},
                },
            },
        )

        self.assertEqual("wait_backoff", decision["action"])
        self.assertEqual({"surfshark_4": 120.0}, decision["backoff_remaining"])

    def test_stress_parser_accepts_expected_options(self):
        args = self.chamosel.build_parser().parse_args(
            [
                "stress",
                "--iterations",
                "100",
                "--mode",
                "rotation",
                "--target",
                "https://ifconfig.co/json",
                "--timeout",
                "12",
                "--out-dir",
                "/tmp/chamosel-stress",
            ]
        )

        self.assertEqual("stress", args.action)
        self.assertEqual(100, args.iterations)
        self.assertEqual("rotation", args.stress_mode)
        self.assertEqual(12, args.timeout)
        self.assertEqual("/tmp/chamosel-stress", args.out_dir)

    def test_doctor_parser_accepts_repair(self):
        args = self.chamosel.build_parser().parse_args(["doctor", "--repair", "--json"])

        self.assertEqual("doctor", args.action)
        self.assertTrue(args.repair)
        self.assertTrue(args.json_output)

    def test_leak_only_stress_does_not_rotate_and_summarizes_report(self):
        rotate_calls = []
        verify_calls = []

        def fake_verify(cfg, target, timeout):
            verify_calls.append((target, timeout))
            return {
                "ok": True,
                "verified_count": 1,
                "total_count": 1,
                "instances": [
                    {
                        "name": "surfshark_0",
                        "proxy_ip": "45.134.140.5",
                        "leak_detected": False,
                        "error": None,
                    }
                ],
            }

        self.chamosel.verify_leaks = fake_verify
        self.chamosel.api_call = lambda cfg, method, path, timeout=15: rotate_calls.append(path) or {}

        result = self.chamosel.run_stress(
            self.cfg,
            iterations=3,
            mode="leak-only",
            target="https://ifconfig.co/json",
            timeout=7,
        )

        self.assertTrue(result["ok"])
        self.assertEqual("leak_only", result["mode"])
        self.assertEqual(3, result["iterations_completed"])
        self.assertEqual(3, result["verified_backend_checks"])
        self.assertEqual(0, result["leak_failures"])
        self.assertEqual(0, result["availability_failures"])
        self.assertEqual([], rotate_calls)
        self.assertEqual(3, len(verify_calls))

    def test_rotation_stress_summarizes_partial_success_and_cooldown(self):
        responses = [
            {
                "ok": False,
                "outcome": "partial_success",
                "results": [
                    {"instance": "surfshark_0", "ok": True, "outcome": "success"},
                    {"instance": "surfshark_1", "ok": False, "outcome": "cooldown"},
                ],
            },
            {
                "ok": True,
                "outcome": "success",
                "results": [
                    {"instance": "surfshark_0", "ok": True, "outcome": "success"},
                ],
            },
        ]

        def fake_api(cfg, method, path, timeout=15):
            self.assertEqual("POST", method)
            self.assertEqual("/rotate/all", path)
            return responses.pop(0)

        self.chamosel.api_call = fake_api
        self.chamosel.verify_leaks = lambda cfg, target, timeout: {
            "ok": True,
            "verified_count": 2,
            "total_count": 2,
            "instances": [],
        }

        result = self.chamosel.run_stress(
            self.cfg,
            iterations=2,
            mode="rotation",
            target="https://ifconfig.co/json",
            timeout=7,
        )

        self.assertTrue(result["ok"])
        self.assertEqual("rotation", result["mode"])
        self.assertEqual(2, result["mass_rotation_attempts"])
        self.assertEqual(1, result["partial_success_count"])
        self.assertEqual(1, result["cooldown_skip_count"])
        self.assertEqual(2, result["rotation_outcomes"]["success"])
        self.assertEqual(1, result["rotation_outcomes"]["cooldown"])

    def test_readme_documents_leak_verification_examples_and_limits(self):
        readme = (ROOT / "README.md").read_text()

        self.assertIn("## Leak Verification", readme)
        self.assertIn("python3 chamosel.py verify-leaks", readme)
        self.assertIn("python3 chamosel.py verify-leaks --json", readme)
        self.assertIn("direct host IP differs", readme)
        self.assertIn("Browser WebRTC", readme)
        self.assertIn("socks5h://", readme)
        self.assertIn("Traffic that bypasses chamosel", readme)


if __name__ == "__main__":
    unittest.main()
