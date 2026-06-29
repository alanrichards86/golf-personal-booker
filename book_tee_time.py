#!/usr/bin/env python3
"""
Browns Mill Golf Course - Fore Pass Tee Time Booker
Automates browsing, login, and checkout via Playwright.
Stops at "Complete your purchase" by default (human-in-the-loop safety).

Usage:
    python book_tee_time.py
    python book_tee_time.py --date 2026-07-12
    python book_tee_time.py --golfers 4
    python book_tee_time.py --auto-complete  # dangerous: clicks "Complete your purchase"
"""

import os
import sys
import re
import logging
import argparse
import datetime
from typing import Optional, List, Tuple
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
RESERVATIONS_URL = "https://browns-mill-fore-passholder.book.teeitup.golf/reservation/history"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("golf-booker")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_player_availability(text: str) -> Tuple[int, int]:
    """
    Parse player availability text like '1', '1 - 4', '1 or 2', '1 - 3'.
    Returns (min_players, max_players).
    """
    text = text.strip().lower()

    # Pattern: "1 - 4" or "1-4"
    m = re.search(r'(\d+)\s*-\s*(\d+)', text)
    if m:
        return int(m.group(1)), int(m.group(2))

    # Pattern: "1 or 2"
    m = re.search(r'(\d+)\s+or\s+(\d+)', text)
    if m:
        return int(m.group(1)), int(m.group(2))

    # Pattern: single number like "1"
    m = re.search(r'^(\d+)$', text)
    if m:
        n = int(m.group(1))
        return n, n

    return 0, 0


def can_accommodate(text: str, num_golfers: int) -> bool:
    """Check if a tee time availability text can accommodate num_golfers."""
    min_p, max_p = parse_player_availability(text)
    return min_p <= num_golfers <= max_p


# ---------------------------------------------------------------------------
# Date Logic
# ---------------------------------------------------------------------------
def get_next_weekday(target_weekday: int, after_date: Optional[datetime.date] = None) -> datetime.date:
    """Return the next occurrence of target_weekday on or after after_date."""
    if after_date is None:
        after_date = datetime.date.today()
    days_ahead = target_weekday - after_date.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return after_date + datetime.timedelta(days=days_ahead)


def parse_existing_reservation_dates(iframe) -> List[datetime.date]:
    """
    Navigate to the Reservations page and parse dates of existing bookings.
    Returns a list of datetime.date objects.
    """
    logger.info("Checking existing reservations...")
    dates: List[datetime.date] = []

    try:
        # Click the Reservations tab/link
        reservations_link = iframe.locator("a[href='/reservation/history'], text=Reservations").first
        if reservations_link.is_visible(timeout=5000):
            reservations_link.click()
            iframe.page.wait_for_timeout(2000)
        else:
            # Navigate directly inside the iframe
            iframe.page.goto(RESERVATIONS_URL, wait_until="networkidle", timeout=15000)
            iframe.page.wait_for_timeout(2000)

        # Look for date patterns in the reservation list
        # Common formats: "07/05/2026", "July 5, 2026", "Jul 05, 2026"
        page_text = iframe.page.content()

        # Pattern 1: MM/DD/YYYY
        for m in re.finditer(r'(\d{1,2})/(\d{1,2})/(\d{4})', page_text):
            try:
                d = datetime.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
                dates.append(d)
            except ValueError:
                continue

        # Pattern 2: Month DD, YYYY (e.g. "July 5, 2026")
        month_map = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12
        }
        for m in re.finditer(r'([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})', page_text):
            month_name = m.group(1).lower()
            if month_name in month_map:
                try:
                    d = datetime.date(int(m.group(3)), month_map[month_name], int(m.group(2)))
                    dates.append(d)
                except ValueError:
                    continue

        # Remove duplicates and sort
        dates = sorted(list(set(dates)))
        logger.info(f"Found {len(dates)} existing reservation date(s): {[d.isoformat() for d in dates]}")

    except Exception as e:
        logger.warning(f"Could not read reservations: {e}")

    return dates


