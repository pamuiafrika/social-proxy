import logging
import sys
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("orchestrator")


def _parse_active_hours(window: str):
    try:
        start_str, end_str = window.split("-")
        def _t(s):
            h, m = s.strip().split(":")
            return int(h) * 60 + int(m)
        return _t(start_str), _t(end_str)
    except Exception:
        return None, None


def _in_active_hours(window: str) -> bool:
    start, end = _parse_active_hours(window)
    if start is None:
        return True
    now = datetime.now()
    now_min = now.hour * 60 + now.minute
    if start <= end:
        return start <= now_min < end
    return now_min >= start or now_min < end


class Orchestrator:
    def __init__(self, config: dict):
        self.config = config
        self._build_components()

    def _build_components(self):
        import os
        from jobqueue.manager import QueueManager
        from agent.state_manager import StateManager
        from sms.reader import SMSReader
        from sms.sender import SMSSender
        from sms.thread_batcher import ThreadBatcher
        from agent.contact_resolver import ContactResolver
        from agent.context_builder import ContextBuilder
        from agent.safety import SafetyLayer
        from agent.pacing import ReplyPacer
        from agent.reasoner import ReasoningEngine
        from agent.insight_extractor import InsightExtractor
        from agent.enrichment import ContactEnrichment
        from ai.deepseek import DeepSeekClient
        from ai.zhipu import ZhipuClient
        from ai.selector import LLMSelector

        base = os.path.expanduser(self.config.get("_base_dir", "~/social-proxy"))
        db_path = os.path.join(base, "store", "state.db")
        conversations_dir = os.path.join(base, "store", "conversations")
        insights_dir = os.path.join(base, "store", "insights")
        digests_dir = os.path.join(base, "store", "digests")
        contacts_path = os.path.join(base, "contacts.csv")

        agent_cfg = self.config.get("agent", {})
        sms_cfg = self.config.get("sms", {})
        ai_cfg = self.config.get("ai", {})
        safety_cfg = self.config.get("safety", {})
        pacing_cfg = self.config.get("pacing", {})
        dedup_cfg = self.config.get("dedup", {})
        thread_cfg = self.config.get("thread_batcher", {})
        sim_cfg = self.config.get("sim", {})

        self.dry_run = agent_cfg.get("dry_run", False)
        self.active_hours = self.config.get("schedule", {}).get("active_hours", "00:00-23:59")
        self.interval_minutes = self.config.get("schedule", {}).get("interval_minutes", 5)

        self.queue = QueueManager(
            db_path=db_path,
            max_retry_attempts=agent_cfg.get("max_retry_attempts", 3),
            dedup_retention_days=dedup_cfg.get("retention_days", 90),
        )
        self.state = StateManager(db_path)
        self.sms_reader = SMSReader(
            inbox_limit=sms_cfg.get("inbox_limit", 50),
            default_country_code=sms_cfg.get("default_country_code", "+255"),
        )
        self.sms_sender = SMSSender(
            sim_strategy=sim_cfg.get("strategy", "same"),
            max_reply_length=sms_cfg.get("max_reply_length", 320),
        )
        self.thread_batcher = ThreadBatcher(
            window_seconds=thread_cfg.get("window_seconds", 1800)
        )
        self.contact_resolver = ContactResolver(
            csv_path=contacts_path,
            default_country_code=sms_cfg.get("default_country_code", "+255"),
        )
        self.context_builder = ContextBuilder(
            conversations_dir=conversations_dir,
            insights_dir=insights_dir,
            history_window=agent_cfg.get("history_window", 20),
        )
        self.safety = SafetyLayer(
            blocked_keywords=safety_cfg.get("blocked_keywords", []),
            self_silence_topics=safety_cfg.get("self_silence_topics", []),
            max_replies_per_contact_per_hour=safety_cfg.get("max_replies_per_contact_per_hour", 5),
            max_replies_per_day=safety_cfg.get("max_replies_per_day", 100),
            flood_window_minutes=safety_cfg.get("flood_window_minutes", 60),
            trust_gate_enabled=safety_cfg.get("trust_gate_enabled", True),
        )
        self.pacer = ReplyPacer(
            min_seconds=pacing_cfg.get("min_seconds", 30),
            max_seconds=pacing_cfg.get("max_seconds", 300),
            high_trust_min=pacing_cfg.get("high_trust_min", 15),
            high_trust_max=pacing_cfg.get("high_trust_max", 90),
            low_trust_min=pacing_cfg.get("low_trust_min", 60),
            low_trust_max=pacing_cfg.get("low_trust_max", 600),
            dry_run=self.dry_run,
        )

        ds_key = ai_cfg.get("deepseek_api_key", "")
        zh_key = ai_cfg.get("zhipu_api_key", "")
        deepseek = DeepSeekClient(
            api_key=ds_key,
            model=ai_cfg.get("deepseek_model", "deepseek-chat"),
            timeout=ai_cfg.get("request_timeout_seconds", 30),
            max_tokens=ai_cfg.get("max_tokens", 1000),
            round1_temperature=ai_cfg.get("round1_temperature", 0.2),
            round2_temperature=ai_cfg.get("round2_temperature", 0.75),
            round3_temperature=ai_cfg.get("round3_temperature", 0.2),
        )
        zhipu = ZhipuClient(
            api_key=zh_key,
            model=ai_cfg.get("zhipu_model", "glm-4-flash"),
            timeout=ai_cfg.get("request_timeout_seconds", 30),
            max_tokens=ai_cfg.get("max_tokens", 800),
            round1_temperature=ai_cfg.get("round1_temperature", 0.2),
            round2_temperature=ai_cfg.get("round2_temperature", 0.75),
            round3_temperature=ai_cfg.get("round3_temperature", 0.2),
        )
        self.llm_selector = LLMSelector(deepseek, zhipu, self.state)

        self.reasoner = ReasoningEngine(
            llm_selector=self.llm_selector,
            agent_name=agent_cfg.get("name", "Agent"),
            max_rounds=agent_cfg.get("max_rounds", 3),
        )
        self.insight_extractor = InsightExtractor(insights_dir, self.llm_selector)
        self.enrichment = ContactEnrichment(
            insights_dir=insights_dir,
            contact_resolver=self.contact_resolver,
            enabled=agent_cfg.get("enrichment_enabled", True),
        )

    def run_once(self, dry_run: Optional[bool] = None):
        if dry_run is not None:
            self.dry_run = dry_run
            self.pacer.dry_run = dry_run

        logger.info("Run started.")
        self.state.set("last_run_at", datetime.now(timezone.utc).isoformat())

        if not _in_active_hours(self.active_hours):
            logger.info(f"Outside active hours ({self.active_hours}). Exiting.")
            return

        self.queue.recover_stale_processing()
        self.queue.purge_old_dedup_hashes()
        self.llm_selector.check_health()

        messages = self.sms_reader.read()
        logger.info(f"Fetched {len(messages)} unread message(s).")

        for msg in messages:
            if self.queue.is_duplicate(msg.message_id, msg.phone, msg.body, msg.received_at.isoformat()):
                logger.info(f"Dedup: message_id {msg.message_id} already seen — skipping.")
                continue
            job_id = self.queue.enqueue(msg.message_id, msg.phone, msg.body, msg.received_at.isoformat())
            logger.info(f"Enqueued job #{job_id} for {msg.phone}.")

        sent = 0
        skipped = 0
        held = 0

        while True:
            job = self.queue.get_next_pending()
            if not job:
                break

            contact = self.contact_resolver.resolve(job.phone)
            if not contact:
                self.queue.mark_skipped(job.id, "unknown_or_dnd")
                logger.info(f"Job #{job.id}: {job.phone} not in allow-list or in DND — skipped.")
                skipped += 1
                continue

            from sms.reader import InboundMessage
            from datetime import datetime as dt
            lead_msg = InboundMessage(
                message_id=job.message_id,
                phone=job.phone,
                body=job.body,
                received_at=dt.fromisoformat(job.received_at),
                subscription_id=-1,
                raw={},
            )
            thread = self.thread_batcher.build(job, lead_msg, contact, self.queue)

            # Pre-reasoning inbound safety (no round1 yet)
            safety_status, safety_reason = self.safety.check_inbound(
                job.body, contact, None, self.queue, self.state
            )
            if safety_status == "hold":
                self.queue.mark_held(job.id, safety_reason)
                held += 1
                continue
            if safety_status == "skip":
                self.queue.mark_skipped(job.id, safety_reason)
                skipped += 1
                continue

            context = self.context_builder.build(thread, contact)

            from ai.selector import LLMUnavailableError
            try:
                result = self.reasoner.run(context, contact)
            except LLMUnavailableError:
                self.queue.mark_failed(job.id, "no_llm_available")
                logger.error(f"Job #{job.id}: LLM unavailable — marked failed.")
                continue
            except Exception as e:
                self.queue.mark_failed(job.id, f"reasoning_error:{e}")
                logger.error(f"Job #{job.id}: Reasoning error: {e}")
                continue

            if result.status == "hold":
                self.queue.mark_held(job.id, result.hold_reason or "agent_hold")
                held += 1
                continue
            if result.status == "skip":
                self.queue.mark_skipped(job.id, result.skip_reason or "agent_skip")
                skipped += 1
                continue

            # Post-reasoning outbound safety check
            out_status, out_reason = self.safety.check_outbound(result.reply)
            if out_status == "hold":
                self.queue.mark_held(job.id, out_reason)
                held += 1
                continue

            # Round1 analysis safety re-check (with proper round1 data)
            if result.round1_analysis:
                safety_status2, safety_reason2 = self.safety.check_inbound(
                    job.body, contact, result.round1_analysis, self.queue, self.state
                )
                if safety_status2 == "hold":
                    self.queue.mark_held(job.id, safety_reason2)
                    held += 1
                    continue
                if safety_status2 == "skip":
                    self.queue.mark_skipped(job.id, safety_reason2)
                    skipped += 1
                    continue

            if self.dry_run:
                logger.info(f"[DRY-RUN] Would send to {contact.name}: {result.reply}")
                print(f"\n[DRY-RUN] → {contact.name} ({job.phone}):\n{result.reply}\n")
                self.queue.mark_done(job.id, result.reply, None)
                sent += 1
                continue

            self.pacer.wait(contact)

            sim_slot = self.sms_sender.select_sim(contact.sim_preference, lead_msg.subscription_id)
            success = self.sms_sender.send(result.reply, job.phone, sim_slot)

            if success:
                self.queue.mark_done(job.id, result.reply, sim_slot)
                self.state.increment("stats_today_sent")
                self.context_builder.append_to_history(
                    job.phone, thread.messages, result.reply, result.model_used, result.round_count
                )
                self.insight_extractor.run(thread, result.reply, contact)
                self.enrichment.run(contact)
                sent += 1
            else:
                self.queue.mark_failed(job.id, "send_error")

        logger.info(f"Run complete. Sent: {sent}. Skipped: {skipped}. Held: {held}.")
        self.state.increment("stats_today_skipped")

    def run_daemon(self, dry_run: Optional[bool] = None):
        logger.info(f"Daemon started. Polling every {self.interval_minutes} minute(s).")
        while True:
            try:
                self.run_once(dry_run=dry_run)
            except KeyboardInterrupt:
                logger.info("Daemon stopped by user.")
                break
            except Exception as e:
                logger.error(f"Unhandled error in run_once: {e}")
            time.sleep(self.interval_minutes * 60)
