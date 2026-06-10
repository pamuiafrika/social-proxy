import subprocess
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

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

    def read_thread(self, phone: str, limit_each: int = 10) -> List[Dict]:
        """
        Fetch the full conversation thread for a contact by reading both
        inbox (received) and sent messages from the device SMS database,
        then merging and sorting them chronologically.

        Returns a list of dicts: {direction, body, timestamp, message_id}
        Falls back to an empty list if termux-sms-list is unavailable.
        """
        received = self._raw_fetch("inbox", phone, limit_each)
        sent     = self._raw_fetch("sent",  phone, limit_each)

        # Deduplicate by _id in case the same message appears in both queries
        seen_ids: set = set()
        thread: List[Dict] = []

        for m, default_dir in [(m, "inbound") for m in received] + [(m, "outbound") for m in sent]:
            mid = str(m.get("_id", ""))
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            # Use `type` field from the DB as authoritative direction source:
            # Android SMS type: 1=received(inbox), 2=sent, anything else treat as
            # inbound for inbox queries and outbound for sent queries.
            raw_type = m.get("type")
            if raw_type == 2:
                direction = "outbound"
            elif raw_type == 1:
                direction = "inbound"
            else:
                direction = default_dir
            thread.append({
                "direction":  direction,
                "body":       m.get("body", ""),
                "timestamp":  self._ts(m),
                "message_id": mid,
            })

        thread.sort(key=lambda e: e["timestamp"])
        return thread

    def _raw_fetch(self, msg_type: str, address: str, limit: int) -> List[dict]:
        """Run termux-sms-list for a given type and address, return raw dicts.

        Uses last-9-digit LIKE matching so +255, 0, and bare formats all hit.
        """
        # Strip non-digits and take the last 9 significant digits.
        # +255612494740 → 612494740 — matches however Android stored the number.
        digits = re.sub(r'\D', '', address)[-9:]
        try:
            result = subprocess.run(
                [
                    "termux-sms-list",
                    "-t", msg_type,
                    "-l", str(limit),
                    f"--message-selection=address LIKE '%{digits}%'",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return []
            data = json.loads(result.stdout.strip())
            return [m for m in data if m.get("_id") is not None and m.get("body") is not None]
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return []
        except Exception as e:
            logger.warning(f"_raw_fetch({msg_type}, {address}): {e}")
            return []

    @staticmethod
    def _ts(m: dict) -> str:
        # Sent messages may populate date_sent instead of (or in addition to) date
        ts_ms = m.get("date") or m.get("date_sent") or 0
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()

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
