#!/usr/bin/env bash
# ============================================================
# Bob — AWS Deployment Script
#
# Usage:
#   ./infra/scripts/deploy.sh              # Code deploy only
#   ./infra/scripts/deploy.sh --infra      # Create/update CloudFormation stack + deploy code
#   ./infra/scripts/deploy.sh --infra-only # Create/update stack only, skip code deploy
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CF_TEMPLATE="$PROJECT_ROOT/infra/cloudformation/bob-infra.yaml"

# ---------------------------------------------------------------------------
# Load configuration
# ---------------------------------------------------------------------------
DEPLOY_ENV="$SCRIPT_DIR/deploy.env"
if [ ! -f "$DEPLOY_ENV" ]; then
    echo "ERROR: $DEPLOY_ENV not found."
    echo "Copy deploy.env.example to deploy.env and fill in your values."
    exit 1
fi
# shellcheck disable=SC1090
source "$DEPLOY_ENV"

# Validate required variables
REQUIRED_VARS=(
    DOMAIN_NAME SUBDOMAIN_NAME HOSTED_ZONE_ID
    KEY_PAIR_NAME SSH_KEY_PATH DB_PASSWORD
    JWT_SECRET API_KEY
)
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: $var is not set in deploy.env"
        exit 1
    fi
done

# Defaults
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-default}"
STACK_NAME="${STACK_NAME:-bob-prod}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t4g.small}"
ROOT_VOLUME_SIZE="${ROOT_VOLUME_SIZE:-30}"
TRUSTED_SSH_CIDR="${TRUSTED_SSH_CIDR:-0.0.0.0/0}"
REMOTE_USER="${REMOTE_USER:-ec2-user}"
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-$STACK_NAME}"
ORIGIN_SUBDOMAIN="${ORIGIN_SUBDOMAIN:-bob-origin}"

FULL_DOMAIN="${SUBDOMAIN_NAME}.${DOMAIN_NAME}"
export AWS_DEFAULT_REGION="$AWS_REGION"
export AWS_PROFILE

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------
DEPLOY_INFRA=false
INFRA_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --infra)      DEPLOY_INFRA=true ;;
        --infra-only) DEPLOY_INFRA=true; INFRA_ONLY=true ;;
        --help|-h)
            echo "Usage: $0 [--infra] [--infra-only]"
            echo "  --infra       Deploy CloudFormation stack + application code"
            echo "  --infra-only  Deploy CloudFormation stack only"
            echo "  (no flags)    Deploy application code only (stack must exist)"
            exit 0
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

log() { echo -e "\n\033[1;34m==>\033[0m \033[1m$1\033[0m"; }
ok()  { echo -e "    \033[32m✓\033[0m $1"; }
err() { echo -e "    \033[31m✗\033[0m $1"; }

build_frontend() {
    log "Building frontend..."
    cd "$PROJECT_ROOT/bob-ui"

    if [ ! -d node_modules ]; then
        npm ci
    fi

    npm run build
    ok "Frontend built → bob-ui/dist/"
    cd "$PROJECT_ROOT"
}

deploy_stack() {
    log "Deploying CloudFormation stack: $STACK_NAME"

    if [ ! -f "$CF_TEMPLATE" ]; then
        err "Template not found: $CF_TEMPLATE"
        exit 1
    fi

    aws cloudformation deploy \
        --template-file "$CF_TEMPLATE" \
        --stack-name "$STACK_NAME" \
        --capabilities CAPABILITY_IAM \
        --no-fail-on-empty-changeset \
        --parameter-overrides \
            EnvironmentName="$ENVIRONMENT_NAME" \
            DomainName="$DOMAIN_NAME" \
            SubdomainName="$SUBDOMAIN_NAME" \
            OriginSubdomainName="$ORIGIN_SUBDOMAIN" \
            HostedZoneId="$HOSTED_ZONE_ID" \
            InstanceType="$INSTANCE_TYPE" \
            RootVolumeSize="$ROOT_VOLUME_SIZE" \
            TrustedSshCidr="$TRUSTED_SSH_CIDR" \
            KeyPairName="$KEY_PAIR_NAME" \
            DbPassword="$DB_PASSWORD"

    ok "Stack deployed/updated"
}

