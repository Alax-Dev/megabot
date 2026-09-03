# MegaBot 🤖⬇️

A professional Telegram bot that downloads files from **MEGA (mega.nz / mega.io)** using your own
MEGA account, analyzes what it downloaded, and delivers it to your Telegram chat — with a smooth,
emoji-rich inline-button UI.

Built on **Pyrogram (MTProto)**, so uploads bypass the 50 MB Bot-API HTTP limit — the bot can send
files up to ~2 GB.

## Features

- 🔗 Paste any `mega.nz` / `mega.io` **file or folder link** — the bot picks it up automatically
- 🔐 Downloads through **your MEGA account** (email + password)
- 📦 **Archive?** You pick: upload the archive as-is, or the bot decompresses it and uploads the contents
  (zip, rar, 7z, tar supported — zip-slip safe extraction)
- 🖼️ **Many images?** Merged into one **PDF** in natural order (`1, 2, 3 … 10, 100`)
- 🎬 **Videos?** Uploaded directly, one after another, with generated thumbnails
- 📊 Live progress bar with speed + ETA, cancel button on every job
- 🗄️ All users, jobs & settings stored in **MongoDB** (motor)
- ⚙️ Per-user settings, per-user concurrency limits, disk-space guard, retry with backoff,
  link dedup cache (24 h), owner panel with stats/ban/broadcast

## Setup

### 1. Requirements

- Python 3.10+
- MongoDB (local or Atlas URI)
- System tools: `ffmpeg` (video thumbnails), `unrar` or `unar` (RAR archives)

```bash
sudo apt install ffmpeg unrar   # Debian/Ubuntu
```

### 2. Credentials

| What | Where |
|---|---|
| `API_ID`, `API_HASH` | https://my.telegram.org → API development tools |
| `BOT_TOKEN` | @BotFather → `/newbot` |
| `MEGA_EMAIL`, `MEGA_PASSWORD` | your MEGA account |
| `OWNER_ID` | your Telegram user id (e.g. via @userinfobot) |

### 3. Install & run

```bash
cd megabot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in your credentials
python main.py
```

### 4. Use

1. `/start`
2. Paste one or more MEGA links
3. Watch the live status card → answer the inline prompts → receive your files

## Owner commands

| Command | Description |
|---|---|
| `/stats` | users, jobs, success rate, disk usage |
| `/ban <id>` / `/unban <id>` | block a user |
| `/broadcast <text>` | send to all users |

## Docker

```bash
docker build -t megabot .
docker run --env-file .env -p 8080:8080 megabot
```

## Project layout

```
config.py            env-based settings
main.py              Pyrogram client bootstrap
megabot/
  core/              MongoDB layer, job queue
  downloaders/       MEGA downloader (extensible)
  analyzers/         content classification
  processors/        archives, images→PDF, uploader
  ui/                texts & inline keyboards
  plugins/           /start, link handler, callbacks, settings, owner
```