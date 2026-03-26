FROM apache/superset:4.1.4

USER root

# psycopg2 for PostgreSQL connectivity
RUN pip install --no-cache-dir psycopg2-binary requests

COPY init_superset.sh   /app/init_superset.sh
COPY init_dashboards.py /app/init_dashboards.py
RUN chmod +x /app/init_superset.sh

USER superset

ENV SUPERSET_SECRET_KEY="quantum_mitm_secret_key_change_in_prod"
ENV FLASK_APP="superset"

CMD ["/app/init_superset.sh"]
