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
        self.old_cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self.chamosel = load_chamosel()
        self.cfg = {"global_settings": {"api_port": 8800}, "vpn_providers": {"surfshark": {}}}

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def pool(self, healthy=True):
        return {
            "instances": [
                {
                    "name": "surfshark_0",
                    "healthy": healthy,
                    "status": "healthy" if healthy else "down",
                    "public_ip": "45.134.140.5" if healthy else None,
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

    def test_verify_leaks_success_when_backend_ip_differs_from_host(self):
        self.chamosel.fetch_direct_ip = lambda target, timeout: ("149.232.250.241", {"ip": "149.232.250.241"})
        self.chamosel.fetch_pool_state = lambda cfg: self.pool()
        self.chamosel.run_backend_probe = lambda instance, target, timeout: {"ip": "45.134.140.5"}

        result = self.chamosel.verify_leaks(self.cfg)

        self.assertTrue(result["ok"])
        self.assertEqual("149.232.250.241", result["direct_ip"])
        self.assertEqual(1, result["verified_count"])
        self.assertFalse(result["instances"][0]["leak_detected"])

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
        self.assertIn("--json", help_text)
        self.assertIn("--timeout", help_text)
        self.assertIn("--target", help_text)
        self.assertNotIn("GLUETUN_API_KEY", help_text)
        self.assertNotIn("WIREGUARD_PRIVATE_KEY", help_text)

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
