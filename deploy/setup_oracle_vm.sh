#!/bin/bash
# ============================================================================
# Oracle Cloud ARM VM Deployment Script
# Sets up the Finance Bot with Ollama VLM, PostgreSQL, and Nginx
# Run this on a fresh Ubuntu 22.04+ ARM instance (Oracle Always Free A1)
# Usage: chmod +x setup_oracle_vm.sh && sudo ./setup_oracle_vm.sh
# ============================================================================

set -euo pipefail

# --- Configuration ---
APP_USER="${APP_USER:-ubuntu}"
APP_DIR="/home/${APP_USER}/TartanHacks26"
REPO_URL="${REPO_URL:-https://github.com/YOUR_USERNAME/TartanHacks26.git}"
DOMAIN="${DOMAIN:-}"  # Leave empty to use IP address
OLLAMA_MODEL="qwen2.5-vl:7b"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# --- Check root ---
if [ "$EUID" -ne 0 ]; then
    err "Please run as root: sudo ./setup_oracle_vm.sh"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Finance Bot - Oracle Cloud VM Setup                   ║"
echo "║   ARM A1 (4 OCPU / 24 GB RAM)                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# 1. System packages
# ============================================================================
log "Updating system packages..."
apt update && apt upgrade -y

log "Installing dependencies..."
apt install -y \
    python3.11 python3.11-venv python3.11-dev \
    python3-pip \
    tesseract-ocr \
    poppler-utils \
    postgresql postgresql-contrib \
    nginx certbot python3-certbot-nginx \
    git curl wget unzip \
    build-essential libffi-dev libssl-dev \
    chromium-browser \
    jq

# Make python3.11 the default if not already
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 || true

# ============================================================================
# 2. PostgreSQL setup
# ============================================================================
log "Setting up PostgreSQL..."

# Generate a random password
DB_PASSWORD=$(openssl rand -base64 24 | tr -d '=/+' | head -c 20)
DB_NAME="finance_bot"
DB_USER="finance_bot"

sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" 2>/dev/null || \
    sudo -u postgres psql -c "ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';"
sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" 2>/dev/null || \
    warn "Database ${DB_NAME} already exists"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"

log "PostgreSQL configured: db=${DB_NAME}, user=${DB_USER}"
echo "  DB_PASSWORD=${DB_PASSWORD} (save this!)"

# ============================================================================
# 3. Ollama installation
# ============================================================================
log "Installing Ollama..."
curl -fsSL https://ollama.com/install.sh | sh

# Enable and start ollama service
systemctl enable ollama
systemctl start ollama

# Wait for Ollama to be ready
sleep 5

log "Pulling VLM model (${OLLAMA_MODEL})... This may take 5-10 minutes."
ollama pull "${OLLAMA_MODEL}"

log "Ollama ready with ${OLLAMA_MODEL}"

# ============================================================================
# 4. Application setup
# ============================================================================
log "Setting up application..."

# Clone repo if not exists
if [ ! -d "${APP_DIR}" ]; then
    warn "App directory not found. Clone your repo:"
    echo "  git clone ${REPO_URL} ${APP_DIR}"
    echo "  Or: scp -r ./TartanHacks26 ${APP_USER}@<VM_IP>:~/"
    mkdir -p "${APP_DIR}"
fi

# Create venv and install deps
if [ -f "${APP_DIR}/requirements.txt" ]; then
    sudo -u "${APP_USER}" bash -c "
        cd ${APP_DIR}
        python3 -m venv venv
        source venv/bin/activate
        pip install --upgrade pip
        pip install -r requirements.txt
        pip install sqlalchemy asyncpg psycopg2-binary alembic
        playwright install chromium --with-deps
    "
    log "Python dependencies installed"
else
    warn "requirements.txt not found — install deps manually after cloning repo"
fi

# Append database URL to .env if not present
if [ -f "${APP_DIR}/.env" ]; then
    if ! grep -q "DATABASE_URL" "${APP_DIR}/.env"; then
        echo "" >> "${APP_DIR}/.env"
        echo "# Database" >> "${APP_DIR}/.env"
        echo "DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}" >> "${APP_DIR}/.env"
        echo "" >> "${APP_DIR}/.env"
        echo "# Ollama" >> "${APP_DIR}/.env"
        echo "OLLAMA_URL=http://localhost:11434" >> "${APP_DIR}/.env"
        echo "OLLAMA_MODEL=${OLLAMA_MODEL}" >> "${APP_DIR}/.env"
    fi
fi

