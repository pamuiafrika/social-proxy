import json
import os
import sys
from datetime import datetime, timezone

from cli import formatter as fmt


def _load_config(base_dir: str) -> dict:
    import yaml
    config_path = os.path.join(base_dir, "config.yaml")
    if not os.path.exists(config_path):
        print(f"config.yaml not found at {config_path}")
        sys.exit(1)
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # Overlay env vars
    ds_key = os.environ.get("DEEPSEEK_API_KEY", "")
    zh_key = os.environ.get("ZHIPU_API_KEY", "")
    cfg.setdefault("ai", {})
    if ds_key:
        cfg["ai"]["deepseek_api_key"] = ds_key
    if zh_key:
        cfg["ai"]["zhipu_api_key"] = zh_key
    cfg["_base_dir"] = base_dir
    return cfg


def cmd_init(base_dir: str):
    dirs = [
        "store/conversations", "store/insights", "store/digests", "logs",
        "agent", "sms", "ai", "queue", "cli",
    ]
    for d in dirs:
        os.makedirs(os.path.join(base_dir, d), exist_ok=True)

    db_path = os.path.join(base_dir, "store", "state.db")
    from jobqueue.manager import QueueManager
    QueueManager(db_path)
    fmt.success(f"Database initialised at {db_path}")

    contacts_path = os.path.join(base_dir, "contacts.csv")
    if not os.path.exists(contacts_path):
        with open(contacts_path, "w") as f:
            f.write("phone,name,relationship,how_we_met,shared_interests,communication_style,language,trust_level,dnd_after,dnd_before,sim_preference,model_preference,notes,active\n")
        fmt.success(f"Created empty contacts.csv at {contacts_path}")

    fmt.success("Initialisation complete.")


def cmd_run(base_dir: str, dry_run: bool = False):
    cfg = _load_config(base_dir)
    from agent.orchestrator import Orchestrator
    orch = Orchestrator(cfg)
    orch.run_once(dry_run=dry_run)


def cmd_daemon(base_dir: str, dry_run: bool = False):
    cfg = _load_config(base_dir)
    from agent.orchestrator import Orchestrator
    orch = Orchestrator(cfg)
    orch.run_daemon(dry_run=dry_run)


def cmd_status(base_dir: str):
    cfg = _load_config(base_dir)
    db_path = os.path.join(base_dir, "store", "state.db")
    from jobqueue.manager import QueueManager
    from agent.state_manager import StateManager
    queue = QueueManager(db_path)
    state = StateManager(db_path)

    fmt.header("AI Social Proxy — Status")
    fmt.row("Last run:", state.get("last_run_at") or "never")
    fmt.row("DeepSeek healthy:", state.get("llm_primary_healthy") or "unknown")
    fmt.row("Zhipu healthy:", state.get("llm_secondary_healthy") or "unknown")
    fmt.row("Sent today:", state.get_stats_today_sent())
    fmt.row("Skipped today:", state.get_stats_today_skipped())
    print()
    counts = queue.status_counts()
    for status in ("pending", "processing", "done", "skipped", "held", "failed"):
        fmt.row(f"Queue [{status}]:", counts.get(status, 0))

    held = queue.list_held()
    if held:
        fmt.warn(f"{len(held)} job(s) held for review — run: python main.py review list")


def cmd_queue_list(base_dir: str, status: str = None):
    db_path = os.path.join(base_dir, "store", "state.db")
    from jobqueue.manager import QueueManager
    queue = QueueManager(db_path)

    if status:
        jobs = queue.list_by_status(status)
    else:
        jobs = []
        for s in ("pending", "processing", "held", "failed"):
            jobs.extend(queue.list_by_status(s))

    fmt.header(f"Queue ({len(jobs)} jobs)")
    if not jobs:
        print("  (empty)")
        return
    fmt.table(
        ["ID", "Phone", "Status", "Attempts", "Reason", "Body"],
        [[j.id, j.phone, j.status, j.attempt_count, fmt.truncate(j.fail_reason or "", 20), fmt.truncate(j.body, 40)] for j in jobs],
    )


