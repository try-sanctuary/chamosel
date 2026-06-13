# Contract: Controller Authentication

## Protected surfaces

When controller authentication is enabled, the following surfaces require a valid operator token:

- `GET /`
- `GET /pool`
- `GET /pool?fresh=1`
- `GET /metrics`
- `POST /rotate`
- `POST /rotate/<name>`
- `POST /rotate/all`
- repair endpoints or repair-triggering calls added by this feature

## Request contract

Authenticated requests provide the configured token in an HTTP header.

Missing or invalid credentials return:

```json
{
  "error": "unauthorized"
}
```

Requirements:
- The response must not disclose whether a token exists or what the expected token is.
- Protected POST requests must not execute when auth fails.
- CLI calls must attach credentials automatically when configured.

## Configuration contract

Operator-facing configuration must support:

- enabling/disabling controller authentication
- supplying the controller auth token without logging it
- warning/failing safely when auth is disabled on a non-loopback bind

The controller/gluetun API key remains separate from controller operator authentication.
