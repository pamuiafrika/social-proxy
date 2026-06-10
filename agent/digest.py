import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("digest")


class DigestReporter:
    def __init__(
        self,
        digests_dir: str,
        insights_dir: str,
        queue_manager,
        state_manager,
        contact_resolver,
    ):
        self.digests_dir = digests_dir
        self.insights_dir = insights_dir
        self.queue = queue_manager
        self.state = state_manager
        self.resolver = contact_resolver

    def generate(self, week_label: Optional[str] = None) -> str:
        if not week_label:
            now = datetime.now(timezone.utc)
            week_label = f"{now.year}-W{now.isocalendar()[1]:02d}"

        jobs = self._all_jobs()
        done = [j for j in jobs if j.status == "done"]
        skipped = [j for j in jobs if j.status == "skipped"]
        held = [j for j in jobs if j.status == "held"]
        failed = [j for j in jobs if j.status == "failed"]

        per_contact: dict = {}
        for j in jobs:
            if j.phone not in per_contact:
                per_contact[j.phone] = {"received": 0, "sent": 0, "held": 0}
            per_contact[j.phone]["received"] += 1
            if j.status == "done":
                per_contact[j.phone]["sent"] += 1
            if j.status == "held":
                per_contact[j.phone]["held"] += 1

        open_threads_count = 0
        for phone in per_contact:
            path = os.path.join(self.insights_dir, f"{phone}.json")
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        ins = json.load(f)
                    open_threads_count += len(ins.get("open_threads", []))
                except Exception:
                    pass

        contacts = {c.phone: c for c in self.resolver.get_all()}
        ds_primary = self.state.get("llm_primary_healthy") or "unknown"
        ds_secondary = self.state.get("llm_secondary_healthy") or "unknown"

        lines = [
            f"# AI Social Proxy — Weekly Digest",
            f"**Week:** {week_label}  ",
            f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "## Summary",
            f"| Metric | Count |",
            f"|---|---|",
            f"| Messages received | {len(jobs)} |",
            f"| Replies sent | {len(done)} |",
            f"| Skipped | {len(skipped)} |",
            f"| Held for review | {len(held)} |",
            f"| Failed | {len(failed)} |",
            f"| Open threads | {open_threads_count} |",
            "",
            "## Per-Contact Breakdown",
            "| Contact | Received | Sent | Held |",
            "|---|---|---|---|",
        ]
        for phone, stats in per_contact.items():
            name = contacts.get(phone, None)
            label = name.name if name else phone
            lines.append(f"| {label} | {stats['received']} | {stats['sent']} | {stats['held']} |")

        lines += [
            "",
            "## System Status",
            f"- DeepSeek healthy: {ds_primary}",
            f"- Zhipu healthy: {ds_secondary}",
            "",
        ]

        report = "\n".join(lines)
        os.makedirs(self.digests_dir, exist_ok=True)
        path = os.path.join(self.digests_dir, f"{week_label}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info(f"Digest written to {path}")
        return report

    def _all_jobs(self):
        all_jobs = []
        for status in ("done", "skipped", "held", "failed", "pending", "processing"):
            all_jobs.extend(self.queue.list_by_status(status))
        return all_jobs
