import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI
from kafka import KafkaConsumer, KafkaProducer

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)
app = FastAPI(title="BookingLab payment simulator")
DATABASE = os.getenv("PAYMENT_DB_PATH", "/data/payments.db")
SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"

def db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.execute("CREATE TABLE IF NOT EXISTS requests (event_id TEXT PRIMARY KEY, result TEXT)")
    return conn

def handle(payload, producer):
    if payload.get("event_type") != "PaymentRequested" or payload.get("version") != 1 or payload.get("currency") != "RUB":
        log.warning("Invalid request: %s", payload)
        return
    request_id = str(uuid.UUID(payload["event_id"]))
    booking_id = str(uuid.UUID(payload["booking_id"]))
    scenario = payload.get("test_scenario", "success") if TEST_MODE else "success"
    if scenario not in ("success", "failure", "no_response"):
        scenario = "success"
    with db_connection() as conn:
        row = conn.execute("SELECT result FROM requests WHERE event_id=?", (request_id,)).fetchone()
        if row:
            result = json.loads(row[0]) if row[0] else None
        else:
            result = None if scenario == "no_response" else {
                "event_id": str(uuid.uuid4()), "event_type": "PaymentFailed" if scenario == "failure" else "PaymentSucceeded",
                "version": 1, "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "correlation_id": request_id, "booking_id": booking_id}
            conn.execute("INSERT INTO requests (event_id, result) VALUES (?, ?)", (request_id, json.dumps(result) if result else None))
            conn.commit()
        if result:
            for attempt in range(5):
                try:
                    producer.send("payment.results.v1", key=booking_id.encode(), value=json.dumps(result).encode()).get(timeout=5)
                    break
                except Exception:
                    if attempt == 4:
                        raise
                    log.warning("Result publish retry %s for %s", attempt + 1, request_id)
                    time.sleep(1)

def consume():
    while True:
        producer = None
        consumer = None
        try:
            producer = KafkaProducer(bootstrap_servers=SERVERS, max_block_ms=3000)
            consumer = KafkaConsumer("payment.requests.v1", bootstrap_servers=SERVERS, group_id="bookinglab-payment",
                                     enable_auto_commit=False, auto_offset_reset="earliest", consumer_timeout_ms=1000)
            while True:
                for message in consumer:
                    handle(json.loads(message.value), producer)
                    consumer.commit()
        except Exception:
            log.exception("Broker unavailable; retrying")
            time.sleep(3)
        finally:
            if consumer:
                consumer.close()
            if producer:
                producer.close()

@app.get("/health/live")
def live():
    return {"status": "ok"}

if __name__ == "__main__":
    threading.Thread(target=consume, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8080)
