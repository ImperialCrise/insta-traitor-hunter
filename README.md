# insta-traitor-hunter

Small Python command-line tool to **audit** and **clean up** your Instagram
follow list.

Main use case: find **"traitors"**: accounts *you* follow that **do not follow
you back** and have **fewer than X followers** (default 10,000, configurable),
then bulk-unfollow them with sensible rate limiting to reduce ban risk.

> ⚠️ You are using Instagram's private API. Use an account you are willing to
> lose, or at least to see temporarily restricted. Go easy.

---

## Prerequisites

- WSL / Ubuntu / Debian / macOS (tested on WSL2 Ubuntu 22.04)
- Python **3.10+**
- An Instagram account (ideally **with 2FA enabled**)

---

## Installation (WSL / Ubuntu)

```bash
# From WSL, go to the repo folder
cd insta-traitor-hunter

# System packages (once)
sudo apt update
sudo apt install -y python3 python3-venv python3-pip

# Virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Dependencies
pip install -r requirements.txt

# Config
cp .env.example .env
nano .env    # set IG_USERNAME / IG_PASSWORD / thresholds
```

> **Windows PowerShell** works too:
> ```powershell
> python -m venv .venv
> .\.venv\Scripts\Activate.ps1
> pip install -r requirements.txt
> copy .env.example .env
> ```

---

## Usage

Run everything with `python main.py <command>`.

### Overview

```bash
python main.py stats
```

```
@your_account - stats
followers                             842
following                           1 203
mutuals                               510
fans (they follow, you don't)         332
non-followers (you follow, they don't) 693
```

### List categories

```bash
python main.py list-mutuals          # follow each other
python main.py list-fans             # follow you, you don't follow them
python main.py list-non-followers    # you follow them, they don't follow you
python main.py list-traitors         # non-followers below threshold (targets)
```

### Unfollow traitors

```bash
# 1) Dry-run first to see what would happen:
python main.py unfollow-traitors --dry-run

# 2) If OK, run for real with global confirmation:
python main.py unfollow-traitors

# Variants:
python main.py unfollow-traitors --confirm   # confirm each account (y/n)
python main.py unfollow-traitors -y          # skip global confirmation
```

By default the command:

- respects the **whitelist** in `.env` (`WHITELIST=friend1,friend2,...`)
- skips **verified** accounts (unless `TRAITOR_INCLUDE_VERIFIED=true`)
- performs **at most `UNFOLLOW_MAX_PER_RUN` actions per run** (40 by default)
- waits between **`UNFOLLOW_DELAY_MIN`** and **`UNFOLLOW_DELAY_MAX`** seconds
  between each unfollow
- takes a **long break** (5 to 10 min) every `UNFOLLOW_PAUSE_EVERY` actions

### Refresh the cache

Results from `user_followers` / `user_following` / `user_info` are **cached on
disk** (under `data/`) for speed and to avoid hammering the API. To force a
rescan:

```bash
python main.py --refresh stats
```

---

## How it works

- `traitor_hunter/client.py`: login via [`instagrapi`](https://github.com/subzeroid/instagrapi),
  session persisted in `data/session.json` (no need to log in every run, fewer
  anti-bot flags).
- `traitor_hunter/analysis.py`: loads followers and following, computes
  `mutuals / fans / non_followers`, then hydrates accounts with
  `follower_count` (slowest step, hence `data/user_info_cache.json`).
- `traitor_hunter/actions.py`: sequential unfollow with random delays and
  periodic long pauses.

---

## Configuration (`.env`)

Everything is documented in [`.env.example`](.env.example). Main variables:

| Variable | Default | Role |
|---|---|---|
| `IG_USERNAME` / `IG_PASSWORD` | *(required)* | Your IG credentials |
| `IG_TOTP_SEED` | *(empty)* | TOTP secret if 2FA (otherwise enter the code manually) |
| `TRAITOR_FOLLOWER_THRESHOLD` | `10000` | Below this = potential traitor |
| `TRAITOR_INCLUDE_VERIFIED` | `false` | Include verified accounts |
| `WHITELIST` | *(empty)* | `user1,user2,user3`, never unfollow |
| `UNFOLLOW_MAX_PER_RUN` | `40` | Limit per run |
| `UNFOLLOW_DELAY_MIN` / `MAX` | `35` / `90` | Anti-ban delays (seconds) |

---

## Tips to avoid getting banned

1. **Start small.** 20 to 40 unfollows per day max for about a week.
2. **Keep the same IP** (same WSL, same VPN, or none).
3. **Keep the session** (`data/session.json`): do not delete it between runs.
4. **Do not run in a tight loop**: 1 to 2 runs per day max.
5. **2FA + IG app active on your phone**: helps the anti-bot side of things.

---

## Project layout

```
insta-traitor-hunter/
├── main.py                  # CLI (argparse)
├── requirements.txt
├── .env.example
├── .gitignore
├── traitor_hunter/
│   ├── __init__.py
│   ├── config.py            # .env parsing
│   ├── client.py            # login + persistent session
│   ├── analysis.py          # snapshot + traitor detection
│   └── actions.py           # rate-limited unfollow / follow
└── data/                    # caches + session (gitignored)
```

---

## License

MIT: use at your own risk.
