# Local access policy

NEXUS STUDIO PRO is passwordless by default for a local-only deployment. FastAPI and Streamlit open directly without an operator login.

## Default local mode

- `NEXUS_AUTH_ENABLED=false` is the default when the variable is omitted.
- Docker Compose binds the service ports to `127.0.0.1` only: FastAPI `28503`, Streamlit `28502`.
- Do not expose these ports to a LAN or public network.
- Existing `.env` password and session-secret values are preserved; they are ignored while authentication is disabled.
- The browser session-status endpoint reports `required=false`; the UI starts without a login overlay.

## Optional authenticated mode

Set the following values in the repository-local `.env`:

```dotenv
NEXUS_AUTH_ENABLED=true
NEXUS_API_PASSWORD=<unique password of at least 12 characters>
NEXUS_SESSION_SECRET=<independent random secret of at least 32 characters>
NEXUS_COOKIE_SECURE=false
```

Use `NEXUS_COOKIE_SECURE=true` only behind HTTPS. FastAPI then requires a signed 12-hour HttpOnly/SameSite=Strict session cookie for API and `/output/*` media. Streamlit uses the same password in a separate server-side session. Invalid or missing credentials fail closed before protected operations or data initialization.

## Windows PowerShell setup and verification

```powershell
pwsh -File .\\scripts\\setup-local-nexus.ps1
pwsh -File .\\scripts\\setup-local-nexus.ps1 -Start
pwsh -File .\\scripts\\verify-local-nexus.ps1
```

The setup script preserves existing `.env` entries and does not print secrets. Inspect existing containers and ports before startup; do not remove the legacy runtime, volumes, database, generated videos, or OAuth tokens.

## Security boundary

Passwordless mode is intended only for loopback-bound local development. Keep Docker host bindings on `127.0.0.1`; do not deploy this mode to a network-accessible host. Cross-origin mutation checks remain enabled. Uploads still require explicit human approval and remain private by default.
