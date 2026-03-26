#!/usr/bin/env python3
"""
Superset dashboard initialisation for Quantum MITM Detection.

Programmatically creates (via Superset REST API):
  1. A PostgreSQL database connection
  2. Datasets for every SQL table + several virtual (SQL-based) datasets
  3. Charts:
       • Communication graph  — clients & hackers, edges coloured by status
         (green = protected, red = attacked, grey = broken)
       • Top 10 Hackers       — bar chart
       • Most Attacked Clients— bar chart
       • Attack Timeline      — line chart
       • Big numbers          — Total Messages / Total Attacks / Detection Rate
       • Session Topics       — table
       • Hacker Decryption Attempts — table (shows QBER + garbage output)
       • Full data tables     — messages, alerts, hackers
  4. A single "Quantum MITM Dashboard" combining all charts.

Run this script AFTER Superset has finished starting up (init_superset.sh
waits for /health before calling this script).
"""

import json
import sys
import time

import requests

BASE_URL  = "http://localhost:8088"
ADMIN     = "admin"
PASSWORD  = "postgres123"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

class SupersetClient:
    def __init__(self):
        self.session = requests.Session()
        self.access_token = None
        self._login()

    def _login(self):
        resp = self.session.post(
            f"{BASE_URL}/api/v1/security/login",
            json={"username": ADMIN, "password": PASSWORD, "provider": "db",
                  "refresh": True},
        )
        resp.raise_for_status()
        self.access_token = resp.json()["access_token"]
        self.session.headers.update(
            {"Authorization": f"Bearer {self.access_token}"}
        )
        # Fetch CSRF token
        csrf_resp = self.session.get(f"{BASE_URL}/api/v1/security/csrf_token/")
        csrf_resp.raise_for_status()
        self.session.headers.update(
            {"X-CSRFToken": csrf_resp.json()["result"]}
        )

    def post(self, path, payload):
        r = self.session.post(f"{BASE_URL}{path}", json=payload)
        if r.status_code not in (200, 201):
            print(f"  [WARN] POST {path} → {r.status_code}: {r.text[:200]}")
        return r

    def put(self, path, payload):
        r = self.session.put(f"{BASE_URL}{path}", json=payload)
        if r.status_code not in (200, 201):
            print(f"  [WARN] PUT {path} → {r.status_code}: {r.text[:200]}")
        return r


# ---------------------------------------------------------------------------
# Step 1 — Database connection
# ---------------------------------------------------------------------------

def create_database(client: SupersetClient) -> int:
    print("Creating database connection...")
    payload = {
        "database_name": "Quantum MITM PostgreSQL",
        "sqlalchemy_uri": (
            "postgresql+psycopg2://hackathon:hackathon@postgres:5432/streaming"
        ),
        "expose_in_sqllab": True,
        "allow_run_async": True,
    }
    r = client.post("/api/v1/database/", payload)
    db_id = r.json().get("id")
    if not db_id:
        # Already exists — look it up
        r2 = client.session.get(f"{BASE_URL}/api/v1/database/")
        for db in r2.json().get("result", []):
            if "Quantum" in db.get("database_name", ""):
                db_id = db["id"]
                break
    print(f"  database_id = {db_id}")
    return db_id


# ---------------------------------------------------------------------------
# Step 2 — Datasets
# ---------------------------------------------------------------------------

def create_physical_dataset(client, db_id, table_name) -> int:
    print(f"  Creating physical dataset: {table_name}")
    r = client.post("/api/v1/dataset/", {
        "database": db_id,
        "schema": "public",
        "table_name": table_name,
    })
    ds_id = r.json().get("id")
    if not ds_id:
        # Try to find existing
        r2 = client.session.get(
            f"{BASE_URL}/api/v1/dataset/?q=(filters:!((col:table_name,opr:eq,val:{table_name})))"
        )
        results = r2.json().get("result", [])
        if results:
            ds_id = results[0]["id"]
    return ds_id


