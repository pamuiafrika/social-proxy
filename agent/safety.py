import logging
from typing import List, Optional, Tuple

logger = logging.getLogger("safety")


class SafetyLayer:
    def __init__(
        self,
        blocked_keywords: List[str],
        self_silence_topics: List[str],
        max_replies_per_contact_per_hour: int = 5,
        max_replies_per_day: int = 100,
        flood_window_minutes: int = 60,
        trust_gate_enabled: bool = True,
    ):
        self.blocked_keywords = [k.lower() for k in blocked_keywords]
        self.self_silence_topics = [t.lower() for t in self_silence_topics]
        self.max_per_contact_per_hour = max_replies_per_contact_per_hour
        self.max_per_day = max_replies_per_day
        self.flood_window = flood_window_minutes
        self.trust_gate_enabled = trust_gate_enabled

    def check_inbound(self, body: str, contact, round1_analysis: Optional[dict], queue_manager, state_manager) -> Tuple[str, Optional[str]]:
        body_lower = body.lower()
        for kw in self.blocked_keywords:
            if kw in body_lower:
                logger.warning(f"Blocked keyword '{kw}' found in inbound message from {contact.phone}")
                return "hold", f"blocked_keyword_in_message:{kw}"

        if round1_analysis:
            intent = round1_analysis.get("intent", "")
            sensitive = round1_analysis.get("sensitive_topic_detected", False)
            if sensitive:
                logger.warning(f"Sensitive topic detected in message from {contact.name}")
                return "hold", "self_silence_topic_detected"
            if self.trust_gate_enabled and contact.trust_level == "low" and intent != "question":
                logger.info(f"Low trust gate: {contact.name} sent non-question (intent={intent})")
                return "skip", "low_trust_non_question"

        today_sent = state_manager.get_stats_today_sent()
        if today_sent >= self.max_per_day:
            logger.warning(f"Daily cap reached ({today_sent}). Skipping all further jobs.")
            return "skip", "daily_cap_exceeded"

        recent_count = queue_manager.recent_reply_count(contact.phone, self.flood_window)
        if recent_count >= self.max_per_contact_per_hour:
            logger.warning(f"Flood threshold for {contact.name}: {recent_count} replies in {self.flood_window}min")
            return "skip", "flood_threshold_exceeded"

        return "ok", None

    def check_outbound(self, reply: str) -> Tuple[str, Optional[str]]:
        reply_lower = reply.lower()
        for kw in self.blocked_keywords:
            if kw in reply_lower:
                logger.warning(f"Blocked keyword '{kw}' found in outbound reply — holding")
                return "hold", f"blocked_keyword_in_reply:{kw}"
        return "ok", None
