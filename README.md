# AI Social Proxy

An agentic SMS assistant that runs entirely on Android using [Termux](https://termux.dev) + [Termux:API](https://wiki.termux.com/wiki/Termux:API). It reads your unread SMS messages, reasons about each conversation using your personal contact profiles, and sends human-paced replies that match your own communication style — all from your phone, with no cloud, no server, no root.

---

## How it works

```
Cron (every 5 min)
  └─► Read unread SMS (termux-sms-list)
        └─► Filter against contacts allow-list
              └─► Dedup + thread grouping
                    └─► 3-round reasoning loop
                          Round 1: analyse intent, tone, mood
                          Round 2: draft a reply in your voice
                          Round 3: self-review (approve / revise / hold)
                    └─► Safety gates (keywords, trust level, flood limit)
                    └─► Human-realistic send delay
                    └─► Send via termux-sms-send
                    └─► Extract insights, update contact profile
```

Two LLM backends:
- **DeepSeek** (`deepseek-chat`) — primary, used for reasoning and high-trust contacts
- **Zhipu GLM-4-Flash** (`glm-4-flash`) — secondary, used for routine drafts and insight extraction

If one is down the other takes over automatically. If both are down, jobs are held and retried next cycle.

---

## Features

- **Allow-list only** — only replies to contacts explicitly listed in `contacts.csv`. Unknown numbers are silently ignored.
- **Relationship-aware replies** — each contact has a profile: language, tone, formality, shared interests, notes.
- **Multi-round reasoning** — up to 3 LLM calls per message: context analysis → draft → self-review.
- **Thread batching** — groups multiple messages from the same person into one reply window.
- **Safety gates** — blocked keywords, self-silence topics (politics, health advice, etc.), trust levels, flood detection, daily cap.
- **Reply pacing** — random human-realistic delay before sending (configurable per trust level).
- **Dual-SIM support** — reply from the same SIM that received the message, or override per contact.
- **Contact insights** — after each reply, the agent extracts topics, patterns, open threads, and mood history.
- **Contact enrichment** — newly discovered interests are added back to `contacts.csv` automatically.
- **Human review queue** — sensitive messages are held, not dropped. Review and approve/reject via CLI.
- **Weekly digest** — markdown summary of activity, top topics, open threads, LLM usage.
- **Full CLI** — manage contacts, queue, insights, history, config, and logs from the terminal.
- **No cloud, no root** — everything is local to your device.

---

## Requirements

- Android device with [Termux](https://f-droid.org/packages/com.termux/) from **F-Droid** (not Play Store)
- [Termux:API](https://f-droid.org/packages/com.termux.api/) from **F-Droid**
- A [DeepSeek API key](https://platform.deepseek.com/) and/or [Zhipu AI API key](https://open.bigmodel.cn/)

> **Important:** The Google Play Store version of Termux has SMS access removed by Google policy. You must install from F-Droid.

---

## Installation

### 1. Install Termux and Termux:API from F-Droid

Install both apps. Then in Android Settings → Apps → **Termux:API** → Permissions, enable:
- SMS (Read + Send)
- Phone (Read Phone State)

Also disable battery optimisation for Termux in Android Settings to prevent cron jobs from being killed.

### 2. Set up Termux

```bash
pkg update && pkg upgrade
pkg install python sqlite termux-api cronie git
```

### 3. Clone this repo

```bash
cd ~
git clone https://github.com/pamuiafrika/social-proxy.git
cd social-proxy
pip install -r requirements.txt
```

### 4. Set your API keys

```bash
echo 'export DEEPSEEK_API_KEY="your-deepseek-key-here"' >> ~/.bashrc
echo 'export ZHIPU_API_KEY="your-zhipu-key-here"' >> ~/.bashrc
source ~/.bashrc
```

You only need one key to start. Both are optional if you have the other.

### 5. Configure

```bash
nano config.yaml
```

At minimum, set:
- `agent.name` — your name (used in reply prompts so the LLM writes as you)
- `schedule.timezone` — your timezone (e.g. `Africa/Dar_es_Salaam`)
- `schedule.active_hours` — hours when the agent should run (e.g. `07:00-23:00`)

### 6. Add your contacts

```bash
nano contacts.csv
```

See [contacts.csv schema](#contactscsv-schema) below. Each row is one person you allow the agent to reply to.

### 7. Initialise and test

```bash
cd ~/social-proxy
python main.py init
python main.py run --dry-run   # Reads inbox, prints what it would send — nothing is actually sent
```

### 8. Set up the cron job

```bash
crond   # Start the cron daemon (add this line to ~/.bashrc to auto-start)
crontab -e
```

Add:
```
*/5 * * * * cd ~/social-proxy && python main.py run >> logs/cron.log 2>&1
```

---

## Pulling updates on Android

```bash
cd ~/social-proxy
git pull
pip install -r requirements.txt   # Only needed if requirements changed
```

Your `config.yaml`, `contacts.csv`, and `store/` data are not tracked by git and will never be overwritten by a pull.

---

## contacts.csv schema

```csv
phone,name,relationship,how_we_met,shared_interests,communication_style,language,trust_level,dnd_after,dnd_before,sim_preference,model_preference,notes,active
```

| Field | Description | Example |
|---|---|---|
| `phone` | E.164 format | `+255712345678` |
| `name` | Display name | `Amina` |
| `relationship` | Relationship type | `close_friend`, `family`, `work_colleague`, `acquaintance` |
| `how_we_met` | Context for the LLM | `university`, `job`, `childhood` |
| `shared_interests` | Comma-separated (quote if multiple) | `"music,coding,travel"` |
| `communication_style` | Style hint | `casual_swahili_mix`, `formal_english`, `playful` |
| `language` | Language code(s) | `sw`, `en`, `sw+en` |
| `trust_level` | Controls reply logic | `high`, `medium`, `low` |
| `dnd_after` | Do Not Disturb start | `22:00` |
| `dnd_before` | Do Not Disturb end | `07:00` |
| `sim_preference` | SIM override | `sim1`, `sim2`, `same`, `default` |
| `model_preference` | LLM override | `deepseek`, `zhipu`, `auto` |
| `notes` | Free-form hints for the LLM | `Short replies. Formal on Mondays.` |
| `active` | Enable/disable | `true`, `false` |

**Trust levels:**
- `high` — agent replies freely, short pacing delay
- `medium` — agent replies to all intents, self-review is mandatory
- `low` — agent only replies to direct questions, longer delay

**DND windows** can span midnight: `dnd_after: 22:00`, `dnd_before: 07:00` means no replies between 10pm and 7am.

---

## CLI reference

```bash
python main.py run [--dry-run]           # Run one agent cycle
python main.py daemon [--dry-run]        # Run continuously (daemon mode)
python main.py init                      # Initialise DB and directories

python main.py status                    # System status + queue counts
python main.py logs [--tail 50]          # View recent log lines

python main.py queue list [--status X]  # List queue jobs
python main.py queue clear --status X --confirm

python main.py review list               # Show held jobs
python main.py review approve <id>       # Send the draft reply
python main.py review reject <id>        # Permanently skip
python main.py review edit <id> "text"   # Send a custom reply

python main.py contacts list
python main.py contacts disable <phone>

python main.py insights <phone>          # View contact insights
python main.py insights <phone> --clear  # Reset insights

python main.py history <phone> [--last 10]

python main.py digest [--week 2025-W23]

python main.py config show
python main.py config set <key> <value>  # e.g. sim.strategy sim2

python main.py state reset --confirm     # Clear dedup + daily stats
```

---

## Safety system

The agent will **hold** (not delete) a job when:
- The incoming message contains a blocked keyword (money transfers, OTPs, passwords)
- The LLM detects a self-silence topic (politics, health/legal/financial advice, religion)
- The outbound draft contains a blocked keyword (LLM hallucination guard)
- The Round 3 self-review returns a `hold` verdict

The agent will **skip** (not reply) when:
- The sender is not in `contacts.csv` or `active: false`
- The contact is in their DND window
- The message is a duplicate (already replied)
- Flood threshold exceeded (> 5 replies to same contact in 60 min)
- Daily cap hit (100 replies/day)
- Low-trust contact sent something other than a direct question

Held jobs are reviewed via `python main.py review list`.

---

## Security

- API keys are never stored in `config.yaml`. Use environment variables only.
- `contacts.csv` is sensitive — run `chmod 600 contacts.csv` on device.
- Incoming message text is sent to the LLM APIs (DeepSeek, Zhipu) as part of the prompt. This is the only data that leaves the device.
- No telemetry, no analytics, no cloud sync.

---

## Project structure

```
social-proxy/
├── main.py                  # Entry point + CLI
├── config.yaml              # All configuration
├── contacts.csv             # Your allow-list
├── requirements.txt
├── agent/                   # Core agent logic
│   ├── orchestrator.py      # Pipeline controller
│   ├── reasoner.py          # 3-round LLM loop
│   ├── safety.py            # Safety gates
│   ├── pacing.py            # Send delay
│   ├── contact_resolver.py  # contacts.csv loader + DND
│   ├── context_builder.py   # LLM context assembly
│   ├── insight_extractor.py # Post-reply insight extraction
│   ├── enrichment.py        # contacts.csv auto-update
│   ├── state_manager.py     # SQLite key-value state
│   └── digest.py            # Weekly report
├── sms/
│   ├── reader.py            # termux-sms-list wrapper
│   ├── sender.py            # termux-sms-send + SIM logic
│   └── thread_batcher.py    # Group messages per contact
├── ai/
│   ├── deepseek.py          # DeepSeek API client
│   ├── zhipu.py             # Zhipu GLM client (JWT auth)
│   └── selector.py          # Health check + fallback logic
├── jobqueue/
│   ├── manager.py           # Queue CRUD + state machine
│   └── schema.sql           # SQLite schema
├── cli/
│   ├── commands.py          # All CLI command handlers
│   └── formatter.py         # Terminal output helpers
├── store/                   # Runtime data (gitignored)
│   ├── state.db
│   ├── conversations/       # Per-contact message history
│   ├── insights/            # Per-contact AI insights
│   └── digests/             # Weekly reports
└── logs/                    # Rotating log files (gitignored)
```

---

## Known limitations

1. **F-Droid only** — Play Store Termux has SMS access removed.
2. **Battery optimisation** — Android may kill background Termux processes. Disable it for Termux in Settings.
3. **Polling only** — Messages are processed at most every 5 minutes (configurable). Not real-time.
4. **Device must be online** — LLM API calls need internet. Offline jobs are retried next cycle.
5. **SIM subscription_id** — On some Android versions, `subscription_id` returns -1. The `same` SIM strategy falls back to Android default in that case.
6. **LLM API costs** — Each message uses 2–3 API calls. Use Zhipu (cheaper) for low-trust contacts and the daily cap to control spend.

---

## License

MIT
