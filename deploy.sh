#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# BookmarkBrain — deploy to VPS
#
# First time:
#   1. Buy VPS (Ubuntu 22.04+, 2 CPU, 4GB RAM)
#   2. Install Docker: https://docs.docker.com/engine/install/ubuntu/
#   3. ssh root@YOUR_IP
#   4. git clone https://github.com/OGUREC04/bookmark-brain.git
#   5. cd bookmark-brain
#   6. cp .env.production.example .env
#   7. nano .env   # fill in real values
#   8. chmod +x deploy.sh && ./deploy.sh
#
# Update:
#   cd bookmark-brain && git pull && ./deploy.sh
# ============================================================

echo "=== BookmarkBrain Deploy ==="

# ── 1. Check Docker ──────────────────────────────────
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker not installed."
    echo "Install: https://docs.docker.com/engine/install/ubuntu/"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo "ERROR: docker compose not found (need Docker 20.10+)"
    exit 1
fi

# ── 2. Check .env exists ─────────────────────────────
if [ ! -f .env ]; then
    echo "ERROR: .env file not found!"
    echo "  cp .env.production.example .env"
    echo "  nano .env  # fill in real values"
    exit 1
fi

# ── 3. Validate required env vars (safe parsing) ─────
REQUIRED_VARS="POSTGRES_PASSWORD TELEGRAM_BOT_TOKEN SECRET_KEY BOT_SECRET"
PLACEHOLDERS="CHANGE_ME_STRONG_PASSWORD_HERE CHANGE_ME_GENERATE_RANDOM_KEY"

for var in $REQUIRED_VARS; do
    val=$(grep -E "^${var}=" .env | head -1 | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    if [ -z "$val" ]; then
        echo "ERROR: $var is not set in .env"
        exit 1
    fi
    for ph in $PLACEHOLDERS; do
        if [ "$val" = "$ph" ]; then
            echo "ERROR: $var still has placeholder value"
            exit 1
        fi
    done
done
echo ">>> .env validated"

# ── 4. Build and start ───────────────────────────────
echo ">>> Building containers..."
docker compose -f docker-compose.prod.yml build

echo ">>> Starting services..."
docker compose -f docker-compose.prod.yml up -d --wait

# ── 5. Show status ───────────────────────────────────
echo ""
echo "=== Status ==="
docker compose -f docker-compose.prod.yml ps
echo ""
echo "=== Useful commands ==="
echo "  Logs:     docker compose -f docker-compose.prod.yml logs -f"
echo "  Backend:  docker compose -f docker-compose.prod.yml logs -f backend"
echo "  Bot:      docker compose -f docker-compose.prod.yml logs -f bot"
echo "  Worker:   docker compose -f docker-compose.prod.yml logs -f worker"
echo "  Stop:     docker compose -f docker-compose.prod.yml down"
echo "  Restart:  docker compose -f docker-compose.prod.yml restart"
echo "  Update:   git pull && ./deploy.sh"
echo "  DB shell: docker compose -f docker-compose.prod.yml exec postgres psql -U bookmarkbrain"
echo ""
echo "=== Done! Bot should be responding in Telegram ==="
