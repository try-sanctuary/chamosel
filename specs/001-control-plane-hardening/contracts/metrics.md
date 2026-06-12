# Contract: Metrics

Existing metrics remain:

```text
chamosel_instances_total
chamosel_instances_healthy
chamosel_rotations_total
chamosel_rotation_errors_total
chamosel_instance_healthy{instance="..."}
chamosel_instance_rotations_total{instance="..."}
```

## Clarified Semantics

- `chamosel_rotations_total` counts only rotations that reach usable health
  within 30 seconds.
- `chamosel_instance_rotations_total` follows the same success-only rule.
- `chamosel_rotation_errors_total` increments for command errors, authorization
  failures, unsupported control endpoints, and recovery timeouts.

## Additional Metrics

The implementation should expose enough signal to distinguish failure classes.
Recommended metrics:

```text
chamosel_rotation_errors_by_outcome_total{outcome="..."}
chamosel_instance_rotation_errors_by_outcome_total{instance="...",outcome="..."}
chamosel_instance_status{instance="...",status="..."}
```

Allowed `outcome` labels:

- `command_error`
- `recovery_timeout`
- `unauthorized`
- `unsupported_control`
- `control_unreachable`

Allowed `status` labels:

- `healthy`
- `reconnecting`
- `unreachable`
- `unauthorized`
- `unsupported_control`

At most one `chamosel_instance_status` series per instance should be `1` at a
time; all other statuses for that instance should be `0` or omitted consistently.