def cmd_queue_clear(base_dir: str, status: str, confirm: bool = False):
    if not confirm:
        fmt.error("Use --confirm to confirm deletion.")
        return
    db_path = os.path.join(base_dir, "store", "state.db")
    from jobqueue.manager import QueueManager
    queue = QueueManager(db_path)
    count = queue.delete_by_status(status)
    fmt.success(f"Deleted {count} job(s) with status '{status}'.")


def cmd_review_list(base_dir: str):
    db_path = os.path.join(base_dir, "store", "state.db")
    from jobqueue.manager import QueueManager
    from agent.contact_resolver import ContactResolver
    cfg = _load_config(base_dir)
    queue = QueueManager(db_path)
    resolver = ContactResolver(
        os.path.join(base_dir, "contacts.csv"),
        cfg.get("sms", {}).get("default_country_code", "+255"),
    )
    held = queue.list_held()
    fmt.header(f"Held jobs ({len(held)})")
    if not held:
        print("  No held jobs.")
        return
    for j in held:
        contact = resolver.resolve(j.phone)
        name = contact.name if contact else j.phone
        print(f"\n  Job #{j.id} — {name} ({j.phone})")
        print(f"  Hold reason : {j.fail_reason}")
        print(f"  Their message: {fmt.truncate(j.body, 80)}")
        if j.reply_sent:
            print(f"  Draft reply  : {fmt.truncate(j.reply_sent, 80)}")


def cmd_review_approve(base_dir: str, job_id: int):
    cfg = _load_config(base_dir)
    db_path = os.path.join(base_dir, "store", "state.db")
    from jobqueue.manager import QueueManager
    from sms.sender import SMSSender
    from agent.contact_resolver import ContactResolver
    from agent.state_manager import StateManager

    queue = QueueManager(db_path)
    state = StateManager(db_path)
    job = queue.get_job(job_id)
    if not job or job.status != "held":
        fmt.error(f"Job #{job_id} not found or not held.")
        return
    if not job.reply_sent:
        fmt.error("No draft reply stored for this job. Use 'review edit' to provide one.")
        return

    resolver = ContactResolver(
        os.path.join(base_dir, "contacts.csv"),
        cfg.get("sms", {}).get("default_country_code", "+255"),
    )
    contact = resolver.resolve(job.phone)
    sim_cfg = cfg.get("sim", {})
    sender = SMSSender(sim_strategy=sim_cfg.get("strategy", "same"))
    sim_slot = sender.select_sim(contact.sim_preference if contact else "default", -1)
    ok = sender.send(job.reply_sent, job.phone, sim_slot)
    if ok:
        queue.mark_done(job_id, job.reply_sent, sim_slot)
        state.increment("stats_today_sent")
        fmt.success(f"Job #{job_id} approved and sent.")
    else:
        fmt.error(f"Send failed for job #{job_id}.")


def cmd_review_reject(base_dir: str, job_id: int):
    db_path = os.path.join(base_dir, "store", "state.db")
    from jobqueue.manager import QueueManager
    queue = QueueManager(db_path)
    job = queue.get_job(job_id)
    if not job or job.status != "held":
        fmt.error(f"Job #{job_id} not found or not held.")
        return
    queue.mark_skipped(job_id, "manually_rejected")
    fmt.success(f"Job #{job_id} rejected and marked skipped.")