def create_virtual_dataset(client, db_id, name, sql) -> int:
    print(f"  Creating virtual dataset: {name}")
    r = client.post("/api/v1/dataset/", {
        "database": db_id,
        "schema": "public",
        "table_name": name,
        "sql": sql,
    })
    ds_id = r.json().get("id")
    if not ds_id:
        r2 = client.session.get(
            f"{BASE_URL}/api/v1/dataset/?q=(filters:!((col:table_name,opr:eq,val:{name})))"
        )
        results = r2.json().get("result", [])
        if results:
            ds_id = results[0]["id"]
    return ds_id


VIRTUAL_DATASETS = {
    "communication_graph": """
        SELECT
            st.sender_name   AS source,
            st.receiver_name AS target,
            st.message_count AS value,
            CASE
                WHEN st.channel_status = 'broken' THEN 'broken'
                WHEN EXISTS (
                    SELECT 1 FROM alerts a WHERE a.session_id = st.session_id
                ) THEN 'attacked'
                ELSE 'protected'
            END AS channel_status
        FROM session_topics st
    """,
    "top_hackers": """
        SELECT h.name AS hacker_name, COUNT(*) AS attack_count
        FROM alerts a
        JOIN hackers h ON a.hacker_id = h.id
        GROUP BY h.name
        ORDER BY attack_count DESC
        LIMIT 10
    """,
    "most_attacked_clients": """
        SELECT m.sender_name, COUNT(DISTINCT a.session_id) AS sessions_attacked
        FROM alerts a
        JOIN messages m ON a.message_id = m.message_id
        GROUP BY m.sender_name
        ORDER BY sessions_attacked DESC
        LIMIT 20
    """,
    "attack_timeline": """
        SELECT
            DATE_TRUNC('minute', detected_at) AS ts,
            COUNT(*) AS attacks
        FROM alerts
        GROUP BY 1
        ORDER BY 1
    """,
    "detection_rate": """
        SELECT
            COUNT(DISTINCT m.session_id)                         AS total_sessions,
            COUNT(DISTINCT a.session_id)                         AS attacked_sessions,
            ROUND(
                100.0 * COUNT(DISTINCT a.session_id)
                      / NULLIF(COUNT(DISTINCT m.session_id), 0), 1
            )                                                    AS detection_rate_pct
        FROM messages m
        LEFT JOIN alerts a ON m.session_id = a.session_id
    """,
}


def create_all_datasets(client, db_id) -> dict:
    print("Creating datasets...")
    ds = {}
    for table in ["messages", "alerts", "hackers",
                  "session_topics", "hacker_decryption_attempts"]:
        ds[table] = create_physical_dataset(client, db_id, table)
    for name, sql in VIRTUAL_DATASETS.items():
        ds[name] = create_virtual_dataset(client, db_id, name, sql.strip())
    return ds


# ---------------------------------------------------------------------------
# Step 3 — Charts
# ---------------------------------------------------------------------------

def create_chart(client, name, viz_type, ds_id, params: dict) -> int:
    print(f"  Creating chart: {name}")
    payload = {
        "slice_name":     name,
        "viz_type":       viz_type,
        "datasource_id":  ds_id,
        "datasource_type": "table",
        "params":         json.dumps(params),
    }
    r = client.post("/api/v1/chart/", payload)
    return r.json().get("id", 0)


