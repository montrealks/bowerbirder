#!/bin/bash
# Deploy Bowerbirder to VPS
# Usage: ./deploy.sh [--frontend]

set -e

VPS="vps"
REMOTE_DIR="~/bowerbirder"

echo "Pulling latest code on VPS..."
ssh $VPS "cd $REMOTE_DIR && git pull"

echo "Rebuilding Docker containers..."
ssh $VPS "cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml up -d --build"

echo "Connecting API to Caddy network..."
ssh $VPS "docker network connect caddy bowerbirder-api-1 2>/dev/null || true"

# Rebuild frontend if --frontend flag is passed
if [[ "$1" == "--frontend" ]]; then
    echo "Building and deploying frontend..."
    ssh $VPS "cd $REMOTE_DIR/frontend && npm install && npm run build && cp -r build/* /srv/bowerbirder/frontend/"
fi

echo "Checking health..."
sleep 3
curl -s https://bowerbirder.pressive.in/health

echo ""
echo "Deploy complete!"
