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
    <integer>7</integer>   <!-- 0–23, local time -->
    <key>Minute</key>
    <integer>0</integer>   <!-- 0–59 -->
</dict>
```

**Current schedule: 7:00 AM local time daily.**

Common alternatives:

| Time                  | Hour  | Minute |
| --------------------- | ----- | ------ |
| 12:01 AM              | 0     | 1      |
| 6:00 AM               | 6     | 0      |
| **7:00 AM (current)** | **7** | **0**  |
| 8:00 AM               | 8     | 0      |
| 12:00 PM              | 12    | 0      |

After editing, apply the change with the commands in the section above.

---

## Switching LLM Providers

The pipeline supports two LLM backends, switchable without touching Python code.

### Option 1 — Environment Variable (recommended for one-off runs)

```bash
# Use Ollama (default)
python3 main.py

# Use Claude Code CLI
SIGNAL_LLM_PROVIDER=claude python3 main.py
```

### Option 2 — Persistent switch via the plist (for scheduled runs)

Edit `scripts/com.flexrpl.signal.plist`:

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>SIGNAL_LLM_PROVIDER</key>
    <string>ollama</string>   <!-- change to "claude" to use Claude Code CLI -->
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

Edit `config/sources.yaml`:

```yaml
llm:
  provider: ollama # change to "claude" here as a code-level default
```

---

## Provider Comparison

|              | Ollama (`qwen2.5:14b`)                                | Claude Code CLI                      |
| ------------ | ----------------------------------------------------- | ------------------------------------ |
| **Cost**     | Free (local)                                          | Uses Claude Pro/Max subscription     |
| **Speed**    | ~28 min / full run                                    | Slower (sequential subprocess calls) |
| **Quality**  | Good                                                  | Significantly better analysis        |
| **Requires** | Ollama running (`ollama serve`)                       | Claude Code installed + logged in    |
| **Model**    | Configured in `sources.yaml` under `llm.ollama.model` | Whatever Claude Code defaults to     |

**Default: Ollama.** Switch to Claude when you want higher-quality analysis or are testing prompts.

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

### Step 2 — Test Ollama end-to-end

```bash
python3 main.py --no-fetch
```

`--no-fetch` skips full article text retrieval, making the run faster (~10 min vs ~28 min).
Confirm you see:
- `✓ Ollama ready with qwen2.5:14b`
- Pass 1 through Pass 5 completing
- HTML report written to `reports/`

### Step 3 — Test Claude end-to-end

```bash
SIGNAL_LLM_PROVIDER=claude python3 main.py --no-fetch
```

Confirm you see:
- `✓ 2.x.x (Claude Code)`
- All 5 passes completing (will be slower — each article is a subprocess call)
- HTML report written to `reports/`

### Step 4 — Compare output quality

Open both reports side by side and compare the `SITUATION OVERVIEW` and
`CONNECTIONS & PATTERNS` sections. Claude typically produces more nuanced
entity extraction and sharper cross-story analysis.

### What to check if a pass fails

| Symptom | Likely cause |
|---|---|
| `LLM error: RuntimeError` in Pass 1 | Ollama not running / Claude CLI not authenticated |
| JSON parse failures in Pass 3/4 | Model returned malformed JSON — re-run, it's non-deterministic |
| Pass 5 hangs | Timeout too low — increase `timeout` in `sources.yaml` |
| `FOREIGN KEY constraint failed` | DB corruption — delete `signal.db` and re-run |

---

## Manually Triggering a Run

```bash
# Via launchd (same environment as the scheduled job)
launchctl start com.flexrpl.signal

# Watch the log
tail -f /Users/garotconklin/garotm/fleXRPL/signal/logs/cron.log

# Directly (uses your shell's PATH and env vars)
python3 /Users/garotconklin/garotm/fleXRPL/signal/main.py
```

---

## Troubleshooting

**launchd job not running:**

1. Confirm it is loaded: `launchctl list | grep flexrpl`
2. Check the log: `cat logs/cron.log`
3. Ensure Full Disk Access is granted to `cron` in System Settings → Privacy & Security → Full Disk Access

**Ollama not found:**

- Start it: `ollama serve`
- The `run_and_publish.sh` script will attempt to start Ollama automatically if it is not running

**Claude CLI not found:**

```bash
which claude          # should return /opt/homebrew/bin/claude
claude --version      # should return 2.x.x (Claude Code)
```

If missing: `npm install -g @anthropic-ai/claude-code`
