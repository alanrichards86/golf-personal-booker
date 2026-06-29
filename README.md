# Golf Personal Booker

Automated tee time booking for Browns Mill Golf Course (Atlanta) via Playwright.

## How It Works (Dynamic Dates)

**No more changing config every week.** The script is smart:

1. **Logs into TeeItUp** and checks your **existing reservations**
2. **Finds the latest Sunday** (or your configured weekday) you already have booked
3. **Automatically targets the NEXT occurrence** after that one
4. Books it and stops at checkout for your review

This means if you already have July 5th booked, the next run will target July 12th. If you have July 12th too, it'll target July 19th. Fully automatic.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
playwright install chromium
```

2. Copy and fill in your credentials:
```bash
cp .env.example .env
# Edit .env with your username/password
```

## Usage

### Automatic mode (recommended)
```bash
python book_tee_time.py
```
The script checks your reservations and books the next unbooked Sunday.

### Book a specific date
```bash
python book_tee_time.py --date 2026-07-19
```

### Danger: Auto-complete purchase
```bash
python book_tee_time.py --auto-complete
```
This clicks **"Complete your purchase"** without human review. Use with caution.

## GitHub Actions

### Automatic Weekly Runs
The `.github/workflows/book-tee-time.yml` runs every **Sunday at 6:00 AM ET**.

### Manual Trigger with Date
Go to **Actions → Book Browns Mill Tee Time → Run workflow** and enter:
- `date`: `2026-07-19` (optional — leave blank for auto-detect)
- `auto_complete`: check only if you want it to pay automatically

### Required GitHub Secrets
Add these in your repo's **Settings → Secrets and variables → Actions**:

| Secret | Description |
|--------|-------------|
| `FOREPASS_PASSWORD` | WordPress page password (e.g. `FOREPASSHOLDER`) |
| `TEEITUP_USERNAME` | Your TeeItUp email |
| `TEEITUP_PASSWORD` | Your TeeItUp password |
| `WEBHOOK_URL` | Optional: Slack/Discord webhook for notifications |

### Optional GitHub Variables
Add these in **Settings → Secrets and variables → Variables** (not secrets):

| Variable | Default | Description |
|----------|---------|-------------|
| `TARGET_DAY_OF_WEEK` | `6` | 0=Mon, 6=Sun |
| `TARGET_HOUR_START` | `7` | Earliest preferred hour |
| `TARGET_HOUR_END` | `12` | Latest preferred hour |
| `TARGET_NUM_GOLFERS` | `1` | Number of golfers |
| `AUTO_COMPLETE_PURCHASE` | `false` | Set `true` to auto-pay |

## Safety Features

- **Never auto-pays by default** — stops at "Complete your purchase"
- **Screenshots saved** at every step for debugging
- **Checks existing reservations** to avoid double-booking
- **Minimum 2-day buffer** — won't try to book today or tomorrow

## Directory Structure

```
golf-personal-booker/
├── book_tee_time.py              # Main script
├── .env                          # Your credentials (gitignored!)
├── .env.example                  # Template
├── requirements.txt              # Python deps
├── .github/workflows/            # GitHub Actions
│   └── book-tee-time.yml
├── README.md
└── screenshots/                  # Auto-created debug screenshots
```
