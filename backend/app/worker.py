import json
import logging
import uuid
from threading import Event

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.domain import apply_payment_result, clock, expire_due
from app.models import OutboxEvent

logger = logging.getLogger(__name__)

def stub_result(payload: dict) -> dict | None:
    scenario = payload.get("test_scenario", "success") if settings.test_mode else "success"
    if scenario == "no_response":
        return None
    return {"event_id": str(uuid.uuid4()), "event_type": "PaymentFailed" if scenario == "failure" else "PaymentSucceeded",
            "version": 1, "occurred_at": clock.now().isoformat().replace("+00:00", "Z"),
            "correlation_id": payload["event_id"], "booking_id": payload["booking_id"]}

def process_outbox(producer=None):
    with SessionLocal() as db:
        events = db.scalars(select(OutboxEvent).where(OutboxEvent.published_at.is_(None)).order_by(OutboxEvent.created_at).limit(30)).all()
        for event in events:
            payload = json.loads(event.payload)
            if settings.payment_mode == "stub":
                result = stub_result(payload)
                if result:
                    apply_payment_result(db, result, clock.now())
            elif settings.payment_mode == "kafka":
                if producer is None:
                    return
                producer.send("payment.requests.v1", key=payload["booking_id"].encode(), value=event.payload.encode()).get(timeout=3)
            else:
                return
            event.published_at = clock.now()
            db.commit()

def payment_loop(stop: Event):
    producer = None
    consumer = None
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                expire_due(db, clock.now())
                db.commit()
            if settings.payment_mode == "kafka":
                from kafka import KafkaConsumer, KafkaProducer
                if producer is None:
                    producer = KafkaProducer(bootstrap_servers=settings.kafka_servers, request_timeout_ms=3000, max_block_ms=3000)
                if consumer is None:
                    consumer = KafkaConsumer("payment.results.v1", bootstrap_servers=settings.kafka_servers,
                                             group_id="bookinglab-backend", enable_auto_commit=False,
                                             auto_offset_reset="earliest", consumer_timeout_ms=200,
                                             api_version_auto_timeout_ms=3000)
                process_outbox(producer)
                for message in consumer:
                    try:
                        result = json.loads(message.value)
                        with SessionLocal() as db:
                            apply_payment_result(db, result, clock.now())
                        consumer.commit()
                    except Exception:
                        logger.exception("Failed processing payment result")
                        break
            elif settings.payment_mode == "stub":
                process_outbox()
        except Exception:
            logger.exception("Payment worker retrying")
            if producer:
                producer.close()
            if consumer:
                consumer.close()
            producer = consumer = None
        stop.wait(1)
    if producer:
        producer.close()
    if consumer:
        consumer.close()
