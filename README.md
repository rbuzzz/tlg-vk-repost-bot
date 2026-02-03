# Telegram -> VK Repost Bot (Long Polling)

A production-ready Telegram channel repost bot that **uses long polling only** (no webhooks) and runs as two long-living background services: a **poller** (ingest + enqueue) and a **worker** (download, upload, post). It preserves text and media as fully as possible and prevents duplicates through strict idempotency.

## What this bot does
- Long-polls Telegram with `getUpdates` and stores updates in PostgreSQL.
- Normalizes posts and media (photos, albums, videos, documents).
- Aggregates albums (`media_group_id`) into a single VK post.
- Uploads media to VK and posts to your community wall.
- Ensures **no duplicate VK posts** for the same Telegram `channel_id + message_id`.
- Supports retries/backoff, structured logging, and admin commands in Telegram private chat.

## Architecture (two processes)
- **Poller** (`python -m app.tg.polling`):
  - Long polls Telegram, stores updates in DB, enqueues tasks.
  - Lightweight and non-blocking.
- **Worker** (`celery -A app.tasks.celery_app worker -l INFO`):
  - Downloads media, uploads to VK, posts to wall.
  - Handles album finalization and idempotency.

## Repository layout
```
repo/
  README.md
  docker-compose.yml
  .env.example
  .gitignore
  pyproject.toml
  requirements.txt
  alembic.ini
  alembic/
    env.py
    versions/
  app/
    __init__.py
    config.py
    logging_setup.py
    db.py
    models.py
    crud.py
    tg/
      __init__.py
      client.py
      polling.py
      updates.py
      album_aggregator.py
      commands.py
      formatting.py
    vk/
      __init__.py
      client.py
      uploads.py
      wall.py
      types.py
    tasks/
      __init__.py
      celery_app.py
      repost.py
      utils.py
    utils/
      __init__.py
      files.py
      retry.py
      locks.py
  scripts/
    init_db.sh
    run_poller.sh
    run_worker.sh
    deploy_server.sh
```

---

# Quick Start (Local)

## Prerequisites
- **Python 3.11+**
- **Docker Desktop** (for PostgreSQL + Redis)
- Git (optional but recommended)

## 1) Create `.env`
Copy the template and fill in tokens/IDs:

**Windows (PowerShell)**
```powershell
Copy-Item .env.example .env
notepad .env
```

**Linux/macOS (bash/zsh)**
```bash
cp .env.example .env
nano .env
```

Minimum required values in `.env`:
- `TG_BOT_TOKEN`
- `ADMIN_IDS`
- `VK_GROUP_ID`
- `VK_ACCESS_TOKEN`
- `DATABASE_URL`
- `REDIS_URL`

If you run the **Python app locally** (not in Docker), set:
```
DATABASE_URL=postgresql+psycopg://tg_vk_bot:tg_vk_bot@localhost:5432/tg_vk_bot
REDIS_URL=redis://localhost:6379/0
```
If you run the **app in Docker**, keep the default `postgres`/`redis` hostnames.

## 2) Start PostgreSQL + Redis (Docker)
**Windows (PowerShell)**
```powershell
docker compose up -d postgres redis
```

**Linux/macOS (bash/zsh)**
```bash
docker compose up -d postgres redis
```

Expected output (example):
```
[+] Running 2/2
 OK Container repo-postgres-1  Started
 OK Container repo-redis-1     Started
```

## 3) Create a virtual environment + install deps
**Windows (PowerShell)**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Linux/macOS (bash/zsh)**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4) Run migrations
**Windows (PowerShell)**
```powershell
alembic upgrade head
```

**Linux/macOS (bash/zsh)**
```bash
alembic upgrade head
```

## 5) Run poller and worker (two terminals)
Terminal A:

**Windows (PowerShell)**
```powershell
python -m app.tg.polling
```

**Linux/macOS (bash/zsh)**
```bash
python -m app.tg.polling
```

Terminal B:

**Windows (PowerShell)**
```powershell
celery -A app.tasks.celery_app worker -l INFO
```

**Linux/macOS (bash/zsh)**
```bash
celery -A app.tasks.celery_app worker -l INFO
```

You should start seeing JSON-style log lines indicating polling and task processing.

---

# Development (Quality Checks)

Install dev tools:
`ash
pip install -r requirements-dev.txt
` 

Run checks locally:
`ash
ruff check .
mypy app
pytest
` 

CI runs the same checks on every push/PR.

---

# Quick Start (Server with Docker) - Recommended

## Prerequisites on the server
- Linux server with Docker + Docker Compose v2 plugin
- Git installed
- Open firewall for outbound HTTPS (Telegram/VK APIs)

## Step-by-step
1) **Install Docker + Compose** (package names depend on your OS)
2) **Install Git**
3) **Clone your repo**
4) **Create `.env` from `.env.example`**
5) **Start the stack**

Commands (example):
```bash
sudo apt-get update
sudo apt-get install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker

# Clone
cd /opt
sudo git clone YOUR_GITHUB_REPO_URL tg-vk-bot
cd tg-vk-bot

# Configure
sudo cp .env.example .env
sudo nano .env

# Start
sudo docker compose up -d

# Run migrations once
sudo docker compose run --rm poller alembic upgrade head
```

Check status/logs:
```bash
sudo docker compose ps
sudo docker compose logs -f poller
sudo docker compose logs -f worker
```

Restart services:
```bash
sudo docker compose restart poller worker
```

---

# Alternative: systemd deployment (without Docker)

If you prefer systemd, run PostgreSQL + Redis separately (installed from OS packages), then use these unit files.

