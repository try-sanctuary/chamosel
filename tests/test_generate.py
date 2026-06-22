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
        self.old_controller_token = os.environ.pop("CONTROLLER_AUTH_TOKEN", None)
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
        if self.old_controller_token is not None:
            os.environ["CONTROLLER_AUTH_TOKEN"] = self.old_controller_token
        else:
            os.environ.pop("CONTROLLER_AUTH_TOKEN", None)
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
        self.assertEqual("false", controller_env["CONTROLLER_AUTH_ENABLED"])
        self.assertEqual("${CONTROLLER_AUTH_TOKEN}", controller_env["CONTROLLER_AUTH_TOKEN"])

        gluetun_env = compose["services"]["surfshark_0"]["environment"]
        self.assertNotIn("config-secret", gluetun_env["HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE"])
        self.assertIn("${GLUETUN_API_KEY}", gluetun_env["HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE"])

    def test_env_values_are_mapping_quoted_and_yaml_safe(self):
        self.chamosel.generate(self.base_config())

        compose = yaml.safe_load(Path("docker-compose.yml").read_text())
        env = compose["services"]["surfshark_0"]["environment"]

        self.assertIsInstance(env, dict)
        self.assertEqual("abc#def:ghi", env["WIREGUARD_PRIVATE_KEY"])
        self.assertEqual("Germany,Netherlands", env["SERVER_COUNTRIES"])

    def test_proxy_controller_and_stats_bind_to_loopback_by_default(self):
        self.chamosel.generate(self.base_config())

        compose = yaml.safe_load(Path("docker-compose.yml").read_text())

        self.assertIn("127.0.0.1:8888:8888/tcp", compose["services"]["haproxy"]["ports"])
        self.assertIn("127.0.0.1:8800:8800/tcp", compose["services"]["controller"]["ports"])
        self.assertIn("127.0.0.1:8404:8404/tcp", compose["services"]["haproxy"]["ports"])
        self.assertNotIn("proxy-client-net", compose["networks"])
        self.assertNotIn("proxy-client-net", compose["services"]["controller"]["networks"])
        self.assertNotIn("proxy-client-net", compose["services"]["surfshark_0"]["networks"])

    def test_proxy_client_network_attaches_only_haproxy_with_alias(self):
        cfg = self.base_config()
        cfg["global_settings"]["proxy_client_network_name"] = "chamosel-clients"
        cfg["global_settings"]["proxy_client_network_external"] = True
        cfg["global_settings"]["proxy_client_network_alias"] = "chamosel-proxy"

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())

        self.assertEqual(
            {"name": "chamosel-clients", "external": True},
            compose["networks"]["proxy-client-net"],
        )
        self.assertEqual(
            {"aliases": ["chamosel-proxy"]},
            compose["services"]["haproxy"]["networks"]["proxy-client-net"],
        )
        self.assertNotIn("proxy-client-net", compose["services"]["controller"]["networks"])
        self.assertNotIn("proxy-client-net", compose["services"]["surfshark_0"]["networks"])

    def test_proxy_publish_false_uses_client_network_without_host_proxy_port(self):
        cfg = self.base_config()
        cfg["global_settings"]["proxy_publish"] = False
        cfg["global_settings"]["proxy_bind"] = "0.0.0.0"
        cfg["global_settings"]["proxy_port"] = 8890
        cfg["global_settings"]["proxy_client_network_name"] = "chamosel-clients"

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())

        self.assertNotIn("0.0.0.0:8890:8890/tcp", compose["services"]["haproxy"]["ports"])
        self.assertNotIn("8890:8890/tcp", compose["services"]["haproxy"]["ports"])
        self.assertIn("127.0.0.1:8404:8404/tcp", compose["services"]["haproxy"]["ports"])
        self.assertEqual(
            {"aliases": ["chamosel-proxy"]},
            compose["services"]["haproxy"]["networks"]["proxy-client-net"],
        )

    def test_proxy_client_network_empty_alias_uses_default(self):
        cfg = self.base_config()
        cfg["global_settings"]["proxy_client_network_name"] = "chamosel-clients"
        cfg["global_settings"]["proxy_client_network_alias"] = ""

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())

        self.assertEqual(
            {"aliases": ["chamosel-proxy"]},
            compose["services"]["haproxy"]["networks"]["proxy-client-net"],
        )

    def test_proxy_client_network_rejects_invalid_name(self):
        cfg = self.base_config()
        cfg["global_settings"]["proxy_client_network_name"] = "../bad"

        with self.assertLogs("chamosel", level="ERROR") as logs:
            with self.assertRaises(SystemExit):
                self.chamosel.generate(cfg)

        rendered = "\n".join(logs.output)
        self.assertIn("proxy_client_network_name", rendered)
        self.assertNotIn("config-secret", rendered)

    def test_explicit_remote_bind_requires_controller_auth(self):
        cfg = self.base_config()
        cfg["global_settings"]["api_bind"] = "0.0.0.0"
        cfg["global_settings"]["stats_bind"] = "0.0.0.0"

        with self.assertLogs("chamosel", level="ERROR") as logs:
            with self.assertRaises(SystemExit):
                self.chamosel.generate(cfg)

        self.assertNotIn("config-secret", "\n".join(logs.output))

    def test_public_proxy_requires_explicit_allowlist(self):
        cfg = self.base_config()
        cfg["global_settings"]["proxy_bind"] = "0.0.0.0"

        with self.assertLogs("chamosel", level="ERROR") as logs:
            with self.assertRaises(SystemExit):
                self.chamosel.generate(cfg)

        rendered = "\n".join(logs.output)
        self.assertIn("allow_public_proxy", rendered)
        self.assertNotIn("config-secret", rendered)

    def test_proxy_publish_false_does_not_require_public_proxy_allowlist(self):
        cfg = self.base_config()
        cfg["global_settings"]["proxy_publish"] = False
        cfg["global_settings"]["proxy_bind"] = "0.0.0.0"

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())

        self.assertNotIn("0.0.0.0:8888:8888/tcp", compose["services"]["haproxy"]["ports"])

    def test_proxy_publish_false_does_not_render_host_proxy_acl(self):
        cfg = self.base_config()
        cfg["global_settings"]["proxy_publish"] = False
        cfg["global_settings"]["proxy_client_network_name"] = "chamosel-clients"
        cfg["global_settings"]["proxy_allowed_cidrs"] = "10.20.20.0/24"

        self.chamosel.generate(cfg)
        haproxy = Path("haproxy.cfg").read_text()

        self.assertNotIn("acl allowed_proxy_src", haproxy)
        self.assertNotIn("tcp-request connection reject unless allowed_proxy_src", haproxy)

    def test_public_stats_requires_auth_or_allowlist(self):
        cfg = self.base_config()
        cfg["global_settings"]["stats_bind"] = "0.0.0.0"

        with self.assertLogs("chamosel", level="ERROR") as logs:
            with self.assertRaises(SystemExit):
                self.chamosel.generate(cfg)

        rendered = "\n".join(logs.output)
        self.assertIn("stats_auth_user", rendered)
        self.assertNotIn("config-secret", rendered)

    def test_explicit_remote_bind_renders_when_controller_auth_enabled(self):
        cfg = self.base_config()
        cfg["global_settings"]["api_bind"] = "0.0.0.0"
        cfg["global_settings"]["controller_auth_enabled"] = True
        cfg["global_settings"]["controller_auth_token"] = "controller-secret"

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())

        env_text = Path(".env").read_text()
        controller_env = compose["services"]["controller"]["environment"]
        self.assertIn("CONTROLLER_AUTH_TOKEN=controller-secret\n", env_text)
        self.assertEqual("true", controller_env["CONTROLLER_AUTH_ENABLED"])
        self.assertEqual("${CONTROLLER_AUTH_TOKEN}", controller_env["CONTROLLER_AUTH_TOKEN"])
        self.assertIn("127.0.0.1:8888:8888/tcp", compose["services"]["haproxy"]["ports"])
        self.assertIn("0.0.0.0:8800:8800/tcp", compose["services"]["controller"]["ports"])
        self.assertIn("127.0.0.1:8404:8404/tcp", compose["services"]["haproxy"]["ports"])

    def test_explicit_proxy_bind_renders_independently_from_api_bind(self):
        cfg = self.base_config()
        cfg["global_settings"]["proxy_bind"] = "10.20.20.3"
        cfg["global_settings"]["api_bind"] = "127.0.0.1"
        cfg["global_settings"]["proxy_port"] = 8890
        cfg["global_settings"]["allow_public_proxy"] = True
        cfg["global_settings"]["proxy_allowed_cidrs"] = "10.20.20.0/24"

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())

        self.assertIn("10.20.20.3:8890:8890/tcp", compose["services"]["haproxy"]["ports"])
        self.assertIn("127.0.0.1:8800:8800/tcp", compose["services"]["controller"]["ports"])
        haproxy = Path("haproxy.cfg").read_text()
        self.assertIn("acl allowed_proxy_src src 10.20.20.0/24", haproxy)
        self.assertIn("tcp-request connection reject unless allowed_proxy_src", haproxy)

    def test_generated_env_permissions_are_restrictive(self):
        self.chamosel.generate(self.base_config())

        mode = Path(".env").stat().st_mode & 0o777

        self.assertEqual(0o600, mode)

    def test_broad_env_local_permissions_warn_without_secret_value(self):
        cfg = self.base_config()
        cfg["global_settings"]["env_file"] = ".env.local"
        Path(".env.local").write_text("CONTROLLER_AUTH_TOKEN=local-controller-secret\n")
        os.chmod(".env.local", 0o644)

        with self.assertLogs("chamosel", level="WARNING") as logs:
            self.chamosel.generate(cfg)

        rendered = "\n".join(logs.output)
        self.assertIn("chmod 600 .env.local", rendered)
        self.assertNotIn("local-controller-secret", rendered)

    def test_controller_auth_token_can_come_from_env_local(self):
        cfg = self.base_config()
        cfg["global_settings"]["api_bind"] = "0.0.0.0"
        cfg["global_settings"]["controller_auth_enabled"] = True
        cfg["global_settings"]["env_file"] = ".env.local"
        Path(".env.local").write_text("CONTROLLER_AUTH_TOKEN=local-controller-secret\n")

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())

        env_text = Path(".env").read_text()
        controller_env = compose["services"]["controller"]["environment"]
        self.assertIn("CONTROLLER_AUTH_TOKEN=local-controller-secret\n", env_text)
        self.assertEqual("true", controller_env["CONTROLLER_AUTH_ENABLED"])
        self.assertEqual("${CONTROLLER_AUTH_TOKEN}", controller_env["CONTROLLER_AUTH_TOKEN"])
        self.assertEqual(
            {"X-Chamosel-Auth": "local-controller-secret"},
            self.chamosel.controller_auth_headers(cfg),
        )

    def test_controller_auth_env_local_and_config_conflict_fails(self):
        cfg = self.base_config()
        cfg["global_settings"]["api_bind"] = "0.0.0.0"
        cfg["global_settings"]["controller_auth_enabled"] = True
        cfg["global_settings"]["env_file"] = ".env.local"
        cfg["global_settings"]["controller_auth_token"] = "config-controller-secret"
        Path(".env.local").write_text("CONTROLLER_AUTH_TOKEN=local-controller-secret\n")

        with self.assertLogs("chamosel", level="ERROR") as logs:
            with self.assertRaises(SystemExit):
                self.chamosel.generate(cfg)

        rendered_logs = "\n".join(logs.output)
        self.assertNotIn("local-controller-secret", rendered_logs)
        self.assertNotIn("config-controller-secret", rendered_logs)

    def test_provider_env_file_renders_when_configured(self):
        cfg = self.base_config()
        cfg["global_settings"]["env_file"] = ".env.local"
        cfg["vpn_providers"]["surfshark"]["env"].pop("WIREGUARD_PRIVATE_KEY")

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())
        service = compose["services"]["surfshark_0"]

        self.assertEqual([".env.local"], service["env_file"])
        self.assertNotIn("WIREGUARD_PRIVATE_KEY", service["environment"])

    def test_gluetun_dns_upstream_overrides_are_opt_in(self):
        self.chamosel.generate(self.base_config())
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())
        env = compose["services"]["surfshark_0"]["environment"]

        self.assertNotIn("DNS_UPSTREAM_RESOLVER_TYPE", env)
        self.assertNotIn("DNS_UPSTREAM_RESOLVERS", env)
        self.assertNotIn("DNS_UPSTREAM_PLAIN_ADDRESSES", env)

    def test_unsafe_egress_target_is_rejected(self):
        cfg = self.base_config()
        cfg["global_settings"]["egress_verify_target"] = "http://169.254.169.254/latest/meta-data"

        with self.assertLogs("chamosel", level="ERROR") as logs:
            with self.assertRaises(SystemExit):
                self.chamosel.generate(cfg)

        self.assertIn("egress_verify_target", "\n".join(logs.output))

    def test_gluetun_dns_upstream_overrides_render_when_configured(self):
        cfg = self.base_config()
        cfg["global_settings"]["dns_upstream_resolvers"] = "quad9,cloudflare"
        cfg["global_settings"]["dns_upstream_resolver_type"] = "dot"

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())
        env = compose["services"]["surfshark_0"]["environment"]

        self.assertEqual("dot", env["DNS_UPSTREAM_RESOLVER_TYPE"])
        self.assertEqual("quad9,cloudflare", env["DNS_UPSTREAM_RESOLVERS"])
        self.assertNotIn("DNS_UPSTREAM_PLAIN_ADDRESSES", env)

    def test_provider_plain_dns_sets_plain_resolver_type(self):
        cfg = self.base_config()
        cfg["global_settings"]["dns_upstream_plain_addresses"] = "10.14.0.1:53"

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())
        env = compose["services"]["surfshark_0"]["environment"]

        self.assertEqual("plain", env["DNS_UPSTREAM_RESOLVER_TYPE"])
        self.assertEqual("10.14.0.1:53", env["DNS_UPSTREAM_PLAIN_ADDRESSES"])
        self.assertNotIn("DNS_UPSTREAM_RESOLVERS", env)

    def test_controller_reliability_settings_render(self):
        cfg = self.base_config()
        cfg["global_settings"]["rotate_all_batch_size"] = 3
        cfg["global_settings"]["rotate_all_batch_delay_seconds"] = 5
        cfg["global_settings"]["pool_degraded_min_healthy"] = 2
        cfg["global_settings"]["auto_repair_duplicate_ips"] = False
        cfg["global_settings"]["duplicate_repair_retry_cooldown"] = 180
        cfg["global_settings"]["egress_verify_target"] = "https://ifconfig.co/json"
        cfg["global_settings"]["egress_verify_timeout"] = 12
        cfg["global_settings"]["egress_verify_ttl"] = 90
        cfg["global_settings"]["egress_verify_on_fresh"] = False
        cfg["global_settings"]["dashboard_refresh_seconds"] = 15

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())
        env = compose["services"]["controller"]["environment"]

        self.assertEqual("3", env["ROTATE_ALL_BATCH_SIZE"])
        self.assertEqual("5", env["ROTATE_ALL_BATCH_DELAY_SECONDS"])
        self.assertEqual("2", env["POOL_DEGRADED_MIN_HEALTHY"])
        self.assertEqual("false", env["AUTO_REPAIR_DUPLICATE_IPS"])
        self.assertEqual("180", env["DUPLICATE_REPAIR_RETRY_COOLDOWN"])
        self.assertEqual("https://ifconfig.co/json", env["EGRESS_VERIFY_TARGET"])
        self.assertEqual("12", env["EGRESS_VERIFY_TIMEOUT"])
        self.assertEqual("90", env["EGRESS_VERIFY_TTL"])
        self.assertEqual("15", env["DASHBOARD_REFRESH_SECONDS"])
        self.assertEqual("http://127.0.0.1:8404/stats", env["DASHBOARD_STATS_URL"])
        self.assertEqual("false", env["EGRESS_VERIFY_ON_FRESH"])
        self.assertEqual("false", env["CONTROLLER_AUTH_ENABLED"])

    def test_cmd_up_pulls_runtime_images_by_default(self):
        calls = []
        self.chamosel.generate = lambda cfg: calls.append(("generate", None))
        self.chamosel.compose_cmd = lambda args, capture=False: calls.append(("compose", args))

        self.chamosel.cmd_up(self.base_config())

        self.assertEqual(
            [
                ("generate", None),
                ("compose", ["pull", "--ignore-buildable"]),
                ("compose", ["up", "-d", "--build", "--remove-orphans", "--force-recreate"]),
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
                ("compose", ["up", "-d", "--build", "--remove-orphans", "--force-recreate"]),
            ],
            calls,
        )

    def test_cmd_up_logs_configured_bind_addresses(self):
        cfg = self.base_config()
        cfg["global_settings"].update(
            {
                "api_bind": "10.20.20.3",
                "proxy_bind": "10.20.20.5",
                "stats_bind": "10.20.20.4",
                "proxy_port": 8890,
                "api_port": 8801,
                "stats_port": 8405,
            }
        )
        self.chamosel.generate = lambda cfg: None
        self.chamosel.compose_cmd = lambda args, capture=False: None

        with self.assertLogs("chamosel", level="INFO") as logs:
            self.chamosel.cmd_up(cfg, pull_images=False)

        rendered_logs = "\n".join(logs.output)
        self.assertIn("Proxy http://10.20.20.5:8890", rendered_logs)
        self.assertIn("API+dashboard http://10.20.20.3:8801", rendered_logs)
        self.assertIn("Stats http://10.20.20.4:8405/stats", rendered_logs)

    def test_cmd_up_logs_client_network_proxy_when_host_publish_disabled(self):
        cfg = self.base_config()
        cfg["global_settings"].update(
            {
                "proxy_publish": False,
                "proxy_port": 8890,
                "proxy_client_network_name": "chamosel-clients",
                "proxy_client_network_alias": "chamosel-proxy",
            }
        )
        self.chamosel.generate = lambda cfg: None
        self.chamosel.compose_cmd = lambda args, capture=False: None

        with self.assertLogs("chamosel", level="INFO") as logs:
            self.chamosel.cmd_up(cfg, pull_images=False)

        rendered_logs = "\n".join(logs.output)
        self.assertIn("Proxy http://chamosel-proxy:8890 (network chamosel-clients)", rendered_logs)

    def test_controller_stats_url_uses_configured_stats_bind(self):
        cfg = self.base_config()
        cfg["global_settings"]["stats_bind"] = "10.20.20.4"
        cfg["global_settings"]["stats_port"] = 8405
        cfg["global_settings"]["stats_auth_user"] = "ops"
        cfg["global_settings"]["stats_auth_password"] = "stats-secret"

        self.chamosel.generate(cfg)
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())
        env = compose["services"]["controller"]["environment"]

        self.assertEqual("http://10.20.20.4:8405/stats", env["DASHBOARD_STATS_URL"])
        haproxy = Path("haproxy.cfg").read_text()
        self.assertIn("stats auth ops:stats-secret", haproxy)

    def test_compose_cmd_sanitizes_missing_plugin_help_output(self):
        leaked_help = (
            "docker: 'compose' is not a docker command.\n"
            "Location of client config files (default \"/home/private-user/.docker\")\n"
        )

        def fake_run(*args, **kwargs):
            return self.chamosel.subprocess.CompletedProcess(args[0], 125, stderr=leaked_help)

        self.chamosel.subprocess.run = fake_run

        with self.assertLogs("chamosel", level="ERROR") as logs:
            with self.assertRaises(SystemExit):
                self.chamosel.compose_cmd(["pull", "--ignore-buildable"])

        rendered_logs = "\n".join(logs.output)
        self.assertIn("Docker Compose v2 plugin is not available", rendered_logs)
        self.assertNotIn("/home/private-user", rendered_logs)

    def test_compose_cmd_streams_docker_output_when_not_capturing(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return self.chamosel.subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

        self.chamosel.subprocess.run = fake_run

        self.chamosel.compose_cmd(["pull", "--ignore-buildable"])

        self.assertEqual(["docker", "compose", "version"], calls[0][0])
        self.assertTrue(calls[0][1]["capture_output"])
        self.assertEqual(["docker", "compose", "-f", "docker-compose.yml", "pull", "--ignore-buildable"], calls[1][0])
        self.assertFalse(calls[1][1]["capture_output"])

    def test_controller_image_migrates_state_volume_then_drops_privileges(self):
        dockerfile = (ROOT / "controller" / "Dockerfile").read_text()
        entrypoint = (ROOT / "controller" / "entrypoint.sh").read_text()

        self.assertIn("apk add --no-cache su-exec", dockerfile)
        self.assertIn("ENTRYPOINT [\"/entrypoint.sh\"]", dockerfile)
        self.assertIn("chown -R chamosel:chamosel /data", entrypoint)
        self.assertIn("exec su-exec chamosel python controller.py", entrypoint)

    def test_controller_has_chown_capability_for_state_volume_migration(self):
        self.chamosel.generate(self.base_config())
        compose = yaml.safe_load(Path("docker-compose.yml").read_text())
        controller = compose["services"]["controller"]

        self.assertEqual(["ALL"], controller["cap_drop"])
        self.assertEqual(["CHOWN"], controller["cap_add"])

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
