"""
QBO OAuth 2.0 authentication handler.

First run: gives you a URL to visit, you paste back the redirect URL.
Subsequent runs: uses refresh token (auto-refreshes if expired).
"""

import os
import sys
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

    print(f"\n=== QBO Authorization ===\n")
    print(f"1. Open this URL in any browser:\n")
    print(f"   {auth_url}\n")
    print(f"2. Log into QuickBooks and authorize the app.")
    print(f"3. You'll be redirected to a URL that probably won't load (that's fine).")
    print(f"4. Copy the FULL URL from your browser's address bar and paste it here.\n")

    redirect_url = input("Paste the redirect URL here: ").strip()

    # Parse the auth code and realm ID from the redirect URL
    parsed = urlparse(redirect_url)
    query = parse_qs(parsed.query)

    auth_code = query.get("code", [None])[0]
    realm_id = query.get("realmId", [None])[0]

    if not auth_code:
        print("ERROR: Could not find authorization code in that URL.")
        print("  Make sure you copied the full URL from the address bar.")
        sys.exit(1)

    if not realm_id:
        print("ERROR: Could not find realmId in that URL.")
        sys.exit(1)

    # Exchange code for tokens
    auth_client.get_bearer_token(auth_code, realm_id=realm_id)

    # Save to .env
    set_key(ENV_PATH, "QBO_REALM_ID", realm_id)
    set_key(ENV_PATH, "QBO_REFRESH_TOKEN", auth_client.refresh_token)

    print(f"\nAuthorization successful!")
    print(f"  Company ID (Realm): {realm_id}")
    print(f"  Tokens saved to .env")
    print(f"\nYou're all set. The MCP server is ready to use.")


if __name__ == "__main__":
    initial_auth()