get_stack_outputs() {
    log "Reading stack outputs..."

    local outputs
    outputs=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --query 'Stacks[0].Outputs' \
        --output json 2>/dev/null)

    ELASTIC_IP=$(echo "$outputs" | python3 -c "
import json, sys
for o in json.load(sys.stdin):
    if o['OutputKey'] == 'ElasticIp': print(o['OutputValue'])
" 2>/dev/null || echo "")

    DISTRIBUTION_ID=$(echo "$outputs" | python3 -c "
import json, sys
for o in json.load(sys.stdin):
    if o['OutputKey'] == 'DistributionId': print(o['OutputValue'])
" 2>/dev/null || echo "")

    if [ -z "$ELASTIC_IP" ]; then
        err "Could not get ElasticIp from stack outputs."
        err "Set ELASTIC_IP in deploy.env manually."
        exit 1
    fi

    ok "Elastic IP: $ELASTIC_IP"
    ok "Distribution ID: ${DISTRIBUTION_ID:-N/A}"
}

wait_for_ssh() {
    log "Waiting for SSH on $ELASTIC_IP..."
    local max_attempts=30
    local attempt=0
    while [ $attempt -lt $max_attempts ]; do
        if ssh -i "$SSH_KEY_PATH" \
               -o StrictHostKeyChecking=no \
               -o ConnectTimeout=5 \
               -o BatchMode=yes \
               "$REMOTE_USER@$ELASTIC_IP" "echo ok" &>/dev/null; then
            ok "SSH ready"
            return 0
        fi
        attempt=$((attempt + 1))
        echo "    Attempt $attempt/$max_attempts..."
        sleep 10
    done
    err "SSH not available after $max_attempts attempts"
    exit 1
}

sync_code() {
    log "Syncing code to $REMOTE_USER@$ELASTIC_IP:/app/bob/"

    rsync -azh --delete \
        --exclude '.git/' \
        --exclude '.venv/' \
        --exclude 'node_modules/' \
        --exclude 'bob-ui/node_modules/' \
        --exclude '__pycache__/' \
        --exclude '.env' \
        --exclude 'data/' \
        --exclude 'infra/scripts/deploy.env' \
        --exclude '.DS_Store' \
        --exclude '*.pyc' \
        --exclude '.claude/' \
        -e "ssh -i $SSH_KEY_PATH -o StrictHostKeyChecking=no" \
        "$PROJECT_ROOT/" "$REMOTE_USER@$ELASTIC_IP:/app/bob/"

    ok "Code synced"
}

remote_setup() {
    log "Running remote setup on $ELASTIC_IP..."

    ssh -i "$SSH_KEY_PATH" -o StrictHostKeyChecking=no "$REMOTE_USER@$ELASTIC_IP" bash <<REMOTE
set -euo pipefail

echo "--- Python venv ---"
cd /app/bob

if [ ! -d .venv ]; then
    python3.11 -m venv .venv
    echo "Created new venv"
fi

source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements-prod.txt --quiet
echo "Python dependencies installed"

echo "--- .env ---"
if [ ! -f .env ]; then
    cat > .env << 'DOTENVEOF'
LLM_PROVIDER=${LLM_PROVIDER:-local}
LOCAL_MODEL_BASE_URL=${LOCAL_MODEL_BASE_URL:-}
LOCAL_MODEL_NAME=${LOCAL_MODEL_NAME:-}
LOCAL_MODEL_EMBED_NAME=${LOCAL_MODEL_EMBED_NAME:-}
LOCAL_MODEL_API_KEY=${LOCAL_MODEL_API_KEY:-}
API_KEY=${API_KEY}
APP_ENV=production
LOG_LEVEL=INFO
CORS_ORIGINS=https://${FULL_DOMAIN}
BASE_URL=https://${FULL_DOMAIN}
CHROMA_USE_HTTP=false
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE=bob
DB_USERNAME=bob
DB_PASSWORD=${DB_PASSWORD}
MAIL_HOST=box.webdirect.dev
MAIL_PORT=587
MAIL_USERNAME=${MAIL_USERNAME:-mail@example.com}
MAIL_PASSWORD=${MAIL_PASSWORD:-}
MAIL_ENCRYPTION=tls
MAIL_FROM_ADDRESS=${MAIL_FROM_ADDRESS:-mail@example.com}
MAIL_FROM_NAME=Bob
ADMIN_APPROVAL_EMAIL=${ADMIN_APPROVAL_EMAIL:-}
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
SYSTEM_PROMPT=You are Bob, a helpful AI assistant.
DOTENVEOF
    echo "Created .env"
else
    echo ".env already exists — skipping (edit manually on server if needed)"
fi

echo "--- Alembic migrations ---"
cd /app/bob
.venv/bin/alembic upgrade head
echo "Migrations complete"

echo "--- nginx config ---"
sudo tee /etc/nginx/conf.d/bob.conf > /dev/null << 'NGINXEOF'
server {
    listen 80;
    server_name ${FULL_DOMAIN} ${ORIGIN_SUBDOMAIN}.${DOMAIN_NAME};

    client_max_body_size 50M;

    # API proxy (FastAPI)
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # SSE streaming support
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_set_header Connection '';
    }

    # FastAPI meta endpoints
    location ~ ^/(health|docs|redoc|openapi\.json) {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Static assets (hashed filenames — cache forever)
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?|ttf|eot)$ {
        root /app/bob/bob-ui/dist;
        expires max;
        add_header Cache-Control "public, immutable";
        log_not_found off;
        try_files \$uri =404;
    }

    # React SPA (catch-all)
    location / {
        root /app/bob/bob-ui/dist;
        index index.html;
        try_files \$uri \$uri/ /index.html;
    }
}
NGINXEOF

sudo rm -f /etc/nginx/conf.d/default.conf
sudo nginx -t
sudo systemctl restart nginx
echo "nginx configured and restarted"

echo "--- systemd service ---"
sudo tee /etc/systemd/system/bob.service > /dev/null << 'SVCEOF'
[Unit]
Description=Bob AI Agent API
After=network.target mariadb.service
Wants=mariadb.service

[Service]
Type=exec
User=ec2-user
Group=ec2-user
WorkingDirectory=/app/bob
ExecStart=/app/bob/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5
Environment=PATH=/app/bob/.venv/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable bob
sudo systemctl restart bob
echo "Bob service started"

# Verify
sleep 2
if curl -sf http://127.0.0.1:8000/health > /dev/null; then
    echo "✓ Health check passed"
else
    echo "✗ Health check failed — check logs: journalctl -u bob -n 50"
fi

echo "--- Remote setup complete ---"
REMOTE

    ok "Remote setup finished"
}

