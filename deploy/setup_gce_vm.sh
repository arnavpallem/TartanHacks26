#!/bin/bash
# ============================================================================
# Google Compute Engine VM Deployment Script
# Sets up TPRobot with FastAPI, PostgreSQL, Nginx, and Clerk auth
# Run on a fresh Ubuntu 22.04+ GCE instance (e2-micro free tier)
# Usage: chmod +x setup_gce_vm.sh && sudo ./setup_gce_vm.sh
# ============================================================================

set -euo pipefail

# --- Configuration ---
APP_USER="${APP_USER:-$(logname 2>/dev/null || echo ubuntu)}"
APP_DIR="/home/${APP_USER}/TartanHacks26"
REPO_URL="${REPO_URL:-https://github.com/YOUR_USERNAME/TartanHacks26.git}"
DOMAIN="${DOMAIN:-}"  # Leave empty to use IP address

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
    err "Please run as root: sudo ./setup_gce_vm.sh"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   TPRobot - Google Compute Engine Setup                  ║"
echo "║   e2-micro (0.25 vCPU / 1 GB RAM) — Free Tier           ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# 1. System packages
# ============================================================================
log "Updating system packages..."
apt update && apt upgrade -y

log "Installing dependencies..."
apt install -y \
    python3 python3-venv python3-dev \
    python3-pip \
    tesseract-ocr \
    poppler-utils \
    postgresql postgresql-contrib \
    nginx certbot python3-certbot-nginx \
    git curl wget unzip \
    build-essential libffi-dev libssl-dev \
    jq

# ============================================================================
# 2. Swap file (critical for 1 GB RAM)
# ============================================================================
log "Setting up 2 GB swap file..."

if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    log "Swap file created (2 GB)"
else
    warn "Swap file already exists"
fi

# Optimize for low memory
cat > /etc/sysctl.d/99-low-memory.conf << 'SYSCTL'
vm.swappiness=60
vm.vfs_cache_pressure=50
SYSCTL
sysctl --system > /dev/null 2>&1

# ============================================================================
# 3. PostgreSQL setup
# ============================================================================
log "Setting up PostgreSQL..."

# Generate a random password
DB_PASSWORD=$(openssl rand -base64 24 | tr -d '=/+' | head -c 20)
DB_NAME="tprobot"
DB_USER="tprobot"

sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" 2>/dev/null || \
    sudo -u postgres psql -c "ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';"
sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" 2>/dev/null || \
    warn "Database ${DB_NAME} already exists"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"

# Tune PostgreSQL for 1 GB RAM
cat > /etc/postgresql/*/main/conf.d/low-memory.conf << 'PGCONF'
shared_buffers = 64MB
effective_cache_size = 256MB
work_mem = 2MB
maintenance_work_mem = 32MB
max_connections = 20
PGCONF
systemctl restart postgresql

log "PostgreSQL configured: db=${DB_NAME}, user=${DB_USER}"
echo "  DB_PASSWORD=${DB_PASSWORD} (save this!)"

# ============================================================================
# 4. Application setup
# ============================================================================
log "Setting up application..."

# Clone repo if not exists
if [ ! -d "${APP_DIR}" ]; then
    warn "App directory not found. Clone your repo:"
    echo "  git clone ${REPO_URL} ${APP_DIR}"
    echo "  Or: gcloud compute scp --recurse ./TartanHacks26 ${APP_USER}@tprobot:~/"
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
    "
    log "Python dependencies installed"
else
    warn "requirements.txt not found — install deps manually after cloning repo"
fi

# Create temp directory for uploads
sudo -u "${APP_USER}" mkdir -p "${APP_DIR}/temp/uploads"

# Write database URL to .env if .env exists
if [ -f "${APP_DIR}/.env" ]; then
    if ! grep -q "DATABASE_URL" "${APP_DIR}/.env"; then
        echo "" >> "${APP_DIR}/.env"
        echo "# Database" >> "${APP_DIR}/.env"
        echo "DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}" >> "${APP_DIR}/.env"
    fi
fi

# ============================================================================
# 5. Systemd services
# ============================================================================
log "Creating systemd services..."

# Slack bot service (independent of web app)
cat > /etc/systemd/system/tprobot-bot.service << EOF
[Unit]
Description=TPRobot Slack Bot
After=network.target postgresql.service

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python main.py --webhook
Restart=always
RestartSec=10
Environment=PATH=${APP_DIR}/venv/bin:/usr/local/bin:/usr/bin
EnvironmentFile=${APP_DIR}/.env

# Low memory limits for e2-micro
MemoryMax=300M
CPUQuota=50%

StandardOutput=journal
StandardError=journal
SyslogIdentifier=tprobot-bot

[Install]
WantedBy=multi-user.target
EOF

# Web app service
cat > /etc/systemd/system/tprobot-web.service << EOF
[Unit]
Description=TPRobot Web Application
After=network.target postgresql.service

[Service]
Type=simple
User=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/uvicorn web.app:app --host 127.0.0.1 --port 8080 --workers 1
Restart=always
RestartSec=10
Environment=PATH=${APP_DIR}/venv/bin:/usr/local/bin:/usr/bin
EnvironmentFile=${APP_DIR}/.env

# Low memory limits for e2-micro
MemoryMax=300M
CPUQuota=50%

StandardOutput=journal
StandardError=journal
SyslogIdentifier=tprobot-web

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable tprobot-web
# Don't enable bot by default — user may not need it on this server

log "Systemd services created (tprobot-bot, tprobot-web)"

# ============================================================================
# 6. Nginx reverse proxy
# ============================================================================
log "Configuring Nginx..."

SERVER_NAME="${DOMAIN:-_}"

cat > /etc/nginx/sites-available/tprobot << EOF
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

        # File upload support (receipts)
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

ln -sf /etc/nginx/sites-available/tprobot /etc/nginx/sites-enabled/
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
# 7. Firewall (GCE uses ufw, not iptables)
# ============================================================================
log "Configuring firewall (ufw)..."

ufw allow 22/tcp   # SSH
ufw allow 80/tcp   # HTTP
ufw allow 443/tcp  # HTTPS
ufw --force enable

log "Firewall configured (ports 22, 80, 443)"

# ============================================================================
# Done!
# ============================================================================
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   ✅ Setup complete!                                     ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                          ║"
echo "║  Next steps:                                             ║"
echo "║  1. Clone your repo to ${APP_DIR}"
echo "║  2. Copy .env with your API keys                         ║"
echo "║  3. Start the web app:                                   ║"
echo "║     sudo systemctl start tprobot-web                     ║"
echo "║  4. (Optional) Start Slack bot:                          ║"
echo "║     sudo systemctl start tprobot-bot                     ║"
echo "║  5. Check logs:                                          ║"
echo "║     journalctl -u tprobot-web -f                         ║"
echo "║                                                          ║"
echo "║  Database: postgresql://${DB_USER}:****@localhost/${DB_NAME}"
echo "║  Web:      http://<VM_EXTERNAL_IP>                       ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "💡 TIP: GCE firewall rules are in the Cloud Console:"
echo "   VPC Network → Firewall → default-allow-http should exist"
echo "   (created automatically when you checked 'Allow HTTP traffic')"
echo ""
echo "📦 Memory usage:"
free -h
echo ""
