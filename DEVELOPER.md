# DEVELOPER TODO — AI Social Proxy v1.0.0

## Status Legend
- [ ] Not started
- [x] Complete
- [~] In progress
- [!] Blocked / needs attention

---

## Phase 1 — Core Infrastructure

- [x] Project directory structure created
- [x] `requirements.txt` written
- [x] `config.yaml` written with all documented keys
- [x] `contacts.csv` example file created
- [x] `queue/schema.sql` — SQLite schema (jobs, dedup_hashes, state tables)
- [x] `queue/manager.py` — Queue CRUD, state transitions, stale recovery
- [x] `agent/state_manager.py` — Key-value state persistence

---

## Phase 2 — SMS Layer

- [x] `sms/reader.py` — termux-sms-list wrapper, phone normalisation, InboundMessage dataclass
- [x] `sms/sender.py` — termux-sms-send wrapper, SIM selection logic
- [x] `sms/thread_batcher.py` — Groups messages from same contact within rolling window

---

## Phase 3 — Contact & Context

- [x] `agent/contact_resolver.py` — CSV loader, hot-reload, DND window logic
- [x] `agent/context_builder.py` — Assembles full context payload for LLM

---

## Phase 4 — AI Layer

- [x] `ai/deepseek.py` — DeepSeek API client, retry logic, temperature per round
- [x] `ai/zhipu.py` — Zhipu GLM-4-Flash client, JWT auth, retry logic
- [x] `ai/selector.py` — Health check, LLM selection logic, fallback

---

## Phase 5 — Agent Core

- [x] `agent/safety.py` — All 7 safety checks, trust gate, flood detection, daily cap
- [x] `agent/pacing.py` — Human-realistic send delay, trust-level ranges
- [x] `agent/reasoner.py` — 3-round reasoning loop, ReasoningResult dataclass
- [x] `agent/orchestrator.py` — Full pipeline run_once(), stale recovery, dry-run

---

## Phase 6 — Post-Processing

- [x] `agent/insight_extractor.py` — Post-reply insight extraction via Zhipu
- [x] `agent/enrichment.py` — Conservative contact profile enrichment
- [x] `agent/digest.py` — Weekly markdown digest generation

---

## Phase 7 — CLI

- [x] `cli/formatter.py` — Terminal output helpers
- [x] `cli/commands.py` — All CLI subcommands (run, daemon, init, status, queue, review, contacts, insights, history, digest, config, state, logs)
- [x] `main.py` — Entry point, CLI router

---

## Known TODOs / Future Work

- [ ] Add `--json` output flag to all CLI list commands
- [ ] Add optional webhook notification when a job is held for review
- [ ] Support custom LLM base URLs (for Ollama/local LLM forwarding)
- [ ] Add `contacts import <vcard>` to bulk-import from VCF files
- [ ] Add test suite with mocked termux-sms-list responses
- [ ] Add `python main.py test-llm` to validate API keys before first run
- [ ] Add per-contact reply approval mode (require manual approve for specific contacts)
- [ ] Investigate Android 12+ background SMS access restrictions on target device
- [ ] Disable battery optimisation for Termux — must be done manually in Android settings
- [ ] Set `DEEPSEEK_API_KEY` and `ZHIPU_API_KEY` in `~/.bashrc` on device

---

## Installation Checklist (Termux Device)

- [ ] Install Termux from F-Droid (NOT Play Store)
- [ ] Install Termux:API from F-Droid
- [ ] Grant SMS read/send permissions to Termux:API in Android Settings
- [ ] Grant Phone State permission to Termux:API
- [ ] `pkg install python sqlite termux-api cronie`
- [ ] `pip install -r requirements.txt`
- [ ] Set API keys in `~/.bashrc`
- [ ] Edit `config.yaml` (name, timezone, active_hours)
- [ ] Create `contacts.csv`
- [ ] `python main.py init`
- [ ] `python main.py run --dry-run` (verify)
- [ ] Add cron job: `*/5 * * * * cd ~/social-proxy && python main.py run >> logs/cron.log 2>&1`
- [ ] Start crond: `crond` (add to `~/.bashrc`)

---

## Package Notes

- The queue module is named `jobqueue/` (not `queue/`) to avoid shadowing Python's stdlib `queue` module
- Import as `from jobqueue.manager import QueueManager` throughout the codebase

---

## Architecture Notes

- All LLM calls go through `ai/selector.py` — never call deepseek/zhipu clients directly from agent code
- Safety layer is the last gate before send — it runs after reasoning, not before
- Dedup is two-layer: message_id check (fast) + SHA-256 hash (catch SMS DB resets)
- Thread batcher marks all non-lead jobs as `skipped(batched_into:<id>)` before the lead is processed
- Insights extraction is best-effort: failure must never block the main pipeline
- State manager is the single source of truth for runtime counters (daily stats, LLM health)
- Phone numbers must always be normalised to E.164 before any lookup or storage

---

*Last updated: 2026-06-10*