def cmd_review_edit(base_dir: str, job_id: int, reply_text: str):
    cfg = _load_config(base_dir)
    db_path = os.path.join(base_dir, "store", "state.db")
    from jobqueue.manager import QueueManager
    from sms.sender import SMSSender
    from agent.contact_resolver import ContactResolver
    from agent.state_manager import StateManager

    queue = QueueManager(db_path)
    state = StateManager(db_path)
    job = queue.get_job(job_id)
    if not job or job.status != "held":
        fmt.error(f"Job #{job_id} not found or not held.")
        return
    resolver = ContactResolver(
        os.path.join(base_dir, "contacts.csv"),
        cfg.get("sms", {}).get("default_country_code", "+255"),
    )
    contact = resolver.resolve(job.phone)
    sender = SMSSender(sim_strategy=cfg.get("sim", {}).get("strategy", "same"))
    sim_slot = sender.select_sim(contact.sim_preference if contact else "default", -1)
    ok = sender.send(reply_text, job.phone, sim_slot)
    if ok:
        queue.mark_done(job_id, reply_text, sim_slot)
        state.increment("stats_today_sent")
        fmt.success(f"Job #{job_id} sent with custom reply.")
    else:
        fmt.error(f"Send failed for job #{job_id}.")


def _prompt(label: str, default: str = "", hint: str = "", required: bool = False) -> str:
    """Print a labelled prompt and return stripped input. Enter keeps `default`."""
    hint_str = f"  ({hint})" if hint else ""
    default_str = f"  [{default}]" if default else ""
    while True:
        try:
            val = input(f"  {label}{default_str}{hint_str}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise SystemExit(0)
        if val == "" and default:
            return default
        if val == "" and required:
            print(f"    ! Required — please enter a value.")
            continue
        return val


def _prompt_choice(label: str, choices: list, default: str = "") -> str:
    """Prompt that enforces one of the allowed choices."""
    choices_str = "/".join(choices)
    while True:
        val = _prompt(label, default=default, hint=choices_str)
        if val in choices:
            return val
        print(f"    ! Must be one of: {choices_str}")


def _write_contacts_csv(contacts_path: str, rows: list, fieldnames: list):
    import csv
    with open(contacts_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


CONTACT_FIELDS = [
    "phone", "name", "relationship", "how_we_met", "shared_interests",
    "communication_style", "language", "trust_level", "dnd_after", "dnd_before",
    "sim_preference", "model_preference", "notes", "active",
]


def _collect_contact_fields(current: dict = None) -> dict:
    """
    Interactively collect all contact fields. If `current` is provided, existing
    values are shown as defaults so the user can press Enter to keep them.
    """
    c = current or {}
    editing = bool(current)
    verb = "Edit" if editing else "Add"

    print()
    fmt.header(f"{verb} Contact")

    # Phone — required, validated
    while True:
        raw = _prompt("Phone (E.164: +255...)", default=c.get("phone", ""), required=True)
        import re
        if re.match(r"^\+\d{7,15}$", raw):
            phone = raw
            break
        print("    ! Must start with + followed by 7-15 digits (e.g. +255712345678)")

    name = _prompt("Name", default=c.get("name", ""), required=True)

    relationship = _prompt_choice(
        "Relationship",
        ["close_friend", "family", "work_colleague", "acquaintance", "romantic_partner", "other"],
        default=c.get("relationship", "acquaintance"),
    )

    how_we_met = _prompt(
        "How you met",
        default=c.get("how_we_met", ""),
        hint="e.g. university, job, childhood, neighborhood",
    )

    shared_interests = _prompt(
        "Shared interests (comma-separated)",
        default=c.get("shared_interests", ""),
        hint="e.g. music,coding,travel",
    )

    communication_style = _prompt(
        "Communication style",
        default=c.get("communication_style", ""),
        hint="e.g. casual_swahili_mix, formal_english, playful",
    )

    language = _prompt(
        "Language",
        default=c.get("language", "en"),
        hint="en / sw / sw+en / fr / ...",
        required=True,
    )

    trust_level = _prompt_choice(
        "Trust level",
        ["high", "medium", "low"],
        default=c.get("trust_level", "medium"),
    )

    dnd_after = _prompt(
        "DND after (no replies after this time)",
        default=c.get("dnd_after", ""),
        hint="HH:MM or leave blank to disable",
    )

    dnd_before = _prompt(
        "DND before (no replies before this time)",
        default=c.get("dnd_before", ""),
        hint="HH:MM or leave blank to disable",
    )

    sim_preference = _prompt_choice(
        "SIM preference",
        ["same", "sim1", "sim2", "default"],
        default=c.get("sim_preference", "default"),
    )

    model_preference = _prompt_choice(
        "Model preference",
        ["auto", "deepseek", "zhipu"],
        default=c.get("model_preference", "auto"),
    )

    notes = _prompt(
        "Notes for the AI",
        default=c.get("notes", ""),
        hint="e.g. Short replies. Formal on Mondays.",
    )

    active = _prompt_choice(
        "Active (should agent reply?)",
        ["true", "false"],
        default=c.get("active", "true"),
    )

    return {
        "phone": phone,
        "name": name,
        "relationship": relationship,
        "how_we_met": how_we_met,
        "shared_interests": shared_interests,
        "communication_style": communication_style,
        "language": language,
        "trust_level": trust_level,
        "dnd_after": dnd_after,
        "dnd_before": dnd_before,
        "sim_preference": sim_preference,
        "model_preference": model_preference,
        "notes": notes,
        "active": active,
    }


def cmd_contacts_add(base_dir: str):
    import csv
    contacts_path = os.path.join(base_dir, "contacts.csv")

    # Load existing to check for duplicate phone
    existing_phones = set()
    rows = []
    if os.path.exists(contacts_path):
        with open(contacts_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_phones.add(row.get("phone", "").strip())
                rows.append(dict(row))

    new_contact = _collect_contact_fields()

    if new_contact["phone"] in existing_phones:
        print()
        fmt.warn(f"{new_contact['phone']} already exists in contacts.csv.")
        confirm = _prompt("Overwrite?", hint="yes/no", default="no")
        if confirm.lower() not in ("yes", "y"):
            fmt.error("Aborted.")
            return
        rows = [r for r in rows if r.get("phone", "").strip() != new_contact["phone"]]

    rows.append(new_contact)
    _write_contacts_csv(contacts_path, rows, CONTACT_FIELDS)
    print()
    fmt.success(f"Contact {new_contact['name']} ({new_contact['phone']}) added.")


def cmd_contacts_edit(base_dir: str, phone: str):
    import csv
    contacts_path = os.path.join(base_dir, "contacts.csv")

    if not os.path.exists(contacts_path):
        fmt.error("contacts.csv not found.")
        return

    rows = []
    current = None
    with open(contacts_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
            if row.get("phone", "").strip() == phone:
                current = dict(row)

    if not current:
        fmt.error(f"No contact found with phone {phone}")
        print("  Tip: run `python main.py contacts list` to see all phones.")
        return

    print(f"\n  Editing {current.get('name', phone)} — press Enter to keep current value.")
    updated = _collect_contact_fields(current=current)

    rows = [updated if r.get("phone", "").strip() == phone else r for r in rows]
    _write_contacts_csv(contacts_path, rows, CONTACT_FIELDS)
    print()
    fmt.success(f"Contact {updated['name']} ({updated['phone']}) updated.")


def cmd_contacts_list(base_dir: str):
    cfg = _load_config(base_dir)
    from agent.contact_resolver import ContactResolver
    resolver = ContactResolver(
        os.path.join(base_dir, "contacts.csv"),
        cfg.get("sms", {}).get("default_country_code", "+255"),
    )
    contacts = resolver.get_all()
    fmt.header(f"Contacts ({len(contacts)})")
    fmt.table(
        ["Name", "Phone", "Relationship", "Trust", "Active"],
        [[c.name, c.phone, c.relationship, c.trust_level, str(c.active)] for c in contacts],
    )


def cmd_contacts_disable(base_dir: str, phone: str):
    contacts_path = os.path.join(base_dir, "contacts.csv")
    import csv
    rows = []
    found = False
    with open(contacts_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row.get("phone", "").strip() == phone:
                row["active"] = "false"
                found = True
            rows.append(row)
    if not found:
        fmt.error(f"Phone {phone} not found in contacts.csv")
        return
    with open(contacts_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    fmt.success(f"Contact {phone} disabled.")


def cmd_insights(base_dir: str, phone: str):
    path = os.path.join(base_dir, "store", "insights", f"{phone}.json")
    if not os.path.exists(path):
        fmt.error(f"No insights found for {phone}")
        return
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_insights_clear(base_dir: str, phone: str):
    path = os.path.join(base_dir, "store", "insights", f"{phone}.json")
    if os.path.exists(path):
        os.remove(path)
        fmt.success(f"Insights cleared for {phone}")
    else:
        fmt.warn(f"No insights file found for {phone}")


def cmd_history(base_dir: str, phone: str, last: int = 10):
    path = os.path.join(base_dir, "store", "conversations", f"{phone}.json")
    if not os.path.exists(path):
        fmt.error(f"No history found for {phone}")
        return
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    entries = data[-last:]
    fmt.header(f"History for {phone} (last {len(entries)})")
    for e in entries:
        direction = "→" if e.get("direction") == "outbound" else "←"
        ts = e.get("timestamp", "")[:16]
        body = fmt.truncate(e.get("body", ""), 70)
        print(f"  [{ts}] {direction} {body}")


def cmd_digest(base_dir: str, week: str = None):
    cfg = _load_config(base_dir)
    db_path = os.path.join(base_dir, "store", "state.db")
    from jobqueue.manager import QueueManager
    from agent.state_manager import StateManager
    from agent.contact_resolver import ContactResolver
    from agent.digest import DigestReporter

    queue = QueueManager(db_path)
    state = StateManager(db_path)
    resolver = ContactResolver(
        os.path.join(base_dir, "contacts.csv"),
        cfg.get("sms", {}).get("default_country_code", "+255"),
    )
    reporter = DigestReporter(
        digests_dir=os.path.join(base_dir, "store", "digests"),
        insights_dir=os.path.join(base_dir, "store", "insights"),
        queue_manager=queue,
        state_manager=state,
        contact_resolver=resolver,
    )
    report = reporter.generate(week_label=week)
    print(report)


def cmd_config_show(base_dir: str):
    cfg = _load_config(base_dir)
    safe = {k: v for k, v in cfg.items() if k != "_base_dir"}
    if "ai" in safe:
        safe["ai"] = {k: ("***" if "key" in k else v) for k, v in safe["ai"].items()}
    import yaml
    print(yaml.dump(safe, default_flow_style=False, allow_unicode=True))


def cmd_config_set(base_dir: str, key: str, value: str):
    import yaml
    config_path = os.path.join(base_dir, "config.yaml")
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    parts = key.split(".")
    node = cfg
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    # Coerce type
    if value.lower() == "true":
        value = True
    elif value.lower() == "false":
        value = False
    elif value.isdigit():
        value = int(value)
    node[parts[-1]] = value
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    fmt.success(f"Set {key} = {value}")


def cmd_state_reset(base_dir: str, confirm: bool = False):
    if not confirm:
        fmt.error("Use --confirm to confirm state reset.")
        return
    db_path = os.path.join(base_dir, "store", "state.db")
    from agent.state_manager import StateManager
    import sqlite3
    state = StateManager(db_path)
    state.reset_daily_stats()
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM dedup_hashes")
    conn.commit()
    conn.close()
    fmt.success("State reset: daily stats cleared, dedup hashes purged.")


def cmd_logs(base_dir: str, tail: int = 50):
    log_path = os.path.join(base_dir, "logs", "agent.log")
    if not os.path.exists(log_path):
        fmt.warn("No log file found.")
        return
    with open(log_path, encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines[-tail:]:
        print(line, end="")
