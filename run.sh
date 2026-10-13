#!/usr/bin/env bash
# ==============================================================================
# Sollunga AI — Run Bot & Web Dashboard Together
# ==============================================================================

set -e

# Change to the project directory wherever this script is called from
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

# Check virtual environment
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment .venv not found!"
    echo "Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

echo "=========================================================="
echo "🏪 Starting Sollunga AI Services..."
echo "=========================================================="

# Trap SIGINT (Ctrl+C) and SIGTERM to kill background jobs cleanly
cleanup() {
    echo ""
    echo "🛑 Stopping all Sollunga AI services..."
    kill $(jobs -p) 2>/dev/null || true
    wait $(jobs -p) 2>/dev/null || true
    echo "✅ All services stopped."
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Start Web Dashboard on port 8000
echo "🌐 Starting Web Dashboard at: http://localhost:8000"
echo "   (Owner password: check DASHBOARD_PASSWORD in .env)"
.venv/bin/uvicorn web.app:app --host 0.0.0.0 --port 8000 > /tmp/sollunga_web.log 2>&1 &
WEB_PID=$!

# Wait a second for web server to initialize
sleep 1

# Optional: start Cloudflare Tunnel ONLY if WhatsApp is configured.
# The bot runs fully on Telegram without this.
WA_CONFIGURED=0
if grep -qE '^WHATSAPP_PHONE_NUMBER_ID=.+' .env 2>/dev/null && grep -qE '^WHATSAPP_ACCESS_TOKEN=.+' .env 2>/dev/null; then
    WA_CONFIGURED=1
fi

TUNNEL_URL=""
if [ "$WA_CONFIGURED" = "1" ] && [ -f "bin/cloudflared" ]; then
    echo "🌍 WhatsApp configured — starting public tunnel for webhook..."
    ./bin/cloudflared tunnel --url http://localhost:8000 > /tmp/sollunga_tunnel.log 2>&1 &
    TUNNEL_PID=$!
    
    # Wait for tunnel URL to generate
    for i in {1..15}; do
        TUNNEL_URL=$(grep -o 'https://[-a-zA-Z0-9.]*\.trycloudflare\.com' /tmp/sollunga_tunnel.log | head -n 1 || true)
        if [ -n "$TUNNEL_URL" ]; then
            break
        fi
        sleep 1
    done
else
    echo "ℹ️ WhatsApp not configured — running Telegram-only (no tunnel needed)."
fi

# Start Telegram Bot
echo "🤖 Starting Telegram Bot..."
.venv/bin/python bot/main.py &
BOT_PID=$!

echo ""
echo "🚀 All Sollunga AI services are running!"
echo "   • Local Web Dashboard: http://localhost:8000"
if [ -n "$TUNNEL_URL" ]; then
    echo "   • Public Webhook URL:  ${TUNNEL_URL}/whatsapp/webhook"
    echo "     (Paste this in Meta Developer Console -> WhatsApp -> Configuration -> Webhook)"
fi
echo "   • Telegram Bot:        Active (Primary — WhatsApp disabled)"
echo "   (Press Ctrl+C to stop all services)"
echo "----------------------------------------------------------"

# Keep the script running and wait for background processes
wait $WEB_PID $BOT_PID ${TUNNEL_PID:-}

