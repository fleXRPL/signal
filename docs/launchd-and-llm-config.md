# Signal — launchd Scheduling & LLM Provider Configuration

## Overview

Signal runs automatically via macOS `launchd`. The schedule, LLM provider, and all runtime
settings are controlled by two files:

| File                                              | Purpose                               |
| ------------------------------------------------- | ------------------------------------- |
| `scripts/com.flexrpl.signal.plist`                | Source of truth — commit changes here |
| `~/Library/LaunchAgents/com.flexrpl.signal.plist` | Active copy read by launchd           |

**Any time you edit the plist in the repo you must copy it and reload launchd.**

---

## Applying plist Changes

```bash
launchctl unload ~/Library/LaunchAgents/com.flexrpl.signal.plist
cp /Users/garotconklin/garotm/fleXRPL/signal/scripts/com.flexrpl.signal.plist \
   ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.flexrpl.signal.plist
```

Verify the active copy:

```bash
cat ~/Library/LaunchAgents/com.flexrpl.signal.plist | grep -A4 StartCalendarInterval
launchctl list | grep flexrpl
```

---

## Changing the Schedule

Edit the `StartCalendarInterval` block in `scripts/com.flexrpl.signal.plist`:

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key>
    <integer>5</integer>   <!-- 0–23, local time -->
    <key>Minute</key>
    <integer>0</integer>   <!-- 0–59 -->
</dict>
```

**Current schedule: 4:00 AM local time daily.**

4am was chosen to finish the pipeline before the 9:00 AM social AM post while still
catching overnight wire content and early-morning news cycle updates.

Common alternatives:

| Time                  | Hour  | Minute |
| --------------------- | ----- | ------ |
| 12:01 AM              | 0     | 1      |
| **4:00 AM (current)** | **4** | **0**  |
| 5:00 AM               | 5     | 0      |
| 6:00 AM               | 6     | 0      |
| 7:00 AM               | 7     | 0      |
| **9:00 AM (social AM)** | **9** | **0**  |
| 8:00 AM               | 8     | 0      |

After editing, apply the change with the commands in the section above.

---

## Switching LLM Providers

The pipeline supports two LLM backends, switchable without touching Python code.

> **Important:** Claude is the default and recommended provider for all automated (launchd)
> runs. Ollama caused kernel panics on macOS when invoked from a background launchd daemon
> due to Metal GPU driver issues. See `docs/troubleshooting-macos-crash.md` for the full
> investigation. Ollama remains available for interactive manual runs.

### Option 1 — Environment Variable (recommended for one-off runs)

```bash
# Use Claude (default)
python3 main.py

# Force Ollama for a manual run
SIGNAL_LLM_PROVIDER=ollama python3 main.py
```

### Option 2 — Persistent switch via the plist (for scheduled runs)

The plist already sets `SIGNAL_LLM_PROVIDER=claude`. To revert to Ollama (not recommended
for scheduled runs), edit `scripts/com.flexrpl.signal.plist`:

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>SIGNAL_LLM_PROVIDER</key>
    <string>claude</string>   <!-- change to "ollama" only for manual/interactive use -->
</dict>
```

Then apply the change:

```bash
launchctl unload ~/Library/LaunchAgents/com.flexrpl.signal.plist
cp /Users/garotconklin/garotm/fleXRPL/signal/scripts/com.flexrpl.signal.plist \
   ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.flexrpl.signal.plist
```

### Option 3 — Default via sources.yaml (fallback when env var is not set)

`config/sources.yaml` defaults to `claude`:

```yaml
llm:
  provider: claude # ollama | claude
```

The precedence order is: `SIGNAL_LLM_PROVIDER` env var → `sources.yaml` → `claude`.

---

## Provider Comparison

