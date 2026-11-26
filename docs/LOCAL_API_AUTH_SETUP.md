# Local authentication setup

The FastAPI browser studio and the separate Streamlit interface both require the same operator password. FastAPI uses a signed, HttpOnly browser session for API and preview media. Streamlit gates its UI with server-side session state. Docker Compose binds both ports to loopback only.

## Configure local secrets

1. Create or update `.env` in the repository root.
2. Set `NEXUS_API_PASSWORD` to a unique password of at least 12 characters. This password is shared by both local UI entry points.
3. Set `NEXUS_SESSION_SECRET` to a separate random secret of at least 32 characters. Generate it with:
   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
4. Keep `NEXUS_COOKIE_SECURE=false` for localhost HTTP. Set it to `true` only when using HTTPS.
5. Start or update the stack using the repository's existing Docker Compose configuration. Do not remove volumes or reset the database.
6. Sign in to the browser studio at `http://127.0.0.1:8503`.
7. Sign in to the Streamlit studio at `http://127.0.0.1:8502` using the same password.

The repository ignores `.env`. Never commit it or paste its values into an issue, PR, or chat.

## FastAPI browser session

- Successful login issues a 12-hour HMAC-signed cookie with `HttpOnly`, `SameSite=Strict`, and path `/`.
- The browser does not store the password or a bearer token in local/session storage.
- API endpoints and `/output/*` preview media reject requests without a valid session.
- Session status, login, and logout routes remain available to the login screen.
- Missing or invalid authentication configuration fails closed with HTTP 503. Unauthenticated protected requests return HTTP 401.
- Existing local-origin checks remain active for state-changing requests.

## Streamlit UI session

- Streamlit requires the same `NEXUS_API_PASSWORD`; passwords shorter than 12 characters fail closed.
- Password comparison uses `hmac.compare_digest`.
- The authentication gate runs before directory creation, database opening, or the topic watcher startup.
- Successful authentication is stored in server-side Streamlit session state. The UI provides an explicit logout action.
- Streamlit's session is separate from the FastAPI signed cookie; signing in to one interface does not sign in to the other.

## Network and verification boundaries

- Docker Compose binds ports `8502` and `8503` to `127.0.0.1`. Do not expose them publicly.
- Automated unit tests cover the password helper and FastAPI session enforcement.
- Local Docker startup, browser login, actual rendering, feed availability, and end-to-end OAuth/private upload still require verification on the Windows host. GitHub Actions success does not substitute for those local runtime checks.
- YouTube upload remains a human-approved action and is configured to remain private. Public publishing is not automated.
