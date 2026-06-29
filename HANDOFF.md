# Golf Personal Booker — Session Handoff

**Date:** June 28, 2026  
**Repo:** `alanrichards86/golf-personal-booker`  
**Branch:** `main`  
**Last Commit:** `67da9df` — "Add login retry logic, error detection, and debug screenshots for failed logins"

---

## What This Project Does

Automated tee time booking for **Browns Mill Golf Course (Atlanta)** via Playwright.
- Logs into the password-protected Fore Pass holder page
- Checks existing reservations to determine the next unbooked Sunday
- Finds and selects tee times within a preferred time window
- Supports configurable golfer count (1-4)
- Stops at checkout for human review (safety mode)

---

## Current Status

### What's Working
- ✅ Repo created and pushed to GitHub
- ✅ GitHub Actions workflow configured (manual dispatch + weekly cron)
- ✅ WordPress password entry works
- ✅ TeeItUp login works (with retry logic)
- ✅ Golfer count filtering (1-4 players)
- ✅ Dynamic date detection from existing reservations
- ✅ Configurable via `.env` and GitHub Secrets/Variables

### Known Issues

#### 🔴 CRITICAL: Calendar Navigation Fails Across Month Boundaries
**Status:** Active — needs fix  
**Symptom:** When trying to book a date in the next month (e.g., June → July), the calendar stays on the current month. The `navigate_to_date()` function cannot read the month label or click "Next month" effectively.

**Evidence:**
- Screenshot `03b_after_login_click.png` shows logged-in user on tee times page
- Calendar still displays "June 2026" when target is July 5, 2026
- Script fails at `navigate_to_date()` because it can't find the target date

**Root Cause:** `get_calendar_month_text()` uses overly complex Playwright locators that fail to find the month/year label in the TeeItUp React calendar component.

**Files to Fix:**
- `book_tee_time.py` — Lines 303-317 (`get_calendar_month_text`)
- `book_tee_time.py` — Lines 320-370 (`navigate_to_date`)

**Suggested Fix:**
Replace `get_calendar_month_text()` with a simpler approach:
```python
def get_calendar_month_text(iframe) -> str:
    """Read the current month/year label from the calendar header."""
    try:
        # Look for the month label — it's a paragraph containing "Month YYYY"
        # e.g., "June 2026", "July 2026"
        month_label = iframe.locator(
            "[data-testid='teetimes-calendar-component'] p"
        ).filter(has_text=re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}"))
        if month_label.is_visible(timeout=2000):
            return month_label.inner_text(timeout=3000).strip()
    except Exception:
        pass
    
    # Fallback: read any visible text that looks like a month/year
    try:
        all_text = iframe.locator("[data-testid='teetimes-calendar-component']").inner_text(timeout=3000)
        m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})", all_text, re.IGNORECASE)
        if m:
            return m.group(0)
    except Exception:
        pass
    
    return ""
```

And simplify `navigate_to_date()`:
```python
def navigate_to_date(iframe, target_date: datetime.date) -> None:
    logger.info(f"Navigating calendar to {target_date}...")
    target_month_year = target_date.strftime("%B %Y")
    day_str = str(target_date.day)
    
    for attempt in range(12):
        current_text = get_calendar_month_text(iframe)
        logger.info(f"Calendar showing: {current_text}")
        
        if target_month_year.lower() in current_text.lower():
            break
            
        next_btn = iframe.locator("button[aria-label*='Next month']").first
        if not next_btn.is_visible(timeout=2000):
            raise RuntimeError("Next month button not found")
        next_btn.click()
        iframe.page.wait_for_timeout(1500)  # Wait for React re-render
    else:
        raise RuntimeError(f"Could not reach {target_month_year}")
    
    # Find and click the date
    date_cell = iframe.locator(f"[role='gridcell']").filter(has_text=day_str).first
    if date_cell.get_attribute("disabled"):
        raise RuntimeError(f"Date {target_date} is disabled")
    date_cell.click()
    iframe.page.wait_for_timeout(2000)
```

#### 🟡 GitHub Actions Cron Schedule
**Status:** Reverted to Sunday-only  
**Current:** `0 5 * * 0` (Sunday 1:00 AM ET)  
**Note:** A temporary test cron `8 2 * * *` was used but has been reverted.

#### 🟡 No Purchase Auto-Completion
**Status:** By design  
The script stops at "Complete your purchase" for safety. To enable auto-payment, set `AUTO_COMPLETE_PURCHASE=true` in GitHub Variables.

---

## Configuration

