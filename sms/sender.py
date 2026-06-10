import subprocess
import logging
from typing import Optional

logger = logging.getLogger("sms_sender")

MAX_WARN_LENGTH = 320


class SMSSender:
    def __init__(self, sim_strategy: str = "same", max_reply_length: int = MAX_WARN_LENGTH):
        self.sim_strategy = sim_strategy
        self.max_reply_length = max_reply_length

    def select_sim(self, contact_sim_preference: str, subscription_id: int) -> Optional[int]:
        strategy = contact_sim_preference if contact_sim_preference != "default" else self.sim_strategy
        if strategy == "sim1":
            return 1
        if strategy == "sim2":
            return 2
        if strategy == "same":
            if subscription_id == 0:
                return 1
            if subscription_id == 1:
                return 2
            return None
        return None  # "default" — let Android choose

    def send(self, message: str, phone: str, sim_slot: Optional[int] = None) -> bool:
        if len(message) > self.max_reply_length:
            logger.warning(f"Reply to {phone} is {len(message)} chars (>{self.max_reply_length})")
        cmd = ["termux-sms-send", "-n", phone]
        if sim_slot is not None:
            cmd += ["-s", str(sim_slot)]
        cmd.append(message)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.error(f"termux-sms-send failed for {phone}: {result.stderr.strip()}")
                return False
            preview = message[:50].replace("\n", " ")
            sim_label = f"SIM{sim_slot}" if sim_slot else "default SIM"
            logger.info(f"Sent to {phone} via {sim_label}. Length: {len(message)} chars. Preview: '{preview}'")
            return True
        except subprocess.TimeoutExpired:
            logger.error(f"termux-sms-send timed out for {phone}")
            return False
        except FileNotFoundError:
            logger.error("termux-sms-send not found — is Termux:API installed?")
            return False
        except Exception as e:
            logger.error(f"SMS send error for {phone}: {e}")
            return False
