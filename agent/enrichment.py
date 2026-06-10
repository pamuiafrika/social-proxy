import json
import logging
import os
from typing import List

logger = logging.getLogger("enrichment")


class ContactEnrichment:
    def __init__(self, insights_dir: str, contact_resolver, enabled: bool = True):
        self.insights_dir = insights_dir
        self.resolver = contact_resolver
        self.enabled = enabled

    def run(self, contact):
        if not self.enabled:
            return
        try:
            self._run_inner(contact)
        except Exception as e:
            logger.warning(f"Enrichment failed for {contact.phone}: {e}")

    def _run_inner(self, contact):
        path = os.path.join(self.insights_dir, f"{contact.phone}.json")
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                insights = json.load(f)
        except Exception as e:
            logger.warning(f"Could not read insights for {contact.phone}: {e}")
            return

        new_topics: List[str] = insights.get("recurring_topics", [])
        if not new_topics:
            return

        current_interests = contact.shared_interests or []
        to_add = [t for t in new_topics if t.lower() not in [i.lower() for i in current_interests]]
        if not to_add:
            return

        self.resolver.update_shared_interests(contact.phone, to_add)
