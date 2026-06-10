import logging
import random
import time

logger = logging.getLogger("pacing")


class ReplyPacer:
    def __init__(
        self,
        min_seconds: int = 30,
        max_seconds: int = 300,
        high_trust_min: int = 15,
        high_trust_max: int = 90,
        low_trust_min: int = 60,
        low_trust_max: int = 600,
        dry_run: bool = False,
    ):
        self.min_seconds = min_seconds
        self.max_seconds = max_seconds
        self.high_trust_min = high_trust_min
        self.high_trust_max = high_trust_max
        self.low_trust_min = low_trust_min
        self.low_trust_max = low_trust_max
        self.dry_run = dry_run

    def wait(self, contact):
        if self.dry_run:
            return
        trust = getattr(contact, "trust_level", "medium")
        if trust == "high":
            delay = random.randint(self.high_trust_min, self.high_trust_max)
        elif trust == "low":
            delay = random.randint(self.low_trust_min, self.low_trust_max)
        else:
            delay = random.randint(self.min_seconds, self.max_seconds)
        logger.info(f"Pacing: waiting {delay}s before sending to {getattr(contact, 'name', contact)}")
        time.sleep(delay)
