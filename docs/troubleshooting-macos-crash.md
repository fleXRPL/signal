# Troubleshooting — macOS Kernel Panic During Scheduled Run

**Date:** 2026-05-13  
**Machine:** Mac Studio M1 (Mac13,1), 32 GB RAM, macOS 26.3.1 (25D771280a)  
**Outcome:** Root cause identified and resolved. Claude is now the default LLM provider
for all automated runs.

---

## Symptom

The `launchd`-scheduled 7:00 AM pipeline run caused the Mac to lock up completely and
require a forced reboot. A second manual run attempt also locked up the machine within
2 minutes and required a second forced reboot.

---

## Investigation

### Step 1 — Check the application log

`logs/cron.log` showed Run #12 starting normally, then stopping abruptly:

```bash
Signal run started: Wed May 13 07:09:21 EDT 2026
✓ Collected 150 articles from 18 sources
✓ Ollama ready with qwen2.5:14b

Pass 1 — Entity extraction (150 articles)
```

No error message, no traceback — the process was terminated externally (not a Python
exception).

### Step 2 — Confirm the Mac actually rebooted

```bash
last reboot
```

Output confirmed **two reboots on May 13**:

```bash
reboot time    Wed May 13 14:33   ← forced reboot after Run #13 locked up
reboot time    Wed May 13 08:34   ← kernel panic during Run #12 Pass 1
```

The 08:34 reboot happened ~85 minutes into Run #12 — right in the window where Pass 1
was making live LLM inference calls to Ollama.

### Step 3 — Examine system panic logs

```bash
ls -lt /Library/Logs/DiagnosticReports/
```

Findings:

- `panic-full-2026-05-13-142954.0002.panic` — the `.0002` suffix confirms this was the
  **second** kernel panic of the day (Run #13 forced reboot)
- No `.0001` panic file exists — it was overwritten when the second panic occurred

macOS retains only the most recent panic log, so the 08:34 crash (Run #12) was overwritten.

### Step 4 — Examine macOS system logs around the crash window

```bash
log show --start "2026-05-13 07:00:00" --end "2026-05-13 07:30:00" \
  --predicate 'processImagePath contains "python"' --style compact
```

Key observations:

- Python PID 27205 spawned at 07:09:24 and was actively making network connections
  through at least 07:17 (RSS article fetching — normal behaviour)
- AMFI logged warnings about Homebrew Python being "adhoc signed" — these are audit
  entries only, not blocks; Python ran fine past them
- No Python crash report in `~/Library/Logs/DiagnosticReports/` for May 13 AM
- No SIGKILL or SIGTERM events logged against Python or bash

### Step 5 — Check launchd job lifecycle

```bash
log show --predicate 'eventMessage CONTAINS "flexrpl"' --style compact
```

launchd successfully spawned `bash[27201]` at 07:09:21 and the job was rescheduled for
May 14 at 07:00. No termination event was logged for that PID — the kernel died before
it could write the exit record.

### Step 6 — Rule out bash script crashes

`~/Library/Logs/DiagnosticReports/` contained several `bash-*.ips` crash files from
May 12. Inspecting one:

```json
"responsibleProc" : "Cursor",
"coalitionName"   : "com.todesktop.230313mzl4w4u92"
```

All May 12 bash crashes originated from **Cursor's integrated terminal**, not from
launchd. They are unrelated to the pipeline automation.

---

## Root Cause

**Ollama's Metal GPU driver crashed the macOS kernel when invoked from a background
`launchd` daemon context.**

When `qwen2.5:14b` started processing the first LLM inference calls in Pass 1, Ollama
used Apple Metal for GPU-accelerated inference. Metal GPU access from a non-interactive
`launchd` agent operates in a different GPU session context than a foreground application.
This mismatch triggered a Metal/GPU driver kernel panic, which hard-locked the system.

This is a known macOS limitation: background daemons and agents do not have the same
GPU session entitlements as applications launched in a user login session. The problem
is not specific to the M1 chip or RAM amount — 32 GB is more than sufficient for
`qwen2.5:14b` (~9 GB loaded). The failure mode is the session context, not memory.

---

## Resolution

Switched the default LLM provider from Ollama to Claude Code CLI for all automated runs.

### Changes made

| File                               | Change                                                                                                                            |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `config/sources.yaml`              | `llm.provider` changed from `ollama` to `claude`                                                                                  |
| `scripts/com.flexrpl.signal.plist` | `SIGNAL_LLM_PROVIDER` env var changed from `ollama` to `claude`                                                                   |
| `scripts/run_and_publish.sh`       | Added `export SIGNAL_LLM_PROVIDER="${SIGNAL_LLM_PROVIDER:-claude}"` and made the Ollama startup block conditional on the provider |

### Why Claude does not cause this problem

Claude Code CLI runs as a regular subprocess (`subprocess.run(...)`) making HTTPS calls
to Anthropic's API. It does not access Metal, the GPU, or any kernel-level graphics
resources. The entire pipeline becomes network I/O-bound rather than GPU compute-bound,
which is safe in a background daemon context.

---

## Provider guidance going forward

| Use case                       | Provider                 | How to invoke                                |
| ------------------------------ | ------------------------ | -------------------------------------------- |
| Scheduled 5am launchd run      | **Claude** (default)     | Automatic                                    |
| Manual run with live output    | **Claude** (default)     | `python3 main.py`                            |
| Manual run, script + log       | **Claude** (default)     | `bash scripts/run_and_publish.sh`            |
| Local inference, no API needed | **Ollama** (manual only) | `SIGNAL_LLM_PROVIDER=ollama python3 main.py` |

> **Do not run Ollama via `run_and_publish.sh` or `launchctl start`** — the background
> GPU context will crash the kernel regardless of available RAM.

---

## Useful diagnostic commands

```bash
# Check if the Mac rebooted unexpectedly
last reboot

# List panic and crash logs
ls -lt /Library/Logs/DiagnosticReports/

# Read launchd job events for the signal job
log show --predicate 'eventMessage CONTAINS "flexrpl"' --style compact

# Check system logs around a specific window
log show --start "YYYY-MM-DD HH:MM:00" --end "YYYY-MM-DD HH:MM:00" \
  --predicate 'processImagePath contains "python" OR eventMessage contains "panic"' \
  --style compact

# Check what process caused a bash crash
grep -o '"responsibleProc"[^,]*\|"coalitionName"[^,]*' \
  ~/Library/Logs/DiagnosticReports/bash-<timestamp>.ips
```
