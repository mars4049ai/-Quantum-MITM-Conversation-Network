#!/bin/bash
# Verification script — queries Postgres via docker exec

echo "=== Total Messages ==="
docker exec postgres psql -U hackathon -d streaming -c "SELECT COUNT(*) AS total_messages FROM messages;"

echo ""
echo "=== Total Alerts ==="
docker exec postgres psql -U hackathon -d streaming -c "SELECT COUNT(*) AS total_alerts FROM alerts;"

echo ""
echo "=== Alerts by Hacker (Top 10) ==="
docker exec postgres psql -U hackathon -d streaming -c \
  "SELECT a.hacker_id, h.name AS hacker_name, COUNT(*) AS intercepts
   FROM alerts a JOIN hackers h ON a.hacker_id = h.id
   GROUP BY a.hacker_id, h.name
   ORDER BY intercepts DESC
   LIMIT 10;"

echo ""
echo "=== Hack Start Points (first tampered message per session) ==="
docker exec postgres psql -U hackathon -d streaming -c \
  "SELECT DISTINCT ON (a.session_id)
       a.session_id,
       h.name AS hacker_name,
       a.sequence_num AS hack_started_at_seq,
       a.message_id AS first_tampered_msg_id,
       ROUND(a.deviation_pct::numeric, 4) AS deviation
   FROM alerts a
   JOIN hackers h ON a.hacker_id = h.id
   ORDER BY a.session_id, a.sequence_num
   LIMIT 20;"

echo ""
echo "=== Tampered Sessions Detail (Top 10) ==="
docker exec postgres psql -U hackathon -d streaming -c \
  "WITH hack_start AS (
       SELECT session_id,
              MIN(sequence_num) AS first_tampered_seq,
              MAX(sequence_num) AS last_tampered_seq,
              COUNT(*) AS tampered_msg_count
       FROM alerts
       GROUP BY session_id
   )
   SELECT hs.session_id,
          a.hacker_id,
          h.name AS hacker_name,
          hs.first_tampered_seq,
          hs.last_tampered_seq,
          hs.tampered_msg_count,
          m.total_msgs AS session_total_msgs
   FROM hack_start hs
   JOIN alerts a ON a.session_id = hs.session_id AND a.sequence_num = hs.first_tampered_seq
   JOIN hackers h ON a.hacker_id = h.id
   JOIN (SELECT session_id, COUNT(*) AS total_msgs FROM messages GROUP BY session_id) m
       ON m.session_id = hs.session_id
   ORDER BY hs.tampered_msg_count DESC
   LIMIT 10;"

echo ""
echo "=== Deviation Distribution ==="
docker exec postgres psql -U hackathon -d streaming -c \
  "SELECT ROUND(deviation_pct::numeric, 2) AS deviation, COUNT(*)
   FROM alerts
   GROUP BY 1
   ORDER BY 1;"

echo ""
echo "=== Recent Messages (Last 5) ==="
docker exec postgres psql -U hackathon -d streaming -c \
  "SELECT message_id, session_id, sender_name, sequence_num, quantum_state, is_tampered
   FROM messages ORDER BY id DESC LIMIT 5;"
