import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("reasoner")

ROUND1_SYSTEM = (
    "You are an expert at understanding human communication. Analyse the following "
    "incoming SMS message(s) and provide structured analysis. Return ONLY a valid JSON object, "
    "no markdown, no prose."
)

ROUND2_SYSTEM_TEMPLATE = (
    "You are acting as {agent_name}. Reply to {contact_name}'s message exactly as {agent_name} would. "
    "Match their language ({language}), tone, and style. Do NOT sound like an AI. "
    "Do NOT use formal closings. Do NOT repeat what they said. "
    "Reply only with the message text, nothing else."
)

ROUND3_SYSTEM = (
    "You are reviewing a draft SMS reply before it is sent. Be critical. "
    "Return ONLY a valid JSON object, no markdown, no prose."
)

SAFE_ROUND1_DEFAULTS = {
    "intent": "unknown",
    "emotional_tone": "neutral",
    "energy_level": "medium",
    "requires_action": False,
    "open_thread_reference": None,
    "follow_up_opportunity": None,
    "sensitive_topic_detected": False,
    "reply_length_hint": "short",
    "notes": "",
}


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Try finding first { ... }
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


@dataclass
class ReasoningResult:
    status: str  # "approved", "hold", "skip"
    reply: Optional[str]
    round_count: int
    model_used: str
    hold_reason: Optional[str] = None
    skip_reason: Optional[str] = None
    round1_analysis: Optional[dict] = None
    round_outputs: List[dict] = field(default_factory=list)


