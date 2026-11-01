"""Fixed-page availability diagnostics only; no account input or form submission."""
from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import unquote, urlsplit

RECOVERY_URL = "https://www.instagram.com/accounts/password/reset/"
logger = logging.getLogger(__name__)


async def inspect_recovery_page() -> dict[str, object]:
    # Optional browser support must not break startup of payment/email handlers.
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        options = {"headless": True}
        executable = os.environ.get("INSTAGRAM_INSPECT_BROWSER_PATH")
        if executable:
            options["executable_path"] = executable
        proxy_url = (os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
                     or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"))
        if proxy_url:
            proxy = urlsplit(proxy_url)
            if not proxy.hostname or proxy.scheme not in ("http", "https", "socks5"):
                raise ValueError("Invalid browser proxy configuration")
            host = f"[{proxy.hostname}]" if ':' in proxy.hostname else proxy.hostname
            settings = {"server": f"{proxy.scheme}://{host}" + (f":{proxy.port}" if proxy.port else "")}
            if proxy.username:
                settings["username"] = unquote(proxy.username)
            if proxy.password:
                settings["password"] = unquote(proxy.password)
            options["proxy"] = settings
        browser = await playwright.chromium.launch(**options)
        try:
            page = await browser.new_page(locale="en-US")
            response = await page.goto(
                RECOVERY_URL, wait_until="domcontentloaded", timeout=30000
            )
            if response is None:
                return {"status": "no_response"}
            return {
                "status": "ok" if response.ok else "http_error",
                "http_status": response.status,
                "username_fields": await page.get_by_role("textbox").count(),
                "continue_buttons": await page.get_by_role(
                    "button", name="Continue", exact=True
                ).count(),
            }
        finally:
            try:
                await asyncio.wait_for(browser.close(), timeout=5)
            except Exception as exc:
                logger.warning("Inspector browser cleanup failed (%s)", type(exc).__name__)