### Local `.env`
```bash
FOREPASS_PASSWORD=FOREPASSHOLDER
TEEITUP_USERNAME=alanrichards86@gmail.com
TEEITUP_PASSWORD=5PQ4YpyR8uV^69YNB7fH
TARGET_DAY_OF_WEEK=6        # 0=Mon, 6=Sun
TARGET_HOUR_START=7
TARGET_HOUR_END=12
TARGET_NUM_GOLFERS=1        # Change to 2, 3, or 4
AUTO_COMPLETE_PURCHASE=false
WEBHOOK_URL=
```

### GitHub Secrets (Repository Settings)
| Secret | Value |
|--------|-------|
| `FOREPASS_PASSWORD` | `FOREPASSHOLDER` |
| `TEEITUP_USERNAME` | `alanrichards86@gmail.com` |
| `TEEITUP_PASSWORD` | `5PQ4YpyR8uV^69YNB7fH` |
| `WEBHOOK_URL` | (optional) |

### GitHub Variables (Repository Settings)
| Variable | Default | Description |
|----------|---------|-------------|
| `TARGET_DAY_OF_WEEK` | `6` | Day to book: 0=Mon, 6=Sun |
| `TARGET_HOUR_START` | `7` | Earliest preferred hour |
| `TARGET_HOUR_END` | `12` | Latest preferred hour |
| `TARGET_NUM_GOLFERS` | `1` | Number of golfers |
| `AUTO_COMPLETE_PURCHASE` | `false` | Auto-click "Complete purchase" |

---

## How to Test

### Local
```bash
cd /Users/alanrichards/git/personal/golf-personal-booker
pip install -r requirements.txt
playwright install chromium
python book_tee_time.py --date 2026-07-05 --debug
```

### GitHub Actions (Manual)
1. Go to repo on GitHub
2. Actions → "Book Browns Mill Tee Time" → "Run workflow"
3. Optionally enter:
   - `date`: `2026-07-05`
   - `golfers`: `4`
   - `debug`: ✅ (enabled by default)
4. Check screenshots artifact after run

---

## Next Steps (Priority Order)

1. **🔴 FIX CALENDAR NAVIGATION** — The month boundary issue is the #1 blocker
   - Simplify `get_calendar_month_text()` to reliably read the month label
   - Test with `--date 2026-07-05` to confirm June→July navigation works
   - Consider using the URL parameter `?date=YYYY-MM-DD` as a shortcut instead of clicking calendar

2. **Test full booking flow** — Once calendar works, verify:
   - Tee time selection with golfer filtering
   - Add to cart
   - Checkout page reached
   - Screenshot uploaded to artifact

3. **Consider URL-based date navigation** — Instead of clicking calendar UI:
   ```python
   # The TeeItUp iframe supports ?date=YYYY-MM-DD
   page.goto(f"{BASE_URL}?date={target_date.isoformat()}")
   ```
   This might be more reliable than UI automation.

4. **Add notification webhook** — Set up Slack/Discord webhook for booking status

5. **Monitor first Sunday run** — The cron is set for Sundays at 1:00 AM ET. Watch the first run.

---

## File Structure

```
golf-personal-booker/
├── .env                          # Local credentials (gitignored)
├── .env.example                  # Template
├── .gitignore
├── README.md
├── requirements.txt              # playwright, python-dotenv
├── book_tee_time.py              # Main script (NEEDS FIX: calendar nav)
├── handoff.md                    # This file
└── .github/workflows/
    └── book-tee-time.yml         # GitHub Actions (cron + manual dispatch)
```

---

## Context from This Session

- **Website:** https://www.cityofatlantagolf.com/browns-mill-golf-course/
- **Fore Pass page:** https://www.cityofatlantagolf.com/browns-mill-fore-pass-member-tee-times/
- **Password:** `FOREPASSHOLDER` (WordPress protected page)
- **TeeItUp iframe:** https://browns-mill-fore-passholder.book.teeitup.golf/
- **User:** Alan Richards (alanrichards86@gmail.com)
- **Goal:** Book tee times automatically every Sunday morning
- **Constraint:** Script must stop at checkout (human clicks "Complete purchase")

---

## Screenshots from Failed Runs

Check GitHub Actions artifacts for:
- `01_initial_page.png` — Landing page
- `02_after_wp_password.png` — After WordPress password
- `03_after_login.png` — After TeeItUp login
- `03b_after_login_click.png` — After clicking login (new)
- `04_after_date_select.png` — Calendar page (usually where it fails)
- `error_state.png` — Final state before crash

---

*End of handoff. Next session should focus on fixing the calendar month navigation issue.*
