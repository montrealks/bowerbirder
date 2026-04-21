#!/bin/bash
# Webhook-receiver deploy. Called by /srv/webhook-receiver.py on master pushes.
set -e
cd /srv/bowerbirder
git pull origin master
docker compose -f docker-compose.prod.yml up -d --build
echo "Deployed bowerbirder at $(date -u +%FT%TZ)"