## Example unit: `tg_vk_poller.service`
```
[Unit]
Description=Telegram VK Bot Poller
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/tg-vk-bot
EnvironmentFile=/opt/tg-vk-bot/.env
ExecStart=/opt/tg-vk-bot/.venv/bin/python -m app.tg.polling
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Example unit: `tg_vk_worker.service`
```
[Unit]
Description=Telegram VK Bot Worker
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/tg-vk-bot
EnvironmentFile=/opt/tg-vk-bot/.env
ExecStart=/opt/tg-vk-bot/.venv/bin/celery -A app.tasks.celery_app worker -l INFO
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tg_vk_poller.service
sudo systemctl enable --now tg_vk_worker.service
```

Logs:
```bash
sudo journalctl -u tg_vk_poller.service -f
sudo journalctl -u tg_vk_worker.service -f
```

---

# GitHub workflow (local -> GitHub -> server)

## 1) Create local repo and commit
```bash
git init
git add .
git commit -m "Initial commit"
```

## 2) Create a GitHub repo and set remote
```bash
git remote add origin YOUR_GITHUB_REPO_URL
git branch -M main
git push -u origin main
```

## 3) Server deploy from GitHub
```bash
cd /opt
sudo git clone YOUR_GITHUB_REPO_URL tg-vk-bot
cd tg-vk-bot
sudo cp .env.example .env
sudo nano .env
sudo docker compose up -d
sudo docker compose run --rm poller alembic upgrade head
```

## 4) Update workflow
**Local:**
```bash
git pull
# make changes

git add .
git commit -m "Update"
git push
```

**Server:**
```bash
cd /opt/tg-vk-bot
sudo git pull
sudo docker compose build
sudo docker compose up -d
```

Verify:
```bash
sudo docker compose logs -f poller
sudo docker compose logs -f worker
```

---

# Configuration (.env)

Key settings:
- `TG_BOT_TOKEN`: Telegram Bot token.
- `ADMIN_IDS`: Comma-separated Telegram user IDs allowed to use admin commands.
- `SOURCE_CHANNEL_IDS`: Comma-separated channel IDs. Empty = accept all channels.
- `VK_GROUP_ID`: Community ID (positive number). Posts use `owner_id = -VK_GROUP_ID`.
- `VK_ACCESS_TOKEN`: Group token.
- `VK_USER_ACCESS_TOKEN`: Optional fallback user token for uploads.
- `MODE`: `auto` or `moderation` (manual posting).
- `LIMIT_STRATEGY`: `truncate` or `split_posts`.
- `ALBUM_FINALIZE_DELAY_SEC`: Wait time before finalizing albums.
- `MAX_FILE_SIZE_MB`: Skip uploads larger than this limit.
- `DATABASE_URL`, `REDIS_URL`: Infrastructure connections.
- `TEMP_DIR`: Temporary file location.

---

# Admin commands (Telegram private chat)
Only users in `ADMIN_IDS` can run these.
- `/help`
- `/status`
- `/enable` / `/disable`
- `/last N`
- `/repost <channel_id> <message_id>` or `/repost <message_id>`
- `/retry_failed N`
- `/set_target <vk_group_id>`
- `/set_source <channel_id or @channel>`
- `/set_mode auto|moderation`

---

# How to get tokens (high-level)

## Telegram Bot token
1) Open BotFather in Telegram.
2) Create a new bot and copy the token.

## VK tokens
- Create a **community access token** for your VK group.
- If uploads fail due to permissions, add a **user access token** as `VK_USER_ACCESS_TOKEN`.

---

# Telegram channel setup
1) Add your bot as an **admin** to the Telegram channel.
2) Post a test message in the channel.
3) Confirm the bot receives updates (poller logs show ingestion).

**Channel ID format**: for channels it usually looks like `-1001234567890`.

---

# Operational checklist

## Before deploy
- Run migrations: `alembic upgrade head`
- Ensure `.env` is correct (tokens + IDs)
- Confirm Telegram bot is admin in channels

## After deploy
- Check logs (`docker compose logs -f poller`)
- Run `/status` in Telegram admin chat
- Post a test message and verify it appears on VK

---

# Security basics
- **Never commit `.env`** or tokens.
- Rotate tokens regularly if any are exposed.
- Use least-privilege tokens (group tokens preferred).
- Restrict server access and keep Docker/OS updated.

---

# Troubleshooting

## Telegram: getUpdates conflict / multiple pollers
**Symptom:** errors like "Conflict: terminated by other getUpdates request".
**Fix:** Ensure only one poller instance is running.

## File download issues
**Symptom:** skipped files or missing attachments.
**Fix:** Check `MAX_FILE_SIZE_MB`. Large files are skipped by design.

## VK permission errors
**Symptom:** VK API errors like access denied.
**Fix:** Ensure `VK_ACCESS_TOKEN` has correct rights or add `VK_USER_ACCESS_TOKEN`.

## VK rate limits
**Symptom:** VK API errors during bursts.
**Fix:** Wait and retry; consider reducing posting frequency.

## Attachments > 10
**Symptom:** missing attachments on VK.
**Fix:** VK allows max 10. Set `LIMIT_STRATEGY=split_posts` to split into multiple posts.

## Database connection failures
**Symptom:** errors connecting to PostgreSQL.
**Fix:** Check `DATABASE_URL`, container status, and firewall.

---

# Operational notes
- Only one poller should run at a time.
- Worker can scale, but idempotency prevents duplicates.
- Long polling is required; webhooks are intentionally not used.

