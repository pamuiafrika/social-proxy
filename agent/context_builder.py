import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("context_builder")


class ContextBuilder:
    def __init__(
        self,
        conversations_dir: str,
        insights_dir: str,
        history_window: int = 20,
        sms_reader=None,
    ):
        self.conversations_dir = conversations_dir
        self.insights_dir = insights_dir
        self.history_window = history_window
        self.sms_reader = sms_reader  # SMSReader; None in offline/dev environments

    def build(self, thread, contact) -> Dict[str, Any]:
        insights = self._load_insights(contact.phone)

        # Build the new messages list from the current thread
        new_messages = [
            {
                "body":       m.body,
                "timestamp":  m.received_at.isoformat(),
                "message_id": m.message_id,
            }
            for m in thread.messages
        ]

        # Primary: fetch live conversation thread from device SMS DB
        # (reads both sent and received, merges chronologically)
        conversation_thread = self._build_conversation_thread(contact.phone, new_messages)

        return {
            "contact": {
                "phone":               contact.phone,
                "name":                contact.name,
                "relationship":        contact.relationship,
                "how_we_met":          contact.how_we_met,
                "shared_interests":    contact.shared_interests,
                "communication_style": contact.communication_style,
                "language":            contact.language,
                "trust_level":         contact.trust_level,
                "notes":               contact.notes,
            },
            "new_messages":         new_messages,
            "conversation_thread":  conversation_thread,
            "insights":             insights,
            "thread_span_seconds":  thread.received_span.total_seconds(),
        }

    def _build_conversation_thread(self, phone: str, new_messages: List[dict]) -> List[dict]:
        """
        Returns a chronological conversation chain. Prefers live SMS data from
        the device; falls back to the stored JSON history when offline.

        New (unread) messages are tagged with is_new=True so the LLM can clearly
        see which messages need a reply vs which are prior context.
        """
        new_ids = {m["message_id"] for m in new_messages}

        # Try live device thread first
        if self.sms_reader is not None:
            live = self.sms_reader.read_thread(phone, limit_each=self.history_window)
            if live:
                # Tag new messages so the LLM knows what just arrived
                for entry in live:
                    entry["is_new"] = entry["message_id"] in new_ids
                logger.info(
                    f"[context] Live thread for {phone}: "
                    f"{sum(1 for e in live if e['direction']=='inbound')} received, "
                    f"{sum(1 for e in live if e['direction']=='outbound')} sent"
                )
                return live

        # Fallback: stored JSON history written by the agent after each reply
        history = self._load_history(phone)
        thread = history[-self.history_window:]
        for entry in thread:
            entry["is_new"] = entry.get("message_id", "") in new_ids
        if not self.sms_reader:
            logger.debug(f"[context] No SMS reader — using stored history for {phone} ({len(thread)} entries)")
        else:
            logger.warning(f"[context] Live thread empty for {phone} — falling back to stored history")
        return thread

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
        """Keep the fallback JSON history up to date (used when device SMS is unavailable)."""
        path = os.path.join(self.conversations_dir, f"{phone}.json")
        history = self._load_history(phone)
        for m in inbound_messages:
            history.append({
                "direction":  "inbound",
                "body":       m.body,
                "timestamp":  m.received_at.isoformat(),
                "message_id": m.message_id,
            })
        history.append({
            "direction":    "outbound",
            "body":         reply,
            "timestamp":    self._now(),
            "generated_by": model_used,
            "round_count":  round_count,
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
