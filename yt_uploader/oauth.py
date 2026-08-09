"""OAuth credentials for YouTube, reusing the proven approach from
the "let me paint please" project (verticals/upload.py + setup_youtube_oauth.py):
- token loaded via Credentials.from_authorized_user_file
- refreshed via Request() when expired and saved back
- created via InstalledAppFlow.run_local_server(port=0) when missing
- token files written with 0600 permissions
"""

import json
import os
import stat
from pathlib import Path

from .config import CLIENT_SECRET, SCOPES, TOKEN_PATH
from .logger import log, warn, fail


class OAuthError(RuntimeError):
    pass


def write_secret_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)


def run_oauth_flow() -> object:
    """Interactive one-time authorization; returns fresh credentials."""
    if not CLIENT_SECRET.exists():
        raise OAuthError(
            f"client_secret.json not found at {CLIENT_SECRET}. "
            "Get it from Google Cloud Console (OAuth 2.0 Client ID, Desktop app)."
        )
    from google_auth_oauthlib.flow import InstalledAppFlow

    log("Opening browser for Google sign-in (one-time authorization)...")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0)
    write_secret_file(TOKEN_PATH, creds.to_json())
    log(f"OAuth token saved to {TOKEN_PATH}")
    return creds


def _load_or_refresh() -> object:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not TOKEN_PATH.exists():
        return run_oauth_flow()

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    if creds.expired:
        if creds.refresh_token:
            creds.refresh(Request())
            write_secret_file(TOKEN_PATH, creds.to_json())
            log("OAuth token refreshed")
        else:
            raise OAuthError(
                "YouTube OAuth token is expired and has no refresh token.\n"
                f"Delete {TOKEN_PATH} and re-run: python -m yt_uploader.setup_oauth"
            )
    return creds


def get_credentials() -> object:
    """Return valid credentials, recovering (fresh browser flow) when the
    saved token is missing or revoked. Failures are raised as OAuthError."""
    try:
        return _load_or_refresh()
    except OAuthError:
        raise
    except Exception as exc:
        warn(f"Token unusable ({exc}); re-authorizing from scratch")
        TOKEN_PATH.unlink(missing_ok=True)
        return run_oauth_flow()


def token_summary() -> str:
    if not TOKEN_PATH.exists():
        return "no token yet"
    try:
        data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        client = data.get("client_id", "?")
        scope = ",".join(data.get("scopes", [])) or "?"
        refresh = "yes" if data.get("refresh_token") else "no"
        return f"client_id={client} scopes=[{scope}] refresh_token={refresh}"
    except Exception:
        return "unreadable token file"
