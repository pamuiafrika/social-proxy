import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("insights")

SYSTEM_PROMPT = (
    "You are extracting relationship insights from an SMS conversation. "
    "Return ONLY a valid JSON object. Do not explain. Do not use markdown."
)


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


class InsightExtractor:
    def __init__(self, insights_dir: str, llm_selector):
        self.insights_dir = insights_dir
        self.selector = llm_selector

    def run(self, thread, reply: str, contact):
        try:
            self._run_inner(thread, reply, contact)
        except Exception as e:
            logger.warning(f"Insight extraction failed for {contact.phone}: {e}")

    def _run_inner(self, thread, reply: str, contact):
        existing = self._load(contact.phone)
        inbound_text = "\n".join(m.body for m in thread.messages)
        user_content = (
            f"Contact: {contact.name}, {contact.relationship}\n"
            f"Exchange:\n  Them: {inbound_text}\n  Reply sent: {reply}\n"
            f"Previous insights: {json.dumps(existing)}\n\n"
            "Update the insights object. Add or update:\n"
            "- recurring_topics (add new topics mentioned)\n"
            "- communication_patterns (update if new evidence)\n"
            "- open_threads (add if they mentioned a future plan or unresolved topic)\n"
            "- mood_history (append latest mood, keep last 10)\n"
            "- inside_references (add if a shared reference was used)\n"
            "Increment enrichment_version by 1.\n"
            "Return the complete updated InsightsEntry JSON."
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        llm = self.selector.select_for_insights()
        raw = llm.chat(messages, round_number=2)
        updated = _extract_json(raw)
        if not updated:
            logger.warning(f"Insight extraction: could not parse JSON for {contact.phone}")
            return
        updated["phone"] = contact.phone
        updated["last_updated"] = datetime.now(timezone.utc).isoformat()
        self._save(contact.phone, updated)
        version = updated.get("enrichment_version", "?")
        logger.info(f"Extracted insights for {contact.name}. Version {version}.")

    def _load(self, phone: str) -> dict:
        path = os.path.join(self.insights_dir, f"{phone}.json")
        if not os.path.exists(path):
            return {
                "phone": phone,
                "last_updated": None,
                "recurring_topics": [],
                "communication_patterns": {},
                "open_threads": [],
                "mood_history": [],
                "inside_references": [],
                "sensitive_flags": [],
                "enrichment_version": 0,
            }
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, phone: str, data: dict):
        os.makedirs(self.insights_dir, exist_ok=True)
        path = os.path.join(self.insights_dir, f"{phone}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
