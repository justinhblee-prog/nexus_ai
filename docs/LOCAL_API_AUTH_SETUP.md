# Local API authentication setup

The browser studio API and generated preview media now require a signed, HttpOnly browser session. The login page itself remains accessible so the operator can authenticate. Streamlit and API ports remain bound to loopback by Docker Compose.

## Configure local secrets

1. Copy `.env.example` to `.env` in the repository root.
2. Replace `NEXUS_API_PASSWORD` with a unique password of at least 12 characters.
3. Replace `NEXUS_SESSION_SECRET` with a unique random secret of at least 32 characters. Generate one with:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   Run the command separately for the session secret; do not reuse the login password.
4. Keep `NEXUS_COOKIE_SECURE=false` for the default localhost HTTP setup. Set it to `true` only when the browser accesses the service over HTTPS.
5. Rebuild and restart the local stack:

   ```powershell
   docker compose up -d --build
   ```

6. Open `http://127.0.0.1:8503` and sign in with the configured API password.

The repository ignores `.env`; never commit it or paste its values into an issue, PR, or chat.

## Session and protection behavior

- Successful login issues a 12-hour HMAC-signed cookie with `HttpOnly`, `SameSite=Strict`, and path `/`.
- The browser does not store the password or a bearer token in local/session storage.
- API endpoints and `/output/*` preview media reject requests without a valid session.
- Session status, login, and logout routes remain available to the login screen.
- Invalid or missing configuration fails closed with HTTP 503; unauthenticated protected requests return HTTP 401.
- Existing local-origin checks remain active for state-changing requests.
- Docker Compose continues to bind ports 8502 and 8503 to `127.0.0.1`; do not expose them publicly.

## Scope and limitations

This adds authentication to the FastAPI-backed browser studio and its generated media. The separate Streamlit interface is still intended for loopback-only local access and does not yet have its own login screen. API credentials must be configured before the browser studio can operate. Local Docker/browser end-to-end verification is still required after applying the `.env` values.