def create_all_charts(client, ds) -> list[int]:
    charts = []

    # --- Communication graph (three-color: protected / attacked / broken) ---
    cid = create_chart(
        client,
        "Communication Graph — Channel Status",
        "graph_chart",
        ds["communication_graph"],
        {
            "source": "source",
            "target": "target",
            "metric": {"aggregate": "SUM", "column": {"column_name": "value"},
                       "expressionType": "SIMPLE", "label": "Messages"},
            "category": "channel_status",
            "color_scheme": "custom",
            "label_colors": {
                "protected": "#00CC66",
                "attacked":  "#FF3300",
                "broken":    "#999999",
            },
            "show_legend": True,
            "edge_length": 200,
        },
    )
    charts.append(cid)

    # --- Top 10 Hackers ---
    cid = create_chart(
        client,
        "Top 10 Hackers by Attack Count",
        "bar",
        ds["top_hackers"],
        {
            "metrics":  [{"aggregate": "SUM",
                          "column": {"column_name": "attack_count"},
                          "expressionType": "SIMPLE", "label": "Attacks"}],
            "groupby":  ["hacker_name"],
            "color_scheme": "bnbColors",
            "show_legend": False,
            "x_axis_label": "Hacker",
            "y_axis_label": "Attack Count",
        },
    )
    charts.append(cid)

    # --- Most Attacked Clients ---
    cid = create_chart(
        client,
        "Most Attacked Clients",
        "bar",
        ds["most_attacked_clients"],
        {
            "metrics":  [{"aggregate": "SUM",
                          "column": {"column_name": "sessions_attacked"},
                          "expressionType": "SIMPLE", "label": "Sessions"}],
            "groupby":  ["sender_name"],
            "color_scheme": "googleCategory10c",
            "show_legend": False,
            "x_axis_label": "Client",
            "y_axis_label": "Sessions Attacked",
        },
    )
    charts.append(cid)

    # --- Attack Timeline ---
    cid = create_chart(
        client,
        "Attack Timeline",
        "line",
        ds["attack_timeline"],
        {
            "metrics":   [{"aggregate": "SUM",
                           "column": {"column_name": "attacks"},
                           "expressionType": "SIMPLE", "label": "Attacks"}],
            "groupby":   [],
            "x_axis":    "ts",
            "color_scheme": "bnbColors",
            "show_legend": False,
        },
    )
    charts.append(cid)

    # --- Big Numbers ---
    for label, metric_sql, tbl in [
        ("Total Messages", "COUNT(*)", ds["messages"]),
        ("Total Attacks",  "COUNT(*)", ds["alerts"]),
    ]:
        cid = create_chart(
            client, label, "big_number_total", tbl,
            {
                "metric": {"expressionType": "SQL", "sqlExpression": metric_sql,
                           "label": label},
            },
        )
        charts.append(cid)

    cid = create_chart(
        client,
        "Detection Rate (%)",
        "big_number_total",
        ds["detection_rate"],
        {
            "metric": {"expressionType": "SQL",
                       "sqlExpression": "MAX(detection_rate_pct)",
                       "label": "Detection Rate %"},
        },
    )
    charts.append(cid)

    # --- Session Topics table ---
    cid = create_chart(
        client,
        "Session Topics",
        "table",
        ds["session_topics"],
        {
            "all_columns": ["sender_name", "receiver_name", "topic",
                            "message_count", "channel_status", "created_at"],
            "order_by_cols": ["created_at desc"],
            "page_length": 25,
        },
    )
    charts.append(cid)

    # --- Hacker Decryption Attempts ---
    cid = create_chart(
        client,
        "Hacker Decryption Attempts",
        "table",
        ds["hacker_decryption_attempts"],
        {
            "all_columns": ["hacker_id", "session_id", "sequence_num",
                            "hacker_qber", "attempted_key",
                            "decrypted_garbage", "noise_level", "success",
                            "created_at"],
            "order_by_cols": ["created_at desc"],
            "page_length": 25,
        },
    )
    charts.append(cid)

    # --- Alerts table ---
    cid = create_chart(
        client,
        "All Alerts",
        "table",
        ds["alerts"],
        {
            "all_columns": ["message_id", "session_id", "sender_id",
                            "sequence_num", "hacker_id", "expected_state",
                            "actual_state", "deviation_pct", "detected_at"],
            "order_by_cols": ["detected_at desc"],
            "page_length": 50,
        },
    )
    charts.append(cid)

    # --- All Hackers ---
    cid = create_chart(
        client,
        "All Hackers",
        "table",
        ds["hackers"],
        {
            "all_columns": ["id", "name", "signature_seed"],
            "page_length": 50,
        },
    )
    charts.append(cid)

    # --- Messages table ---
    cid = create_chart(
        client,
        "All Messages",
        "table",
        ds["messages"],
        {
            "all_columns": ["message_id", "session_id", "sender_name",
                            "receiver_name", "sequence_num", "content",
                            "quantum_state", "is_tampered", "created_at"],
            "order_by_cols": ["created_at desc"],
            "page_length": 50,
        },
    )
    charts.append(cid)

    return [c for c in charts if c]


