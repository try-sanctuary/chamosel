# Contract: Controller API

## `GET /pool`

Returns the cached pool snapshot.

Required top-level fields:

```json
{
  "count": 2,
  "healthy": 1,
  "rotations_total": 3,
  "rotation_errors_total": 1,
  "instances": []
}
```

Required instance fields:

```json
{
  "name": "surfshark_0",
  "healthy": true,
  "status": "healthy",
  "public_ip": "203.0.113.10",
  "ip_history": ["203.0.113.10"],
  "rotations": 2,
  "rotation_errors": 0,
  "last_rotated": 1781294400.0,
  "last_seen": 1781294402.0,
  "status_path": "/v1/vpn/status",
  "last_error": null
}
```

Allowed `status` values:

- `healthy`
- `reconnecting`
- `unreachable`
- `unauthorized`
- `unsupported_control`

## `GET /pool?fresh=1`

Forces a live refresh. Stale cached status paths must be re-detected when the
cached path no longer works.

## `POST /rotate`

Rotates one eligible instance.

Success response:

```json
{
  "instance": "surfshark_0",
  "ok": true,
  "outcome": "success",
  "old_ip": "203.0.113.10",
  "new_ip": "198.51.100.20",
  "elapsed_seconds": 12.4,
  "message": "rotation recovered"
}
```

Recovery timeout response:

```json
{
  "instance": "surfshark_0",
  "ok": false,
  "outcome": "recovery_timeout",
  "old_ip": "203.0.113.10",
  "new_ip": null,
  "elapsed_seconds": 30.0,
  "message": "instance did not reach usable health within 30s"
}
```

Other allowed outcomes:

- `cooldown`
- `unknown_instance`
- `command_error`
- `unauthorized`
- `unsupported_control`

## `POST /rotate/<name>`

Rotates the named instance with forced cooldown override. Unknown names return
`ok=false` and `outcome=unknown_instance`.

## `POST /rotate/all`

Rotates all configured instances sequentially and returns one `Rotation Outcome`
per instance.
