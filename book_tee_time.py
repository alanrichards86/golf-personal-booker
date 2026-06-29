#!/usr/bin/env python3
"""
Browns Mill Golf Course - Fore Pass Tee Time Booker
Automates browsing, login, and checkout via Playwright.
Stops at "Complete your purchase" by default (human-in-the-loop safety).
"""

import os
import sys
import logging
import datetime
from typing import Optional
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

FOREPASS_PASSWORD = os.getenv("FOREPASS_PASSWORD", "")
TEEITUP_USERNAME = os.getenv("TEEITUP_USERNAME", "")
TEEITUP_PASSWORD = os.getenv("TEEITUP_PASSWORD", "")
TARGET_DAY_OF_WEEK = int(os.getenv("TARGET_DAY_OF_WEEK", "6"))  # 0=Mon, 6=Sun
TARGET_HOUR_START = int(os.getenv("TARGET_HOUR_START", "7"))    # 7 AM
TARGET_HOUR_END = int(os.getenv("TARGET_HOUR_END", "12"))       # 12 PM
TARGET_NUM_GOLFERS = int(os.getenv("TARGET_NUM_GOLFERS", "1"))
AUTO_COMPLETE_PURCHASE = os.getenv("AUTO_COMPLETE_PURCHASE", "false").lower() == "true"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

BASE_URL = "https://www.cityofatlantagolf.com/browns-mill-fore-pass-member-tee-times/"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("golf-booker")


def get_next_target_date(target_weekday: int = TARGET_DAY_OF_WEEK) -> datetime.date:
    """Return the next occurrence of the target weekday (0=Mon, 6=Sun)."""
    today = datetime.date.today()
    days_ahead = target_weekday - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + datetime.timedelta(days=days_ahead)


def send_notification(message: str) -> None:
    """Optional webhook notification."""
    if not WEBHOOK_URL:
        return
    try:
        import urllib.request
        import json

        data = json.dumps({"text": message}).encode("utf-8")
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info("Notification sent.")
    except Exception as e:
        logger.warning(f"Failed to send notification: {e}")


def get_teeitup_frame(page):
    """Return the TeeItUp iframe locator, waiting until it exists."""
    logger.info("Locating TeeItUp iframe...")
    # Wait for the iframe to attach
    page.wait_for_selector("iframe", timeout=15000)
    # TeeItUp iframe src contains teeitup.golf
    iframe = page.frame_locator("iframe[src*='teeitup.golf']").first
    return iframe


def enter_wordpress_password(page) -> None:
    """Handle the WordPress password-protected page."""
    logger.info("Checking for WordPress password page...")
    try:
        # The password form may or may not appear depending on session
        password_input = page.locator("input[type='password']").first
        if password_input.is_visible(timeout=3000):
            logger.info("Entering WordPress password...")
            password_input.fill(FOREPASS_PASSWORD)
            page.locator("button:has-text('Enter'), input[type='submit']").first.click()
            page.wait_for_load_state("networkidle")
            logger.info("WordPress password submitted.")
        else:
            logger.info("No WordPress password prompt (already unlocked or cookie present).")
    except PlaywrightTimeout:
        logger.info("No WordPress password prompt detected.")


def login_teeitup(iframe) -> None:
    """Log into TeeItUp inside the iframe."""
    logger.info("Checking TeeItUp login state...")
    try:
        # If already logged in, we see the user menu button
        user_menu = iframe.locator("[data-testid='core-user-menu']").first
        if user_menu.is_visible(timeout=3000):
            logger.info("Already logged in to TeeItUp.")
            return
    except PlaywrightTimeout:
        pass

    logger.info("Opening TeeItUp login form...")
    login_btn = iframe.locator("[data-testid='core-login-signup']").first
    login_btn.click()

    logger.info("Filling TeeItUp credentials...")
    iframe.locator("[data-testid='login-email-component']").fill(TEEITUP_USERNAME)
    iframe.locator("[data-testid='login-password-component']").fill(TEEITUP_PASSWORD)
    iframe.locator("[data-testid='login-button']").click()

    # Wait for login to complete (user menu appears or tee times load)
    iframe.locator("[data-testid='core-user-menu']").first.wait_for(state="visible", timeout=15000)
    logger.info("TeeItUp login successful.")


def navigate_to_date(iframe, target_date: datetime.date) -> None:
    """Use the calendar to navigate to the target date."""
    logger.info(f"Navigating calendar to {target_date}...")

    # The calendar shows a month; we need to click "Next month" until we reach target month/year
    target_month_year = target_date.strftime("%B %Y")  # e.g. "July 2026"

    max_clicks = 12
    for _ in range(max_clicks):
        # Read current month label
        month_label = iframe.locator("[data-testid='teetimes-calendar-component'] p").first
        current_text = month_label.inner_text(timeout=5000).strip()
        if target_month_year.lower() in current_text.lower():
            break
        next_month_btn = iframe.locator("button[aria-label*='Next month'], button:has-text('Next month')").first
        next_month_btn.click()
        # Wait for calendar animation
        iframe.page.wait_for_timeout(500)
    else:
        raise RuntimeError(f"Could not navigate to {target_month_year}")

    # Click the specific date
    day_str = str(target_date.day)
    logger.info(f"Selecting day {day_str}...")
    date_cell = iframe.locator(f"[role='gridcell']:has-text('{day_str}')").first
    # Ensure it's not disabled
    if date_cell.get_attribute("disabled"):
        raise RuntimeError(f"Date {target_date} is disabled/unavailable.")
    date_cell.click()
    iframe.page.wait_for_timeout(2000)  # Let tee times load
    logger.info("Date selected, tee times loading...")


