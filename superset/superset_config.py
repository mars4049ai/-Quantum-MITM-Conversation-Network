"""
Superset configuration for Quantum MITM Detection demo.
Placed at /app/pythonpath/superset_config.py inside the container.
"""

SECRET_KEY = "quantum_mitm_secret_key_change_in_prod"

# Use the mounted volume for the SQLite metadata DB
SQLALCHEMY_DATABASE_URI = "sqlite:////app/superset_home/superset.db"

# Allow iframe embedding (useful for dashboards)
WTF_CSRF_ENABLED = True
WTF_CSRF_EXEMPT_LIST = []

# Disable email verification on signup (not needed for demo)
AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = "Public"

# Feature flags
FEATURE_FLAGS = {
    "ENABLE_TEMPLATE_PROCESSING": True,
    "DASHBOARD_NATIVE_FILTERS": True,
    "DASHBOARD_CROSS_FILTERS": True,
}

# Silence noisy warnings
SILENCE_FAB = True
