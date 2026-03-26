#!/bin/bash
# Initialise Apache Superset, then create all dashboards via the REST API.
set -e

echo "=== Quantum MITM — Superset initialisation ==="

# 1. Run DB migrations
superset db upgrade

# 2. Create admin user (idempotent — fails silently if already exists)
superset fab create-admin \
    --username admin \
    --firstname Admin \
    --lastname User \
    --email admin@quantum-mitm.local \
    --password admin 2>/dev/null || true

# 3. Initialise roles and permissions
superset init

# 4. Start Superset server in the background
echo "Starting Superset server on :8088 ..."
superset run -p 8088 --with-threads &
SUPERSET_PID=$!

# 5. Wait until the health endpoint responds (max 120 s)
echo "Waiting for Superset to be ready..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:8088/health >/dev/null 2>&1; then
        echo "Superset is ready."
        break
    fi
    sleep 2
done

# 6. Create database connection, datasets, charts, and dashboard
echo "Creating dashboards..."
python /app/init_dashboards.py || echo "[WARN] Dashboard init encountered errors — continuing."

echo "=== Superset ready at http://localhost:8088 (admin / admin) ==="

# 7. Keep the container alive
wait $SUPERSET_PID