class ReasoningEngine:
    def __init__(self, llm_selector, agent_name: str = "Agent", max_rounds: int = 3):
        self.selector = llm_selector
        self.agent_name = agent_name
        self.max_rounds = max_rounds

    def run(self, context: Dict[str, Any], contact) -> ReasoningResult:
        round_outputs = []

        # Round 1 — Context Analysis
        r1_result = self._round1(context, contact)
        round_outputs.append({"round": 1, "output": r1_result})

        if r1_result.get("sensitive_topic_detected"):
            return ReasoningResult(
                status="hold",
                reply=None,
                round_count=1,
                model_used="",
                hold_reason="self_silence_topic_detected",
                round1_analysis=r1_result,
                round_outputs=round_outputs,
            )

        # Round 2 — Draft
        r2_draft = self._round2(context, contact, r1_result)
        round_outputs.append({"round": 2, "output": r2_draft})

        if self.max_rounds < 3:
            model_used = self._model_name(self.selector.select(contact, 2))
            return ReasoningResult(
                status="approved",
                reply=r2_draft,
                round_count=2,
                model_used=model_used,
                round1_analysis=r1_result,
                round_outputs=round_outputs,
            )

        # Round 3 — Self-Review
        r3_result = self._round3(context, contact, r2_draft)
        round_outputs.append({"round": 3, "output": r3_result})
        verdict = r3_result.get("verdict", "approve")
        model_used = self._model_name(self.selector.select(contact, 3))

        if verdict == "hold":
            return ReasoningResult(
                status="hold",
                reply=None,
                round_count=3,
                model_used=model_used,
                hold_reason=r3_result.get("hold_reason", "round3_hold"),
                round1_analysis=r1_result,
                round_outputs=round_outputs,
            )

        final_reply = r3_result.get("revised_reply") if verdict == "revise" else r2_draft
        if not final_reply:
            final_reply = r2_draft

        return ReasoningResult(
            status="approved",
            reply=final_reply,
            round_count=3,
            model_used=model_used,
            round1_analysis=r1_result,
            round_outputs=round_outputs,
        )

    @staticmethod
    def _format_thread(thread: List[dict], contact_name: str, agent_name: str) -> str:
        """
        Format a conversation_thread list into a readable chat log for the LLM.

        Example output:
          [2025-06-10 09:00]  Amina : Hey are you coming today?
          [2025-06-10 09:15]  You   : Yeah I'll be there by 2
          [2025-06-10 09:16]  Amina : ok cool
          [2025-06-10 14:22]  Amina : [NEW] Actually can you bring the laptop?
        """
        lines = []
        for entry in thread:
            ts = entry.get("timestamp", "")[:16].replace("T", " ")
            direction = entry.get("direction", "inbound")
            is_new = entry.get("is_new", False)
            speaker = agent_name if direction == "outbound" else contact_name
            body = entry.get("body", "").replace("\n", " ")
            tag = "[NEW] " if is_new else ""
            lines.append(f"  [{ts}]  {speaker:<10}: {tag}{body}")
        return "\n".join(lines) if lines else "  (no prior messages)"

    def _round1(self, context: Dict, contact) -> dict:
        contact_info = context["contact"]
        incoming = context["new_messages"]
        thread = context.get("conversation_thread", [])
        insights = context.get("insights")

        chat_log = self._format_thread(thread, contact_info["name"], self.agent_name)

        logger.info(
            f"[context:{contact_info['name']}] Conversation thread sent to AI "
            f"({len(thread)} entries, "
            f"{sum(1 for e in thread if not e.get('is_new'))} prior, "
            f"{sum(1 for e in thread if e.get('is_new'))} new):\n"
            f"{chat_log}"
        )

        user_content = (
            f"Contact profile: {json.dumps(contact_info)}\n\n"
            f"Conversation thread (chronological — [NEW] = just received, needs reply):\n"
            f"{chat_log}\n\n"
            f"Current insights: {json.dumps(insights)}\n\n"
            "Return a JSON object with these exact keys:\n"
            "- intent: question|update|casual_chat|complaint|request|follow_up|greeting|unknown\n"
            "- emotional_tone: happy|sad|stressed|playful|urgent|neutral|affectionate\n"
            "- energy_level: high|medium|low\n"
            "- requires_action: bool\n"
            "- open_thread_reference: string or null\n"
            "- follow_up_opportunity: string or null\n"
            "- sensitive_topic_detected: bool\n"
            "- reply_length_hint: very_short|short|medium|long\n"
            "- notes: string"
        )
        messages = [
            {"role": "system", "content": ROUND1_SYSTEM},
            {"role": "user", "content": user_content},
        ]
        try:
            llm = self.selector.select(contact, 1)
            raw = llm.chat(messages, round_number=1)
            parsed = _extract_json(raw)
            if parsed:
                logger.info(
                    f"Round 1 complete. Intent: {parsed.get('intent')}. Tone: {parsed.get('emotional_tone')}."
                )
                return parsed
            logger.warning("Round 1 JSON parse failed — using safe defaults")
            return SAFE_ROUND1_DEFAULTS.copy()
        except Exception as e:
            logger.error(f"Round 1 LLM error: {e}")
            return SAFE_ROUND1_DEFAULTS.copy()

    def _round2(self, context: Dict, contact, r1: dict) -> str:
        contact_info = context["contact"]
        thread = context.get("conversation_thread", [])

        system = ROUND2_SYSTEM_TEMPLATE.format(
            agent_name=self.agent_name,
            contact_name=contact_info["name"],
            language=contact_info["language"],
        )
        chat_log = self._format_thread(thread, contact_info["name"], self.agent_name)
        relationship_ctx = (
            f"Relationship context:\n"
            f"  - How you know them: {contact_info['how_we_met']}\n"
            f"  - Your relationship: {contact_info['relationship']}\n"
            f"  - Shared interests: {', '.join(contact_info['shared_interests'])}\n"
            f"  - Communication style: {contact_info['communication_style']}\n"
            f"  - Notes: {contact_info['notes']}\n"
            f"  - Energy required: {r1.get('energy_level', 'medium')}\n"
            f"  - Expected reply length: {r1.get('reply_length_hint', 'short')}\n"
            f"  - Follow-up opportunity: {r1.get('follow_up_opportunity')}\n"
            f"  - Their mood: {r1.get('emotional_tone', 'neutral')}"
        )
        user_content = (
            f"{relationship_ctx}\n\n"
            f"Conversation thread (chronological — [NEW] messages are what you are replying to):\n"
            f"{chat_log}\n\n"
            f"Round 1 analysis: {json.dumps(r1)}\n\n"
            "Write the reply now."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        try:
            llm = self.selector.select(contact, 2)
            draft = llm.chat(messages, round_number=2).strip()
            logger.info(f"Round 2 complete. Draft length: {len(draft)} chars.")
            return draft
        except Exception as e:
            logger.error(f"Round 2 LLM error: {e}")
            raise

    def _round3(self, context: Dict, contact, draft: str) -> dict:
        contact_info = context["contact"]
        thread = context.get("conversation_thread", [])
        chat_log = self._format_thread(thread, contact_info["name"], self.agent_name)

        user_content = (
            f"Contact: {contact_info['name']} ({contact_info['relationship']}, trust: {contact_info.get('trust_level', 'medium')})\n\n"
            f"Conversation thread (chronological — [NEW] = messages being replied to):\n"
            f"{chat_log}\n\n"
            f"Proposed reply: {draft}\n\n"
            "Review criteria:\n"
            "1. Does the reply sound like a real person, not an AI?\n"
            "2. Is it appropriate for the trust level and relationship?\n"
            "3. Does it accidentally reveal that it was AI-generated?\n"
            "4. Does it contain any sensitive information (money, OTP, passwords, health)?\n"
            "5. Is the tone/language correct for this contact?\n"
            "6. Is it the right length?\n\n"
            "Return JSON:\n"
            "- verdict: 'approve' | 'revise' | 'hold'\n"
            "- issues: [list of strings]\n"
            "- revised_reply: string or null\n"
            "- hold_reason: string or null"
        )
        messages = [
            {"role": "system", "content": ROUND3_SYSTEM},
            {"role": "user", "content": user_content},
        ]
        try:
            llm = self.selector.select(contact, 3)
            raw = llm.chat(messages, round_number=3)
            parsed = _extract_json(raw)
            if parsed:
                verdict = parsed.get("verdict", "approve")
                logger.info(f"Round 3 verdict: {verdict}.")
                return parsed
            logger.warning("Round 3 JSON parse failed — defaulting to approve")
            return {"verdict": "approve", "issues": [], "revised_reply": None, "hold_reason": None}
        except Exception as e:
            logger.error(f"Round 3 LLM error: {e}")
            return {"verdict": "approve", "issues": [], "revised_reply": None, "hold_reason": None}

    def _model_name(self, llm) -> str:
        class_name = type(llm).__name__.lower()
        if "deepseek" in class_name:
            return "deepseek"
        if "zhipu" in class_name:
            return "zhipu"
        return "unknown"