|                      | Ollama (`qwen2.5:14b`)                                | Claude Code CLI                      |
| -------------------- | ----------------------------------------------------- | ------------------------------------ |
| **Cost**             | Free (local)                                          | Uses Claude Pro/Max subscription     |
| **Speed**            | ~28 min / full run                                    | Slower (sequential subprocess calls) |
| **Quality**          | Good                                                  | Significantly better analysis        |
| **Requires**         | Ollama running (`ollama serve`)                       | Claude Code installed + logged in    |
| **Model**            | Configured in `sources.yaml` under `llm.ollama.model` | Whatever Claude Code defaults to     |
| **Safe for launchd** | **No** — Metal GPU crashes kernel on macOS            | **Yes**                              |

**Default: Claude.** Use Ollama only for interactive manual runs where you want local/free inference.

---

## Ollama Model Configuration

The Ollama model is set in `config/sources.yaml`:

```yaml
llm:
  provider: ollama
  ollama:
    model: "qwen2.5:14b" # change this to any installed model
    base_url: "http://localhost:11434"
    timeout: 120
```

To see installed models:

```bash
ollama list
```

To pull a different model:

```bash
ollama pull qwen2.5:32b
```

---

## Testing Each Provider

Always test locally before committing provider changes.

### Step 1 — Fast smoke test (no LLM calls, no tokens consumed)

```bash
python3 main.py --collect-only
```

Confirms: config loads, DB initialises, feeds are reachable. Works for both providers.

### Step 2 — Test Claude end-to-end (default)

```bash
python3 main.py
```

Confirm you see:

- `✓ 2.x.x (Claude Code)`
- All 5 passes completing
- HTML report written to `reports/`

### Step 3 — Test Ollama end-to-end (manual/interactive only)

```bash
SIGNAL_LLM_PROVIDER=ollama python3 main.py
```

Confirm you see:

- `✓ Ollama ready with qwen2.5:14b`
- Pass 1 through Pass 5 completing
- HTML report written to `reports/`

> Do not run Ollama via `run_and_publish.sh` or launchd — it triggers Metal GPU kernel
> panics in the background daemon context. See `docs/troubleshooting-macos-crash.md`.

### Step 4 — Test the full script (mirrors launchd exactly)

```bash
bash scripts/run_and_publish.sh
# Watch progress in a second terminal:
tail -f logs/cron.log
```

### What to check if a pass fails

| Symptom                             | Likely cause                                                   |
| ----------------------------------- | -------------------------------------------------------------- |
| `LLM error: RuntimeError` in Pass 1 | Ollama not running / Claude CLI not authenticated              |
| JSON parse failures in Pass 3/4     | Model returned malformed JSON — re-run, it's non-deterministic |
| Pass 5 hangs                        | Timeout too low — increase `timeout` in `sources.yaml`         |
| `FOREIGN KEY constraint failed`     | DB corruption — delete `signal.db` and re-run                  |

---

## Manually Triggering a Run

```bash
# Run the full script exactly as launchd does (output → logs/cron.log)
bash /Users/garotconklin/garotm/fleXRPL/signal/scripts/run_and_publish.sh

# Watch the log in a second terminal
tail -f /Users/garotconklin/garotm/fleXRPL/signal/logs/cron.log

# Run pipeline only with live terminal output (no git push)
python3 /Users/garotconklin/garotm/fleXRPL/signal/main.py

# Via launchd directly (identical to the scheduled run)
launchctl start com.flexrpl.signal
```

---

## Troubleshooting

**launchd job not running:**

1. Confirm it is loaded: `launchctl list | grep flexrpl`
2. Check the log: `cat logs/cron.log`
3. After editing the plist, always copy and reload — launchd reads from `~/Library/LaunchAgents/`, not the repo

**Mac freezes or reboots during the run:**

This is almost certainly Ollama's Metal GPU driver crashing the kernel when invoked from a
background daemon. Switch to Claude — see `docs/troubleshooting-macos-crash.md` for the
full diagnosis.

**Claude CLI not found:**

```bash
which claude          # should return /opt/homebrew/bin/claude
claude --version      # should return 2.x.x (Claude Code)
```

If missing: `npm install -g @anthropic-ai/claude-code`

**Ollama not found (for manual runs only):**

```bash
ollama serve          # start the server
ollama list           # confirm qwen2.5:14b is installed
```
