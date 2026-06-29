# Golf Personal Booker

Automated tee time booking for Browns Mill Golf Course (Atlanta) via Playwright.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
playwright install chromium
```

2. Copy environment variables:
```bash
cp .env.example .env
```

3. Edit `.env` with your credentials.

## Running Locally

```bash
python book_tee_time.py
```

## What It Does

1. Navigates to the Browns Mill Fore Pass holder page
2. Enters the WordPress password to unlock the TeeItUp iframe
3. Logs into TeeItUp with your account
4. Selects **next Sunday** on the calendar
5. Finds the earliest available tee time (configurable time window)
6. Selects the rate and adds to cart
7. Proceeds to checkout
8. Checks the Terms & Conditions box
9. **Stops at the "Complete your purchase" button** (does NOT finalize payment)

## Safety

- The script **never clicks "Complete your purchase"** by default. It stops at checkout so you can review and pay manually.
- To enable auto-purchase, set `AUTO_COMPLETE_PURCHASE=true` in your `.env` (not recommended for unattended runs).
