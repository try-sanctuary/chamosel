# Quickstart: Runtime Reliability Hardening

```bash
python3 chamosel.py generate
python3 chamosel.py up
python3 chamosel.py doctor
python3 chamosel.py doctor --json
python3 chamosel.py status
curl localhost:8800/pool | jq '.pool_status,.state_fresh,.degraded_reasons'
curl localhost:8800/metrics | rg 'chamosel_pool_status|chamosel_state_fresh'
```

Conservative live validation:

```bash
python3 chamosel.py verify-leaks
python3 chamosel.py stress --iterations 10 --mode leak-only
python3 chamosel.py stress --iterations 1 --mode rotation --no-verify
```

Recommended Surfshark live config:

```yaml
global_settings:
  rotate_cooldown: 60
  rotation_recovery_timeout: 60
  rotate_all_batch_size: 2
  rotate_all_batch_delay_seconds: 2

vpn_providers:
  surfshark:
    num_containers: 5
```

