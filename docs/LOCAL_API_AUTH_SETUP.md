# Local access policy

NEXUS STUDIO PRO runs in passwordless mode by default. Both the FastAPI Browser Studio and Streamlit Studio open directly without an operator login.

## Default local mode

- NEXUS_AUTH_ENABLED=false is the default (also used when the variable is omitted).
- No operator password or session signing secret is required.
- Browser Studio: http://127.0.0.1:28503
- Streamlit Studio: http://127.0.0.1:28502
- Docker Compose binds both ports to loopback only. Do not expose them to a LAN or public network.
- Existing .env password/session values may remain in place; they are ignored while authentication is disabled. Do not overwrite or delete existing secrets as part of this change.

## Optional authentication

Authentication can be explicitly re-enabled by setting the following in the repository-root .env:

```dotenv
NEXUS_AUTH_ENABLED=true
NEXUS_API_PASSWORD=replace-with-a-unique-password-of-at-least-12-characters
NEXUS_SESSION_SECRET=replace-with-a-separate-random-secret-of-at-least-32-characters
NEXUS_COOKIE_SECURE=false
```

When enabled:
- FastAPI issues a 12-hour HMAC-signed HttpOnly/SameSite=Strict cookie.
- API endpoints and /output/* media require a valid session.
- Streamlit requires the same operator password and keeps its own server-side session.
- Missing or invalid credentials fail closed.
- Use NEXUS_COOKIE_SECURE=true only behind HTTPS.

## Network and safety boundaries

- Loopback-only host binding remains enabled regardless of the authentication setting.
- Cross-origin mutation checks remain active.
- Existing database, generated videos, OAuth tokens, and .env are not changed by switching the authentication mode.
- YouTube publishing remains human-approved and Private by default. Public publishing is not automated.
