import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("context_builder")


class ContextBuilder:
    def __init__(self, conversations_dir: str, insights_dir: str, history_window: int = 20):
        self.conversations_dir = conversations_dir
        self.insights_dir = insights_dir
        self.history_window = history_window

    def build(self, thread, contact) -> Dict[str, Any]:
        history = self._load_history(contact.phone)
        insights = self._load_insights(contact.phone)
        return {
            "contact": {
                "phone": contact.phone,
                "name": contact.name,
                "relationship": contact.relationship,
                "how_we_met": contact.how_we_met,
                "shared_interests": contact.shared_interests,
                "communication_style": contact.communication_style,
                "language": contact.language,
                "trust_level": contact.trust_level,
                "notes": contact.notes,
            },
            "incoming_messages": [
                {
                    "body": m.body,
                    "timestamp": m.received_at.isoformat(),
                    "message_id": m.message_id,
                }
                for m in thread.messages
            ],
            "recent_history": history[-self.history_window:],
            "insights": insights,
            "thread_span_seconds": thread.received_span.total_seconds(),
        }

    def _load_history(self, phone: str) -> List[dict]:
        path = os.path.join(self.conversations_dir, f"{phone}.json")
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"Failed to load history for {phone}: {e}")
            return []

    def _load_insights(self, phone: str) -> Optional[dict]:
        path = os.path.join(self.insights_dir, f"{phone}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load insights for {phone}: {e}")
            return None

    def append_to_history(self, phone: str, inbound_messages: List, reply: str, model_used: str, round_count: int):
        path = os.path.join(self.conversations_dir, f"{phone}.json")
        history = self._load_history(phone)
        for m in inbound_messages:
            history.append({
                "direction": "inbound",
                "body": m.body,
                "timestamp": m.received_at.isoformat(),
                "message_id": m.message_id,
            })
        history.append({
            "direction": "outbound",
            "body": reply,
            "timestamp": self._now(),
            "generated_by": model_used,
            "round_count": round_count,
        })
        max_entries = self.history_window * 4
        if len(history) > max_entries:
            history = history[-max_entries:]
        os.makedirs(self.conversations_dir, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to save history for {phone}: {e}")

    def _now(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
