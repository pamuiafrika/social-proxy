#!/usr/bin/env python3
"""AI Social Proxy — entry point and CLI router."""

import argparse
import logging
import logging.handlers
import os
import sys

BASE_DIR = os.path.expanduser(os.environ.get("SOCIAL_PROXY_DIR", "~/social-proxy"))
sys.path.insert(0, BASE_DIR)


def _setup_logging(base_dir: str, level: str = "INFO"):
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "agent.log")
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s]  [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)


def _load_log_level(base_dir: str) -> str:
    try:
        import yaml
        config_path = os.path.join(base_dir, "config.yaml")
        if os.path.exists(config_path):
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("logging", {}).get("level", "INFO")
    except Exception:
        pass
    return "INFO"


def main():
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="AI Social Proxy — agentic SMS assistant",
    )
    parser.add_argument("--dir", default=BASE_DIR, help="Base project directory")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialise database and directory structure")

    run_p = sub.add_parser("run", help="Run one agent cycle")
    run_p.add_argument("--dry-run", action="store_true", help="Print replies without sending")

    daemon_p = sub.add_parser("daemon", help="Run continuously on polling interval")
    daemon_p.add_argument("--dry-run", action="store_true")

    sub.add_parser("status", help="Show system status and queue counts")

    queue_p = sub.add_parser("queue", help="Queue management")
    queue_sub = queue_p.add_subparsers(dest="queue_cmd", required=True)
    ql = queue_sub.add_parser("list", help="List queue jobs")
    ql.add_argument("--status", help="Filter by status")
    qc = queue_sub.add_parser("clear", help="Delete jobs by status")
    qc.add_argument("--status", required=True)
    qc.add_argument("--confirm", action="store_true")

    review_p = sub.add_parser("review", help="Manage held jobs")
    review_sub = review_p.add_subparsers(dest="review_cmd", required=True)
    review_sub.add_parser("list", help="List held jobs")
    ra = review_sub.add_parser("approve", help="Send draft reply for held job")
    ra.add_argument("job_id", type=int)
    rr = review_sub.add_parser("reject", help="Reject held job")
    rr.add_argument("job_id", type=int)
    re_p = review_sub.add_parser("edit", help="Send custom reply for held job")
    re_p.add_argument("job_id", type=int)
    re_p.add_argument("reply_text")

    contacts_p = sub.add_parser("contacts", help="Contact management")
    contacts_sub = contacts_p.add_subparsers(dest="contacts_cmd", required=True)
    contacts_sub.add_parser("list", help="List all contacts")
    contacts_sub.add_parser("add", help="Interactively add a new contact")
    ce = contacts_sub.add_parser("edit", help="Interactively edit a contact")
    ce.add_argument("phone", help="E.164 phone number of the contact to edit")
    cd = contacts_sub.add_parser("disable", help="Disable a contact")
    cd.add_argument("phone")

    ins_p = sub.add_parser("insights", help="View or clear contact insights")
    ins_p.add_argument("phone", nargs="?")
    ins_p.add_argument("--clear", action="store_true")

    hist_p = sub.add_parser("history", help="View conversation history")
    hist_p.add_argument("phone")
    hist_p.add_argument("--last", type=int, default=10)

    digest_p = sub.add_parser("digest", help="Generate weekly digest")
    digest_p.add_argument("--week", help="Week label e.g. 2025-W23")

    cfg_p = sub.add_parser("config", help="Config management")
    cfg_sub = cfg_p.add_subparsers(dest="config_cmd", required=True)
    cfg_sub.add_parser("show", help="Show resolved config")
    cset = cfg_sub.add_parser("set", help="Set a config value")
    cset.add_argument("key")
    cset.add_argument("value")

    state_p = sub.add_parser("state", help="State management")
    state_sub = state_p.add_subparsers(dest="state_cmd", required=True)
    sr = state_sub.add_parser("reset", help="Reset dedup hashes and daily stats")
    sr.add_argument("--confirm", action="store_true")

    logs_p = sub.add_parser("logs", help="Show recent log lines")
    logs_p.add_argument("--tail", type=int, default=50)

    args = parser.parse_args()
    base_dir = os.path.expanduser(args.dir)
    log_level = _load_log_level(base_dir)
    _setup_logging(base_dir, log_level)

    from cli import commands as cmd

    if args.command == "init":
        cmd.cmd_init(base_dir)

    elif args.command == "run":
        cmd.cmd_run(base_dir, dry_run=args.dry_run)

    elif args.command == "daemon":
        cmd.cmd_daemon(base_dir, dry_run=args.dry_run)

    elif args.command == "status":
        cmd.cmd_status(base_dir)

    elif args.command == "queue":
        if args.queue_cmd == "list":
            cmd.cmd_queue_list(base_dir, status=args.status)
        elif args.queue_cmd == "clear":
            cmd.cmd_queue_clear(base_dir, status=args.status, confirm=args.confirm)

    elif args.command == "review":
        if args.review_cmd == "list":
            cmd.cmd_review_list(base_dir)
        elif args.review_cmd == "approve":
            cmd.cmd_review_approve(base_dir, args.job_id)
        elif args.review_cmd == "reject":
            cmd.cmd_review_reject(base_dir, args.job_id)
        elif args.review_cmd == "edit":
            cmd.cmd_review_edit(base_dir, args.job_id, args.reply_text)

    elif args.command == "contacts":
        if args.contacts_cmd == "list":
            cmd.cmd_contacts_list(base_dir)
        elif args.contacts_cmd == "add":
            cmd.cmd_contacts_add(base_dir)
        elif args.contacts_cmd == "edit":
            cmd.cmd_contacts_edit(base_dir, args.phone)
        elif args.contacts_cmd == "disable":
            cmd.cmd_contacts_disable(base_dir, args.phone)

    elif args.command == "insights":
        if args.clear:
            cmd.cmd_insights_clear(base_dir, args.phone)
        else:
            cmd.cmd_insights(base_dir, args.phone)

    elif args.command == "history":
        cmd.cmd_history(base_dir, args.phone, last=args.last)

    elif args.command == "digest":
        cmd.cmd_digest(base_dir, week=args.week)

    elif args.command == "config":
        if args.config_cmd == "show":
            cmd.cmd_config_show(base_dir)
        elif args.config_cmd == "set":
            cmd.cmd_config_set(base_dir, args.key, args.value)

    elif args.command == "state":
        if args.state_cmd == "reset":
            cmd.cmd_state_reset(base_dir, confirm=args.confirm)

    elif args.command == "logs":
        cmd.cmd_logs(base_dir, tail=args.tail)


if __name__ == "__main__":
    main()
