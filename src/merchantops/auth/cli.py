from __future__ import annotations

import argparse
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx

from merchantops.auth.oauth import ZohoOAuth, build_authorization_url
from merchantops.auth.store import TokenStore
from merchantops.config import Settings
from merchantops.errors import ConfigError, UnauthorizedError


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Store a Zoho Inventory refresh token for MerchantOps.")
    parser.add_argument("command", choices=["login", "url"])
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "url":
        url, _state = build_authorization_url(
            dc=settings.zoho_dc,
            client_id=settings.client_id,
            redirect_uri=settings.redirect_uri,
        )
        print(url)
        return
    import asyncio

    asyncio.run(_login(settings))


async def _login(settings: Settings) -> None:
    store = TokenStore(settings.token_store_path, settings.token_encryption_key)
    url, state = build_authorization_url(
        dc=settings.zoho_dc,
        client_id=settings.client_id,
        redirect_uri=settings.redirect_uri,
    )
    parsed = urlparse(settings.redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/callback"
    code_holder: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            request = urlparse(self.path)
            if request.path != path:
                self.send_response(404)
                self.end_headers()
                return
            params = parse_qs(request.query)
            if params.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"State mismatch. Close this window and retry login.")
                return
            if "error" in params:
                code_holder["error"] = params["error"][0]
            else:
                code_holder["code"] = params.get("code", [""])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Zoho authorization received. You can close this window.")

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    print("Open this URL, approve read-only Inventory access, then return here:\n")
    print(url)
    print("\nWaiting for the OAuth callback...")
    thread.join(timeout=300)
    server.server_close()
    if "error" in code_holder:
        raise UnauthorizedError(f"Zoho authorization failed: {code_holder['error']}")
    code = code_holder.get("code")
    if not code:
        raise ConfigError("No authorization code received. The callback timed out or the redirect URI did not match.")
    async with httpx.AsyncClient() as http:
        oauth = ZohoOAuth(
            dc=settings.zoho_dc,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            redirect_uri=settings.redirect_uri,
            http=http,
        )
        token = await oauth.exchange_code(code)
    store.save(token)
    print(f"Stored an encrypted refresh token at {settings.token_store_path}. Access token expires at {token.expires_at}.")
