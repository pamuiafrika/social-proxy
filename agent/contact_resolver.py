import csv
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import time
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger("contact_resolver")


@dataclass
class ContactProfile:
    phone: str
    name: str
    relationship: str
    how_we_met: str
    shared_interests: List[str]
    communication_style: str
    language: str
    trust_level: str
    dnd_after: Optional[time]
    dnd_before: Optional[time]
    sim_preference: str
    model_preference: str
    notes: str
    active: bool


def _parse_time(val: str) -> Optional[time]:
    val = val.strip()
    if not val:
        return None
    try:
        h, m = val.split(":")
        return time(int(h), int(m))
    except Exception:
        return None


def _in_dnd(dnd_after: Optional[time], dnd_before: Optional[time], now: time) -> bool:
    if dnd_after is None or dnd_before is None:
        return False
    if dnd_after > dnd_before:
        return now >= dnd_after or now < dnd_before
    return dnd_after <= now < dnd_before


class ContactResolver:
    def __init__(self, csv_path: str, default_country_code: str = "+255"):
        self.csv_path = csv_path
        self.default_country_code = default_country_code
        self._cache: Dict[str, ContactProfile] = {}
        self._mtime: float = 0.0
        self._load()

    def _load(self):
        if not os.path.exists(self.csv_path):
            logger.critical(f"contacts.csv not found at {self.csv_path}")
            return
        mtime = os.path.getmtime(self.csv_path)
        if mtime == self._mtime and self._cache:
            return
        self._mtime = mtime
        contacts: Dict[str, ContactProfile] = {}
        try:
            with open(self.csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    phone = self._normalise(row.get("phone", "").strip())
                    if not phone:
                        continue
                    interests_raw = row.get("shared_interests", "")
                    interests = [i.strip() for i in interests_raw.split(",") if i.strip()]
                    active = row.get("active", "true").strip().lower() not in ("false", "0", "no")
                    profile = ContactProfile(
                        phone=phone,
                        name=row.get("name", "").strip(),
                        relationship=row.get("relationship", "acquaintance").strip(),
                        how_we_met=row.get("how_we_met", "").strip(),
                        shared_interests=interests,
                        communication_style=row.get("communication_style", "").strip(),
                        language=row.get("language", "en").strip(),
                        trust_level=row.get("trust_level", "medium").strip(),
                        dnd_after=_parse_time(row.get("dnd_after", "")),
                        dnd_before=_parse_time(row.get("dnd_before", "")),
                        sim_preference=row.get("sim_preference", "default").strip(),
                        model_preference=row.get("model_preference", "auto").strip(),
                        notes=row.get("notes", "").strip(),
                        active=active,
                    )
                    contacts[phone] = profile
            self._cache = contacts
            logger.info(f"Loaded {len(contacts)} contacts from {self.csv_path}")
        except Exception as e:
            logger.error(f"Failed to load contacts.csv: {e}")

    def _normalise(self, phone: str) -> str:
        phone = re.sub(r"[\s\-\(\)]", "", phone)
        if phone.startswith("+"):
            return phone
        if phone.startswith("00"):
            return "+" + phone[2:]
        cc = self.default_country_code.lstrip("+")
        if phone.startswith("0"):
            return "+" + cc + phone[1:]
        if phone.startswith(cc):
            return "+" + phone
        return "+" + cc + phone

    def resolve(self, phone: str) -> Optional[ContactProfile]:
        self._load()
        normalised = self._normalise(phone)
        contact = self._cache.get(normalised)
        if not contact:
            return None
        if not contact.active:
            return None
        now = datetime.now().time()
        if _in_dnd(contact.dnd_after, contact.dnd_before, now):
            logger.info(f"{phone} is in DND window — skipping")
            return None
        return contact

    def get_all(self) -> List[ContactProfile]:
        self._load()
        return list(self._cache.values())

    def update_shared_interests(self, phone: str, new_topics: List[str]):
        contact = self._cache.get(self._normalise(phone))
        if not contact:
            return
        added = [t for t in new_topics if t not in contact.shared_interests]
        if not added:
            return
        contact.shared_interests.extend(added)
        self._write_back()
        logger.info(f"[ENRICHMENT] Added topics to {contact.name}: {added}")

    def _write_back(self):
        if not self._cache:
            return
        fieldnames = [
            "phone", "name", "relationship", "how_we_met", "shared_interests",
            "communication_style", "language", "trust_level", "dnd_after", "dnd_before",
            "sim_preference", "model_preference", "notes", "active",
        ]
        try:
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for c in self._cache.values():
                    writer.writerow({
                        "phone": c.phone,
                        "name": c.name,
                        "relationship": c.relationship,
                        "how_we_met": c.how_we_met,
                        "shared_interests": ",".join(c.shared_interests),
                        "communication_style": c.communication_style,
                        "language": c.language,
                        "trust_level": c.trust_level,
                        "dnd_after": c.dnd_after.strftime("%H:%M") if c.dnd_after else "",
                        "dnd_before": c.dnd_before.strftime("%H:%M") if c.dnd_before else "",
                        "sim_preference": c.sim_preference,
                        "model_preference": c.model_preference,
                        "notes": c.notes,
                        "active": str(c.active).lower(),
                    })
        except Exception as e:
            logger.error(f"Failed to write back contacts.csv: {e}")
