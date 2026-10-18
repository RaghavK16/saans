---
description: Run Saans (collect + brief) and reply with today's 5-line plan
argument-hint: "[run|brief|collect|backfill cpcb_bulletin|reparse]  (default: run)"
allowed-tools: Bash(.venv/bin/saans:*), Bash(ls:*), Read
---

Run the Saans CLI from the project root and report back.

1. Run `.venv/bin/saans $ARGUMENTS`. If no arguments were given, run `.venv/bin/saans run`.
   It takes about a minute (a backfill takes longer). Don't fetch anything else yourself.
2. Show the per-source status lines it printed (ok / skipped / failed) in one short list.
   Call out any **failed** source with its detail. A skipped `datagovin` just means the key isn't set.
3. If the command wrote a brief, open the newest `out/brief-*.md` and reply with:
   - the bullet lines under "## Today's plan" exactly as written (the 5-line summary),
   - any "⚠" note at the top of the brief (e.g. missed days),
   - the path to the HTML brief so it can be opened.
4. Keep it short. Don't restate the reasons sections unless asked; don't edit any files.
