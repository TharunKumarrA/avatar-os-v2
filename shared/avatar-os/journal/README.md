# Event journal

`events.jsonl` is append-only. Each line has `schema_version`, `event_id`,
`source`, `occurred_at`, `operational_day`, `type`, and `payload`.

Do not edit generated snapshots. `tools/avatar_os.py reconcile` validates and
deduplicates the full journal, creates an immutable snapshot under `snapshots/`,
then atomically replaces the `current` symlink. A crash before that final rename
leaves the previous complete snapshot active. Running `rebuild` is safe after an
interruption and produces the same projection from the journal.

Examples:

```bash
python3 tools/avatar_os.py append --source user --type daily_log \
  --payload '{"gate_minutes":82,"gate_topic":"OS scheduling"}'
python3 tools/avatar_os.py reconcile
python3 tools/avatar_os.py operational-day 2026-09-03T01:15:00+05:30
```
