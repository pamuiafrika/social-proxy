import subprocess
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

logger = logging.getLogger("sms_reader")


@dataclass
class InboundMessage:
    message_id: str
    phone: str
    body: str
    received_at: datetime
    subscription_id: int
    raw: dict


def normalise_phone(phone: str, default_country_code: str = "+255") -> str:
    phone = re.sub(r"[\s\-\(\)]", "", phone)
    if phone.startswith("+"):
        return phone
    if phone.startswith("00"):
        return "+" + phone[2:]
    cc = default_country_code.lstrip("+")
    if phone.startswith("0"):
        return "+" + cc + phone[1:]
    if phone.startswith(cc):
        return "+" + phone
    return "+" + cc + phone


class SMSReader:
    def __init__(self, inbox_limit: int = 50, default_country_code: str = "+255"):
        self.inbox_limit = inbox_limit
        self.default_country_code = default_country_code

    def read(self) -> List[InboundMessage]:
        # -t inbox  : message type filter (type column = 1)
        # -l <n>    : limit
        # --message-selection="read = 0" : unread only (no -u flag exists)
        try:
            result = subprocess.run(
                [
                    "termux-sms-list",
                    "-t", "inbox",
                    "-l", str(self.inbox_limit),
                    "--message-selection=read = 0",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                logger.warning(f"termux-sms-list returned code {result.returncode}: {result.stderr.strip()}")
                return []
            raw = result.stdout.strip()
            if not raw:
                return []
            messages = json.loads(raw)
            return [self._parse(m) for m in messages if self._valid(m)]
        except subprocess.TimeoutExpired:
            logger.warning("termux-sms-list timed out")
            return []
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse termux-sms-list output: {e}")
            return []
        except FileNotFoundError:
            logger.error("termux-sms-list not found — is Termux:API installed?")
            return []
        except Exception as e:
            logger.warning(f"SMS read error: {e}")
            return []

    def _valid(self, m: dict) -> bool:
        return bool(m.get("_id")) and bool(m.get("address")) and m.get("body") is not None

    def _parse(self, m: dict) -> InboundMessage:
        ts_ms = m.get("date", 0)
        received_at = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        phone = normalise_phone(str(m.get("address", "")), self.default_country_code)
        sub_id = m.get("subscription_id", -1)
        if sub_id is None:
            sub_id = -1
        return InboundMessage(
            message_id=str(m["_id"]),
            phone=phone,
            body=m.get("body", ""),
            received_at=received_at,
            subscription_id=int(sub_id),
            raw=m,
        )
