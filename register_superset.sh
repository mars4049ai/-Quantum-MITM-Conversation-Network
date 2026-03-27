#!/usr/bin/env bash
# ============================================================
# register_superset.sh
# Creates an admin user in Apache Superset and initialises it.
#
# Usage (all arguments optional):
#   ./register_superset.sh [username] [email] [password]
#
# Defaults (used when arguments are not provided):
#   username : admin
#   email    : admin@admin.com
#   password : postgres123
#
# Example — custom credentials:
#   ./register_superset.sh myuser myuser@example.com mypassword
#
# Example — use defaults:
#   ./register_superset.sh
# ============================================================

SS_USER="${1:-admin}"
SS_EMAIL="${2:-admin@admin.com}"
SS_PASS="${3:-postgres123}"

echo ""
echo "[Superset] Registering admin user..."
echo "  Username : ${SS_USER}"
echo "  Email    : ${SS_EMAIL}"
echo ""

docker exec -it superset superset fab create-admin \
    --username "${SS_USER}" \
    --firstname Superset \
    --lastname Admin \
    --email "${SS_EMAIL}" \
    --password "${SS_PASS}"

echo ""
echo "[Superset] Running database upgrade..."
docker exec -it superset superset db upgrade

echo ""
echo "[Superset] Loading examples..."
docker exec -it superset superset load_examples

echo ""
echo "[Superset] Initialising roles and permissions..."
docker exec -it superset superset init

echo ""
echo "============================================================"
echo " Done! Open http://localhost:8088 and log in with:"
echo "   Username : ${SS_USER}"
echo "   Password : ${SS_PASS}"
echo "============================================================"
echo ""
