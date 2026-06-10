import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import List

from sms.reader import InboundMessage

logger = logging.getLogger("thread_batcher")


@dataclass
class Thread:
    lead_job_id: int
    phone: str
    messages: List[InboundMessage]
    received_span: timedelta
    contact: object  # ContactProfile — typed loosely to avoid circular imports


class ThreadBatcher:
    def __init__(self, window_seconds: int = 1800):
        self.window_seconds = window_seconds

    def build(self, lead_job, lead_message: InboundMessage, contact, queue_manager) -> "Thread":
        from datetime import timezone
        window = timedelta(seconds=self.window_seconds)
        pending_jobs = queue_manager.list_pending()
        messages = [lead_message]
        batched_ids = []

        for job in pending_jobs:
            if job.id == lead_job.id:
                continue
            if job.phone != lead_message.phone:
                continue
            try:
                from datetime import datetime
                job_time = datetime.fromisoformat(job.received_at)
                lead_time = lead_message.received_at
                if job_time.tzinfo is None:
                    job_time = job_time.replace(tzinfo=timezone.utc)
                if lead_time.tzinfo is None:
                    lead_time = lead_time.replace(tzinfo=timezone.utc)
                delta = abs(job_time - lead_time)
                if delta <= window:
                    from sms.reader import InboundMessage as IM
                    extra = IM(
                        message_id=job.message_id,
                        phone=job.phone,
                        body=job.body,
                        received_at=job_time,
                        subscription_id=-1,
                        raw={},
                    )
                    messages.append(extra)
                    batched_ids.append(job.id)
            except Exception:
                continue

        for jid in batched_ids:
            queue_manager.mark_skipped(jid, f"batched_into:{lead_job.id}")
            logger.info(f"Job #{jid} batched into lead #{lead_job.id}")

        messages.sort(key=lambda m: m.received_at)
        span = timedelta(0)
        if len(messages) > 1:
            span = messages[-1].received_at - messages[0].received_at

        return Thread(
            lead_job_id=lead_job.id,
            phone=lead_message.phone,
            messages=messages,
            received_span=span,
            contact=contact,
        )
