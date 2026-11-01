"""Read-only inspection of Instagram's recovery page (no account lookup)."""
from __future__ import annotations

from playwright.async_api import async_playwright

RECOVERY_URL = "https://www.instagram.com/accounts/password/reset/"


async def inspect_recovery_page() -> dict[str, object]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
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
            await browser.close()