invalidate_cache() {
    if [ -n "${DISTRIBUTION_ID:-}" ]; then
        log "Invalidating CloudFront cache..."
        aws cloudfront create-invalidation \
            --distribution-id "$DISTRIBUTION_ID" \
            --paths "/*" &>/dev/null || true
        ok "Cache invalidation submitted"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║        Bob — AWS Deployment          ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Step 1: Build frontend
build_frontend

# Step 2: Deploy infrastructure (if --infra)
if [ "$DEPLOY_INFRA" = true ]; then
    deploy_stack
fi

# Get Elastic IP (from stack outputs or deploy.env)
if [ -z "${ELASTIC_IP:-}" ]; then
    get_stack_outputs
else
    DISTRIBUTION_ID="${DISTRIBUTION_ID:-}"
    ok "Using ELASTIC_IP from deploy.env: $ELASTIC_IP"
fi

# Stop here if --infra-only
if [ "$INFRA_ONLY" = true ]; then
    echo ""
    log "Infrastructure deployed. Run without --infra-only to deploy code."
    exit 0
fi

# Step 3: Wait for SSH
wait_for_ssh

# Step 4: Sync code
sync_code

# Step 5: Remote setup
remote_setup

# Step 6: Invalidate CloudFront cache
invalidate_cache

echo ""
log "Deployment complete!"
echo ""
echo "    URL:    https://$FULL_DOMAIN"
echo "    SSH:    ssh -i $SSH_KEY_PATH $REMOTE_USER@$ELASTIC_IP"
echo "    Logs:   ssh ... 'journalctl -u bob -f'"
echo "    Health: curl https://$FULL_DOMAIN/health"
echo ""