# ---------------------------------------------------------------------------
# Step 4 — Dashboard
# ---------------------------------------------------------------------------

def build_position_json(chart_ids: list[int]) -> dict:
    """
    Build a Superset dashboard layout with charts in a 2-column grid.
    Row 1: Communication Graph (full width)
    Row 2: Top Hackers | Most Attacked
    Row 3: Timeline | Big Numbers (3 cells)
    Row 4: Session Topics | Hacker Decryption Attempts
    Row 5: Alerts | All Hackers | All Messages
    """
    rows_spec = [
        [chart_ids[0]],                           # graph full width
        chart_ids[1:3],                           # bar charts
        chart_ids[3:7],                           # timeline + big numbers
        chart_ids[7:9],                           # tables row 1
        chart_ids[9:],                            # tables row 2
    ]

    position = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID":  {"type": "ROOT",  "id": "ROOT_ID",  "children": ["GRID_ID"]},
        "GRID_ID":  {"type": "GRID",  "id": "GRID_ID",  "children": []},
    }

    row_ids = []
    chart_counter = 0
    for row_idx, row_charts in enumerate(rows_spec):
        if not row_charts:
            continue
        row_id = f"ROW-{row_idx}"
        row_ids.append(row_id)
        col_width = max(2, 12 // len(row_charts))
        row_children = []

        for chart_id in row_charts:
            if not chart_id:
                continue
            chart_counter += 1
            slot_id = f"CHART-{chart_counter}"
            row_children.append(slot_id)
            position[slot_id] = {
                "type": "CHART",
                "id":   slot_id,
                "children": [],
                "meta": {
                    "chartId": chart_id,
                    "width":   col_width,
                    "height":  50 if chart_id == row_charts[0] and row_idx == 0 else 35,
                },
            }

        position[row_id] = {
            "type":     "ROW",
            "id":       row_id,
            "children": row_children,
            "meta":     {"background": "BACKGROUND_TRANSPARENT"},
        }

    position["GRID_ID"]["children"] = row_ids
    return position


def create_dashboard(client: SupersetClient, chart_ids: list[int]) -> int:
    print("Creating dashboard...")
    position_json = build_position_json(chart_ids)
    r = client.post("/api/v1/dashboard/", {
        "dashboard_title": "Quantum MITM Dashboard",
        "slug":            "quantum-mitm",
        "published":       True,
        "position_json":   json.dumps(position_json),
        "charts":          chart_ids,
    })
    dash_id = r.json().get("id", 0)
    if dash_id:
        # Attach charts explicitly (some versions require this separately)
        client.put(f"/api/v1/dashboard/{dash_id}", {"charts": chart_ids})
    return dash_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== Superset Dashboard Initialisation ===")

    # Give the server a moment to be fully ready
    time.sleep(3)

    client = SupersetClient()

    db_id  = create_database(client)
    if not db_id:
        print("[ERROR] Could not create/find database connection. Aborting.")
        sys.exit(1)

    ds      = create_all_datasets(client, db_id)
    charts  = create_all_charts(client, ds)
    dash_id = create_dashboard(client, charts)

    print(f"\n=== Done! ===")
    print(f"Dashboard ID  : {dash_id}")
    print(f"Charts created: {len(charts)}")
    print(f"Open at       : http://localhost:8088/superset/dashboard/quantum-mitm/")
    print()
    print("Dashboard layout:")
    print("  Row 1 : Communication Graph (green=protected | red=attacked | grey=broken)")
    print("  Row 2 : Top 10 Hackers  |  Most Attacked Clients")
    print("  Row 3 : Attack Timeline  |  Total Messages  |  Total Attacks  |  Detection Rate")
    print("  Row 4 : Session Topics   |  Hacker Decryption Attempts")
    print("  Row 5 : All Alerts  |  All Hackers  |  All Messages")


if __name__ == "__main__":
    main()
