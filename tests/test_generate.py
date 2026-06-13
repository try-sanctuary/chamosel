import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_chamosel():
    spec = importlib.util.spec_from_file_location("chamosel_under_test", ROOT / "chamosel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.old_env = os.environ.pop("GLUETUN_API_KEY", None)
        self.old_cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self.chamosel = load_chamosel()

    def tearDown(self):
        os.chdir(self.old_cwd)
        if self.old_env is not None:
            os.environ["GLUETUN_API_KEY"] = self.old_env
        else:
            os.environ.pop("GLUETUN_API_KEY", None)
        self.tmp.cleanup()

    def base_config(self):
        return {
            "global_settings": {"api_key": "config-secret"},
            "vpn_providers": {
                "surfshark": {
                    "num_containers": 1,
                    "env": {
                    "VPN_TYPE": "wireguard",
                    "WIREGUARD_PRIVATE_KEY": "abc#def:ghi",
                    "OPENVPN_PASSWORD": "pa:ss # word",
                    "TOKEN_JSON": '{"a":":#[]{}"}',
                    "QUOTED": '"double" and \'single\'',
                    "DOLLARS": "$abc:${VALUE}",
                    "BRACKETS": "[one, two]",
                    "LEADING_BOOL": "on",
                    "LEADING_NULL": "null",
                    "UNICODEISH": "plain-ascii-value",
                    "SERVER_COUNTRIES": "Germany,Netherlands",
                },
            }
            },
        }

    def test_config_api_key_is_persisted_for_controller_env(self):
        self.chamosel.generate(self.base_config())

        env_text = Path(".env").read_text()
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())

        self.assertIn("GLUETUN_API_KEY=config-secret\n", env_text)
        controller_env = compose["services"]["controller"]["environment"]
        self.assertEqual("${GLUETUN_API_KEY}", controller_env["GLUETUN_API_KEY"])

        gluetun_env = compose["services"]["surfshark_0"]["environment"]
        self.assertIn("config-secret", gluetun_env["HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE"])

    def test_env_values_are_mapping_quoted_and_yaml_safe(self):
        self.chamosel.generate(self.base_config())

        compose = yaml.safe_load(Path("docker-compose.yml").read_text())
        env = compose["services"]["surfshark_0"]["environment"]

        self.assertIsInstance(env, dict)
        self.assertEqual("abc#def:ghi", env["WIREGUARD_PRIVATE_KEY"])
        self.assertEqual("Germany,Netherlands", env["SERVER_COUNTRIES"])

    def test_controller_and_stats_bind_to_loopback_by_default(self):
        self.chamosel.generate(self.base_config())

        compose = yaml.safe_load(Path("docker-compose.yml").read_text())

        self.assertIn("127.0.0.1:8800:8800/tcp", compose["services"]["controller"]["ports"])
        self.assertIn("127.0.0.1:8404:8404/tcp", compose["services"]["haproxy"]["ports"])

    def test_explicit_remote_bind_renders_when_configured(self):
        cfg = self.base_config()
        cfg["global_settings"]["api_bind"] = "0.0.0.0"
        cfg["global_settings"]["stats_bind"] = "0.0.0.0"

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())

        self.assertIn("0.0.0.0:8800:8800/tcp", compose["services"]["controller"]["ports"])
        self.assertIn("0.0.0.0:8404:8404/tcp", compose["services"]["haproxy"]["ports"])

    def test_provider_env_file_renders_when_configured(self):
        cfg = self.base_config()
        cfg["global_settings"]["env_file"] = ".env.local"
        cfg["vpn_providers"]["surfshark"]["env"].pop("WIREGUARD_PRIVATE_KEY")

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())
        service = compose["services"]["surfshark_0"]

        self.assertEqual([".env.local"], service["env_file"])
        self.assertNotIn("WIREGUARD_PRIVATE_KEY", service["environment"])

    def test_controller_reliability_settings_render(self):
        cfg = self.base_config()
        cfg["global_settings"]["rotate_all_batch_size"] = 3
        cfg["global_settings"]["rotate_all_batch_delay_seconds"] = 5
        cfg["global_settings"]["pool_degraded_min_healthy"] = 2
        cfg["global_settings"]["auto_repair_duplicate_ips"] = False
        cfg["global_settings"]["duplicate_repair_retry_cooldown"] = 180

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())
        env = compose["services"]["controller"]["environment"]

        self.assertEqual("3", env["ROTATE_ALL_BATCH_SIZE"])
        self.assertEqual("5", env["ROTATE_ALL_BATCH_DELAY_SECONDS"])
        self.assertEqual("2", env["POOL_DEGRADED_MIN_HEALTHY"])
        self.assertEqual("false", env["AUTO_REPAIR_DUPLICATE_IPS"])
        self.assertEqual("180", env["DUPLICATE_REPAIR_RETRY_COOLDOWN"])

    def test_cmd_up_pulls_runtime_images_by_default(self):
        calls = []
        self.chamosel.generate = lambda cfg: calls.append(("generate", None))
        self.chamosel.compose_cmd = lambda args, capture=False: calls.append(("compose", args))

        self.chamosel.cmd_up(self.base_config())

        self.assertEqual(
            [
                ("generate", None),
                ("compose", ["pull", "--ignore-buildable"]),
                ("compose", ["up", "-d", "--build", "--remove-orphans"]),
            ],
            calls,
        )

    def test_cmd_up_can_skip_runtime_image_pull(self):
        calls = []
        self.chamosel.generate = lambda cfg: calls.append(("generate", None))
        self.chamosel.compose_cmd = lambda args, capture=False: calls.append(("compose", args))

        self.chamosel.cmd_up(self.base_config(), pull_images=False)

        self.assertEqual(
            [
                ("generate", None),
                ("compose", ["up", "-d", "--build", "--remove-orphans"]),
            ],
            calls,
        )

    def test_env_file_and_config_key_conflict_fails(self):
        Path(".env").write_text("GLUETUN_API_KEY=other-secret\n")

        with self.assertLogs("chamosel", level="ERROR") as logs:
            with self.assertRaises(SystemExit):
                self.chamosel.generate(self.base_config())

        rendered_logs = "\n".join(logs.output)
        self.assertNotIn("other-secret", rendered_logs)
        self.assertNotIn("config-secret", rendered_logs)


if __name__ == "__main__":
    unittest.main()