def determine_target_date(
    existing_dates: List[datetime.date],
    target_weekday: int = TARGET_DAY_OF_WEEK,
    min_days_ahead: int = 2,
) -> datetime.date:
    """
    Determine the best target date to book.

    Logic:
      1. If there are existing reservations on the target weekday,
         find the latest one and target the NEXT occurrence.
      2. Otherwise, target the next upcoming target weekday
         that is at least min_days_ahead from today.
    """
    today = datetime.date.today()
    weekday_dates = [d for d in existing_dates if d.weekday() == target_weekday]

    if weekday_dates:
        latest = max(weekday_dates)
        logger.info(f"Latest booked {latest.strftime('%A')}: {latest}")
        # Book the next one after the latest reservation
        candidate = get_next_weekday(target_weekday, after_date=latest + datetime.timedelta(days=1))
    else:
        logger.info("No existing reservations found on target weekday.")
        candidate = get_next_weekday(target_weekday)

    # Ensure we don't book too close to today (tee times may not be released yet)
    min_date = today + datetime.timedelta(days=min_days_ahead)
    while candidate < min_date:
        logger.info(f"Candidate {candidate} is too close to today. Looking further ahead...")
        candidate = get_next_weekday(target_weekday, after_date=candidate + datetime.timedelta(days=1))

    logger.info(f"Determined target date: {candidate} ({candidate.strftime('%A')})")
    return candidate


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def send_notification(message: str) -> None:
    if not WEBHOOK_URL:
        return
    try:
        import urllib.request
        import json
        data = json.dumps({"text": message}).encode("utf-8")
        req = urllib.request.Request(
            WEBHOOK_URL, data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info("Notification sent.")
    except Exception as e:
        logger.warning(f"Failed to send notification: {e}")


# ---------------------------------------------------------------------------
# Browser Automation
# ---------------------------------------------------------------------------
def get_teeitup_frame(page):
    logger.info("Locating TeeItUp iframe...")
    page.wait_for_selector("iframe", timeout=15000)
    iframe = page.frame_locator("iframe[src*='teeitup.golf']").first
    return iframe


def enter_wordpress_password(page) -> None:
    logger.info("Checking for WordPress password page...")
    try:
        password_input = page.locator("input[type='password']").first
        if password_input.is_visible(timeout=3000):
            logger.info("Entering WordPress password...")
            password_input.fill(FOREPASS_PASSWORD)
            page.locator("button:has-text('Enter'), input[type='submit']").first.click()
            page.wait_for_load_state("networkidle")
            logger.info("WordPress password submitted.")
        else:
            logger.info("No WordPress password prompt.")
    except PlaywrightTimeout:
        logger.info("No WordPress password prompt detected.")


def login_teeitup(iframe) -> None:
    logger.info("Checking TeeItUp login state...")
    try:
        user_menu = iframe.locator("[data-testid='core-user-menu']").first
        if user_menu.is_visible(timeout=3000):
            logger.info("Already logged in to TeeItUp.")
            return
    except PlaywrightTimeout:
        pass

    logger.info("Opening TeeItUp login form...")
    iframe.locator("[data-testid='core-login-signup']").first.click()
    logger.info("Filling TeeItUp credentials...")
    iframe.locator("[data-testid='login-email-component']").fill(TEEITUP_USERNAME)
    iframe.locator("[data-testid='login-password-component']").fill(TEEITUP_PASSWORD)
    iframe.locator("[data-testid='login-button']").click()
    iframe.locator("[data-testid='core-user-menu']").first.wait_for(state="visible", timeout=15000)
    logger.info("TeeItUp login successful.")


def navigate_to_date(iframe, target_date: datetime.date) -> None:
    logger.info(f"Navigating calendar to {target_date}...")
    target_month_year = target_date.strftime("%B %Y")

    for _ in range(12):
        month_label = iframe.locator("[data-testid='teetimes-calendar-component'] p").first
        current_text = month_label.inner_text(timeout=5000).strip()
        if target_month_year.lower() in current_text.lower():
            break
        next_month_btn = iframe.locator("button[aria-label*='Next month'], button:has-text('Next month')").first
        next_month_btn.click()
        iframe.page.wait_for_timeout(500)
    else:
        raise RuntimeError(f"Could not navigate to {target_month_year}")

    day_str = str(target_date.day)
    logger.info(f"Selecting day {day_str}...")
    date_cell = iframe.locator(f"[role='gridcell']:has-text('{day_str}')").first
    if date_cell.get_attribute("disabled"):
        raise RuntimeError(f"Date {target_date} is disabled/unavailable.")
    date_cell.click()
    iframe.page.wait_for_timeout(2000)
    logger.info("Date selected, tee times loading...")


def select_tee_time(iframe, num_golfers: int = TARGET_NUM_GOLFERS) -> bool:
    logger.info(
        f"Looking for tee times between {TARGET_HOUR_START}:00 and {TARGET_HOUR_END}:00 "
        f"for {num_golfers} golfer(s)..."
    )
    iframe.locator("[data-testid='teetimes_choose_rate_button']").first.wait_for(state="visible", timeout=15000)

    # Each tee time is in a group/card. We need to inspect the text near each "Choose Rate" button.
    choose_buttons = iframe.locator("button:has-text('Choose Rate')").all()
    logger.info(f"Found {len(choose_buttons)} tee time option(s).")

    best_button = None
    best_hour = 999

    for btn in choose_buttons:
        aria = btn.get_attribute("aria-label") or ""

        # Extract time from aria-label
        time_part = None
        if "," in aria:
            time_part = aria.split(",")[-1].strip().lower()

        if not time_part:
            continue

        hour = None
        if "am" in time_part or "pm" in time_part:
            time_clean = time_part.replace("am", "").replace("pm", "").strip()
            parts = time_clean.split(":")
            if len(parts) >= 2:
                try:
                    h = int(parts[0])
                    if "pm" in time_part and h != 12:
                        h += 12
                    if "am" in time_part and h == 12:
                        h = 0
                    hour = h
                except ValueError:
                    continue

        if hour is None:
            continue

        if not (TARGET_HOUR_START <= hour < TARGET_HOUR_END):
            continue

        # Extract player availability from aria-label, e.g. "1 players available" or "1 - 4 players available"
        player_text = ""
        m = re.search(r'(\d+(?:\s*-\s*\d+|\s+or\s+\d+)?)\s+players?\s+available', aria.lower())
        if m:
            player_text = m.group(1)
        else:
            # Fallback: look at the sibling paragraph near the button
            try:
                card = btn.locator("xpath=ancestor::*[contains(@class, 'MuiGrid-item') or contains(@class, 'css-')][1]")
                player_para = card.locator("p:has-text('players')").first
                if player_para.is_visible(timeout=1000):
                    player_text = player_para.inner_text(timeout=2000)
            except Exception:
                pass

        if player_text and not can_accommodate(player_text, num_golfers):
            logger.debug(f"Skipping {hour}:00 — only accommodates {player_text} players.")
            continue

        if hour < best_hour:
            best_hour = hour
            best_button = btn

    if best_button is None:
        logger.warning("No tee times found matching time window AND golfer count.")
        return False

    logger.info(f"Selecting tee time around {best_hour}:00...")
    best_button.click()
    iframe.page.wait_for_timeout(1500)
    return True


def set_num_golfers(iframe, num_golfers: int) -> None:
    """Select the correct number of golfers in the accordion radio group."""
    logger.info(f"Setting number of golfers to {num_golfers}...")
    try:
        # The radio buttons have aria-label like "1 golfer", "2 golfers", etc.
        radio = iframe.locator(f"[role='radio']:has-text('{num_golfers} golfer')").first
        if not radio.is_visible(timeout=3000):
            # Try plural form
            radio = iframe.locator(f"[role='radio']:has-text('{num_golfers} golfers')").first

        if radio.is_visible(timeout=3000):
            if radio.is_enabled():
                radio.click()
                logger.info(f"Selected {num_golfers} golfer(s).")
            else:
                logger.warning(f"Radio for {num_golfers} golfers is disabled. Using default selection.")
        else:
            logger.warning(f"Could not find radio for {num_golfers} golfers. Using default selection.")
    except Exception as e:
        logger.warning(f"Failed to set golfer count: {e}. Using default.")


def add_to_cart(iframe) -> None:
    logger.info("Adding to cart...")
    add_btn = iframe.locator("[data-testid='add-to-cart-button']").first
    add_btn.wait_for(state="visible", timeout=10000)
    add_btn.click()
    iframe.page.wait_for_timeout(1500)
    logger.info("Added to cart.")


def proceed_to_checkout(iframe) -> None:
    logger.info("Opening cart...")
    iframe.locator("[data-testid='shopping-cart-button']").first.click()
    iframe.page.wait_for_timeout(1500)

    logger.info("Clicking checkout...")
    checkout_btn = iframe.locator("[data-testid='shopping-cart-drawer-checkout-btn']").first
    checkout_btn.wait_for(state="visible", timeout=10000)
    checkout_btn.click()
    iframe.page.wait_for_timeout(2000)
    logger.info("At checkout page.")


def handle_checkout(iframe, auto_complete: bool = False) -> None:
    logger.info("Handling checkout...")
    terms = iframe.locator("[data-testid='terms-and-conditions-checkbox']").first
    terms.wait_for(state="visible", timeout=10000)
    terms.click()
    logger.info("Terms & Conditions checked.")

    complete_btn = iframe.locator("button:has-text('Complete your purchase')").first
    complete_btn.wait_for(state="visible", timeout=10000)

    if auto_complete:
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
    os.makedirs("screenshots", exist_ok=True)
    path = f"screenshots/{name}.png"
    page.screenshot(path=path, full_page=True)
    logger.info(f"Screenshot saved: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(
    target_date: Optional[datetime.date] = None,
    auto_complete: bool = False,
    num_golfers: int = TARGET_NUM_GOLFERS,
) -> None:
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

            # If no explicit date provided, check reservations and determine dynamically
            if target_date is None:
                existing_dates = parse_existing_reservation_dates(iframe)
                target_date = determine_target_date(existing_dates)
                # Navigate back to tee times page if we went to reservations
                page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
                iframe = get_teeitup_frame(page)

            logger.info(f"Target date: {target_date} ({target_date.strftime('%A')})")
            logger.info(f"Target golfers: {num_golfers}")

            navigate_to_date(iframe, target_date)
            take_screenshot(page, "04_after_date_select")

            found = select_tee_time(iframe, num_golfers=num_golfers)
            if not found:
                logger.error("No suitable tee time found. Exiting.")
                take_screenshot(page, "05_no_tee_times")
                sys.exit(1)

            take_screenshot(page, "05_after_tee_select")

            set_num_golfers(iframe, num_golfers)
            take_screenshot(page, "05b_after_golfer_select")

            add_to_cart(iframe)
            take_screenshot(page, "06_after_add_to_cart")

            proceed_to_checkout(iframe)
            take_screenshot(page, "07_at_checkout")

            handle_checkout(iframe, auto_complete=auto_complete)
            take_screenshot(page, "08_final_state")

            logger.info("Script finished successfully.")

        except Exception as e:
            logger.exception("Booking failed.")
            take_screenshot(page, "error_state")
            send_notification(f"Booking script failed: {e}")
            sys.exit(1)

        finally:
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Browns Mill Golf Tee Time Booker")
    parser.add_argument(
        "--date",
        type=str,
        help="Explicit date to book (YYYY-MM-DD). Overrides dynamic date logic.",
    )
    parser.add_argument(
        "--golfers",
        type=int,
        default=TARGET_NUM_GOLFERS,
        help=f"Number of golfers to book for (default: {TARGET_NUM_GOLFERS})",
    )
    parser.add_argument(
        "--auto-complete",
        action="store_true",
        help="Click 'Complete your purchase' automatically (DANGEROUS).",
    )
    parser.add_argument(
        "--target-weekday",
        type=int,
        default=TARGET_DAY_OF_WEEK,
        help="Day of week to target: 0=Mon, 6=Sun (default: 6)",
    )
    args = parser.parse_args()

    explicit_date = None
    if args.date:
        try:
            explicit_date = datetime.date.fromisoformat(args.date)
        except ValueError:
            logger.error(f"Invalid date format: {args.date}. Use YYYY-MM-DD.")
            sys.exit(1)

    if args.golfers < 1 or args.golfers > 4:
        logger.error("Number of golfers must be between 1 and 4.")
        sys.exit(1)

    auto_complete = args.auto_complete or AUTO_COMPLETE_PURCHASE
    if auto_complete:
        logger.warning("=" * 60)
        logger.warning("AUTO-COMPLETE IS ENABLED!")
        logger.warning("This will finalize the purchase without human review.")
        logger.warning("=" * 60)

    run(target_date=explicit_date, auto_complete=auto_complete, num_golfers=args.golfers)


if __name__ == "__main__":
    main()