def select_tee_time(iframe) -> bool:
    """
    Select the best tee time within the configured hour window.
    Returns True if a tee time was selected.
    """
    logger.info(f"Looking for tee times between {TARGET_HOUR_START}:00 and {TARGET_HOUR_END}:00...")

    # Wait for tee time list to appear
    iframe.locator("[data-testid='teetimes_choose_rate_button']").first.wait_for(state="visible", timeout=15000)

    # Get all tee time cards
    choose_buttons = iframe.locator("button:has-text('Choose Rate')").all()
    logger.info(f"Found {len(choose_buttons)} tee time option(s).")

    best_button = None
    best_hour = 999

    for btn in choose_buttons:
        aria = btn.get_attribute("aria-label") or ""
        # Parse time from aria-label, e.g. "July 5th 2026, 8:50:00 am"
        # We'll do a simple extraction
        time_part = None
        if "," in aria:
            time_part = aria.split(",")[-1].strip().lower()

        if not time_part:
            continue

        # Extract hour
        hour = None
        if "am" in time_part or "pm" in time_part:
            # Remove am/pm and parse
            time_clean = time_part.replace("am", "").replace("pm", "").strip()
            parts = time_clean.split(":")
            if len(parts) >= 2:
                try:
                    h = int(parts[0])
                    m = int(parts[1])
                    if "pm" in time_part and h != 12:
                        h += 12
                    if "am" in time_part and h == 12:
                        h = 0
                    hour = h
                except ValueError:
                    continue

        if hour is None:
            continue

        if TARGET_HOUR_START <= hour < TARGET_HOUR_END:
            if hour < best_hour:
                best_hour = hour
                best_button = btn

    if best_button is None:
        logger.warning("No tee times found in the preferred time window.")
        return False

    logger.info(f"Selecting tee time around {best_hour}:00...")
    best_button.click()
    iframe.page.wait_for_timeout(1500)
    return True


def add_to_cart(iframe) -> None:
    """Add the selected tee time to cart."""
    logger.info("Adding to cart...")
    add_btn = iframe.locator("[data-testid='add-to-cart-button']").first
    add_btn.wait_for(state="visible", timeout=10000)
    add_btn.click()
    iframe.page.wait_for_timeout(1500)
    logger.info("Added to cart.")


def proceed_to_checkout(iframe) -> None:
    """Open cart and click checkout."""
    logger.info("Opening cart...")
    cart_btn = iframe.locator("[data-testid='shopping-cart-button']").first
    cart_btn.click()
    iframe.page.wait_for_timeout(1500)

    logger.info("Clicking checkout...")
    checkout_btn = iframe.locator("[data-testid='shopping-cart-drawer-checkout-btn']").first
    checkout_btn.wait_for(state="visible", timeout=10000)
    checkout_btn.click()
    iframe.page.wait_for_timeout(2000)
    logger.info("At checkout page.")


def handle_checkout(iframe) -> None:
    """Agree to terms and stop (or complete purchase)."""
    logger.info("Handling checkout...")

    # Check terms box
    terms = iframe.locator("[data-testid='terms-and-conditions-checkbox']").first
    terms.wait_for(state="visible", timeout=10000)
    terms.click()
    logger.info("Terms & Conditions checked.")

    complete_btn = iframe.locator("button:has-text('Complete your purchase')").first
    complete_btn.wait_for(state="visible", timeout=10000)

    if AUTO_COMPLETE_PURCHASE:
        logger.warning("AUTO_COMPLETE_PURCHASE is enabled. Finalizing purchase!")
        complete_btn.click()
        iframe.page.wait_for_timeout(3000)
        logger.info("Purchase completed!")
        send_notification("Tee time booked successfully!")
    else:
        logger.info("=" * 60)
        logger.info("STOPPED AT CHECKOUT (safety mode).")
        logger.info("Tee time is in cart and ready to purchase.")
        logger.info("Please click 'Complete your purchase' manually.")
        logger.info("=" * 60)
        send_notification("Tee time is ready for purchase. Please complete checkout manually.")


def take_screenshot(page, name: str) -> None:
    """Save a screenshot for debugging."""
    os.makedirs("screenshots", exist_ok=True)
    path = f"screenshots/{name}.png"
    page.screenshot(path=path, full_page=True)
    logger.info(f"Screenshot saved: {path}")


def run() -> None:
    target_date = get_next_target_date()
    logger.info(f"Target date: {target_date} ({target_date.strftime('%A')})")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1486, "height": 929},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            logger.info(f"Navigating to {BASE_URL}...")
            page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
            take_screenshot(page, "01_initial_page")

            enter_wordpress_password(page)
            take_screenshot(page, "02_after_wp_password")

            iframe = get_teeitup_frame(page)
            login_teeitup(iframe)
            take_screenshot(page, "03_after_login")

            navigate_to_date(iframe, target_date)
            take_screenshot(page, "04_after_date_select")

            found = select_tee_time(iframe)
            if not found:
                logger.error("No suitable tee time found. Exiting.")
                take_screenshot(page, "05_no_tee_times")
                sys.exit(1)

            take_screenshot(page, "05_after_tee_select")

            add_to_cart(iframe)
            take_screenshot(page, "06_after_add_to_cart")

            proceed_to_checkout(iframe)
            take_screenshot(page, "07_at_checkout")

            handle_checkout(iframe)
            take_screenshot(page, "08_final_state")

            logger.info("Script finished successfully.")

        except Exception as e:
            logger.exception("Booking failed.")
            take_screenshot(page, "error_state")
            send_notification(f"Booking script failed: {e}")
            sys.exit(1)

        finally:
            browser.close()


if __name__ == "__main__":
    run()
