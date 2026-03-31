"""
QBO OAuth 2.0 authentication handler.

First run: opens browser for you to authorize, saves tokens to .env.
Subsequent runs: uses refresh token (auto-refreshes if expired).
"""

import os
import sys
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv, set_key
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes

load_dotenv()

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def get_auth_client():
    return AuthClient(
        client_id=os.getenv("QBO_CLIENT_ID"),
        client_secret=os.getenv("QBO_CLIENT_SECRET"),
        redirect_uri=os.getenv("QBO_REDIRECT_URI", "http://localhost:8080/callback"),
        environment=os.getenv("QBO_ENVIRONMENT", "sandbox"),
    )


def get_tokens():
    """Get a valid access token, refreshing if needed."""
    auth_client = get_auth_client()
    refresh_token = os.getenv("QBO_REFRESH_TOKEN")

    if not refresh_token:
        print("No refresh token found. Run: python qbo_auth.py")
        sys.exit(1)

    auth_client.refresh(refresh_token=refresh_token)

    # Save the new refresh token
    set_key(ENV_PATH, "QBO_REFRESH_TOKEN", auth_client.refresh_token)

    return auth_client


class CallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth callback from Intuit."""

    auth_code = None
    realm_id = None

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        CallbackHandler.auth_code = query.get("code", [None])[0]
        CallbackHandler.realm_id = query.get("realmId", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Authorization successful!</h2>"
            b"<p>You can close this tab and return to the terminal.</p>"
            b"</body></html>"
        )

    def log_message(self, format, *args):
        pass  # Suppress server logs


def initial_auth():
    """Run the full OAuth flow (first time setup)."""
    client_id = os.getenv("QBO_CLIENT_ID")
    client_secret = os.getenv("QBO_CLIENT_SECRET")

    if not client_id or not client_secret or "your_" in (client_id or ""):
        print("ERROR: Set QBO_CLIENT_ID and QBO_CLIENT_SECRET in .env first.")
        print("  1. Copy .env.example to .env")
        print("  2. Fill in your credentials from developer.intuit.com")
        sys.exit(1)

    auth_client = get_auth_client()
    auth_url = auth_client.get_authorization_url([Scopes.ACCOUNTING])

    print(f"\nOpening browser for authorization...")
    print(f"If it doesn't open, go to:\n{auth_url}\n")
    webbrowser.open(auth_url)

    # Start local server to catch the callback
    server = HTTPServer(("localhost", 8080), CallbackHandler)
    print("Waiting for authorization callback...")
    server.handle_request()

    if not CallbackHandler.auth_code:
        print("ERROR: No authorization code received.")
        sys.exit(1)

    # Exchange code for tokens
    auth_client.get_bearer_token(CallbackHandler.auth_code, realm_id=CallbackHandler.realm_id)

    # Save to .env
    set_key(ENV_PATH, "QBO_REALM_ID", CallbackHandler.realm_id)
    set_key(ENV_PATH, "QBO_REFRESH_TOKEN", auth_client.refresh_token)

    print(f"\nAuthorization successful!")
    print(f"  Company ID (Realm): {CallbackHandler.realm_id}")
    print(f"  Tokens saved to .env")
    print(f"\nYou're ready to use mark_paid.py")


if __name__ == "__main__":
    initial_auth()