# ============================================================================
# 5. Systemd services
# ============================================================================
log "Creating systemd services..."

# Finance Bot service
cat > /etc/systemd/system/finance-bot.service << EOF
[Unit]
Description=Finance Automation Slack Bot
After=network.target postgresql.service ollama.service
Wants=ollama.service

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python main.py --webhook
Restart=always
RestartSec=10
Environment=PATH=${APP_DIR}/venv/bin:/usr/local/bin:/usr/bin
EnvironmentFile=${APP_DIR}/.env

# Resource limits
MemoryMax=4G
CPUQuota=100%

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=finance-bot

[Install]
WantedBy=multi-user.target
EOF

# Web app service (will be used once web app is built)
cat > /etc/systemd/system/finance-web.service << EOF
[Unit]
Description=Finance Bot Web Application
After=network.target postgresql.service ollama.service
Wants=ollama.service

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/uvicorn web.app:app --host 127.0.0.1 --port 8080 --workers 2
Restart=always
RestartSec=10
Environment=PATH=${APP_DIR}/venv/bin:/usr/local/bin:/usr/bin
EnvironmentFile=${APP_DIR}/.env

# Resource limits
MemoryMax=2G
CPUQuota=50%

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=finance-web

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable finance-bot
# Don't start yet — user needs to clone repo and set up .env first

log "Systemd services created (finance-bot, finance-web)"

# ============================================================================
# 6. Nginx reverse proxy
# ============================================================================
log "Configuring Nginx..."

SERVER_NAME="${DOMAIN:-_}"

cat > /etc/nginx/sites-available/finance-bot << EOF
server {
    listen 80;
    server_name ${SERVER_NAME};

    # Web application
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # File upload support (receipts can be large)
        client_max_body_size 25M;
    }

    # Email webhook (Mailgun)
    location /webhook/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    # Health check
    location /health {
        proxy_pass http://127.0.0.1:8080/health;
    }
}
EOF

ln -sf /etc/nginx/sites-available/finance-bot /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl restart nginx
log "Nginx configured"

# Set up SSL if domain provided
if [ -n "${DOMAIN}" ]; then
    log "Setting up SSL with Let's Encrypt..."
    certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos --email "admin@${DOMAIN}" || \
        warn "SSL setup failed — run 'certbot --nginx' manually"
fi

# ============================================================================
# 7. Keepalive cron (prevents Oracle from reclaiming idle instances)
# ============================================================================
log "Setting up keepalive cron job..."

cat > /usr/local/bin/keepalive.sh << 'KEEPALIVE'
#!/bin/bash
# Generate minimal CPU activity to prevent Oracle from reclaiming this instance.
# Oracle reclaims Always Free instances with <20% utilization over 7 days.
dd if=/dev/urandom bs=1M count=50 of=/dev/null 2>/dev/null
# Also verify services are running
systemctl is-active --quiet ollama || systemctl restart ollama
systemctl is-active --quiet finance-bot || systemctl restart finance-bot
KEEPALIVE

chmod +x /usr/local/bin/keepalive.sh

# Run every 6 hours
(crontab -l 2>/dev/null; echo "0 */6 * * * /usr/local/bin/keepalive.sh") | sort -u | crontab -

log "Keepalive cron installed (runs every 6 hours)"

# ============================================================================
# 8. Firewall
# ============================================================================
log "Configuring firewall (iptables)..."

# Oracle Cloud uses iptables, not ufw
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
netfilter-persistent save 2>/dev/null || iptables-save > /etc/iptables/rules.v4

log "Ports 80 and 443 opened"

# ============================================================================
# Done!
# ============================================================================
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   ✅ Setup complete!                                     ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                          ║"
echo "║  Next steps:                                             ║"
echo "║  1. Clone your repo to ${APP_DIR}                        ║"
echo "║  2. Copy .env and credentials/ to the app directory      ║"
echo "║  3. Start the bot:                                       ║"
echo "║     sudo systemctl start finance-bot                     ║"
echo "║  4. Check logs:                                          ║"
echo "║     journalctl -u finance-bot -f                         ║"
echo "║                                                          ║"
echo "║  Database: postgresql://${DB_USER}:****@localhost/${DB_NAME} ║"
echo "║  Ollama:   http://localhost:11434 (${OLLAMA_MODEL})       ║"
echo "║  Web:      http://<VM_PUBLIC_IP>                          ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "⚠️  IMPORTANT: Also open ports 80/443 in Oracle Cloud Console:"
echo "   Networking → Virtual Cloud Networks → Security Lists → Add Ingress Rules"
echo ""
