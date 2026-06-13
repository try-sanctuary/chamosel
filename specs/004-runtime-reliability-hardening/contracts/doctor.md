# Doctor CLI Contract

## Command

```bash
python3 chamosel.py doctor
python3 chamosel.py doctor --json
```

## JSON Shape

```json
{
  "ok": true,
  "configured_instances": 5,
  "pool_status": "healthy",
  "healthy_backends": 5,
  "backend_count": 5,
  "checks": {
    "compose_stack": {"ok": true},
    "controller_health": {"ok": true},
    "pool_fresh": {"ok": true, "state_fresh": true},
    "haproxy_stats_port": {"ok": true},
    "env_local": {"ok": true},
    "image_freshness": {"ok": true}
  }
}
```

Secret values are excluded from every field.

