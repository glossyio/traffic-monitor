# tmdb schema

The schema of the Traffic Monitor database (`tmdb.sqlite`) lives here as numbered SQL migrations. `tmdb_migrate.py` applies the ones a database doesn't have yet and records the version in SQLite's `PRAGMA user_version`. Node-RED reads and writes the tables.

| Path | Purpose |
|---|---|
| `migrations/NNNN_name.sql` | One schema change per file, applied in order |
| `schema.sql` | The full current schema, generated from the migrations. Read this to see the data model. |
| `tmdb_migrate.py` | The runner. Standard library only, Python 3.11+ |
| `tests/` | pytest suite that runs off-device with synthetic data |

## Changing the schema

1. Add `migrations/NNNN_short_name.sql` with the next number.
2. Regenerate `schema.sql`:

   ```bash
   python3 container/node-red-tm/schema/tmdb_migrate.py --dump-schema > container/node-red-tm/schema/schema.sql
   ```

3. Update the table docs in `docs/data-and-payloads/`.
4. Run the tests.

Rules for migrations:

- **Never edit, renumber, or delete a merged migration.** Devices may already have applied it. Fix mistakes with a new migration.
- **Leave out `BEGIN`, `COMMIT`, and `PRAGMA user_version`.** The runner wraps each file in a transaction and sets the version, so a failing file leaves nothing behind.
- **Prefer additive changes:** new tables, `ALTER TABLE ... ADD COLUMN`, `CREATE INDEX IF NOT EXISTS`. Renaming, retyping, or dropping a column needs SQLite's [table rebuild procedure](https://www.sqlite.org/lang_altertable.html#otheralter) and a note in the release notes.
- **Check drift reports before relying on a column.** Some devices have older table shapes. A migration that assumes the current shape fails there, and those devices keep running at the previous version.
- **Keep migrations fast.** Node-RED is down while they run, and so is its MQTT broker, which Frigate publishes to. Events in that window are lost. Time anything that touches the large `radar_*` tables against a copy of a big database first.
- **Use SQL that SQLite 3.40 supports.** That's the oldest SQLite the runner may meet on a device.

## Running the tests

From the repo root, in the dev venv:

```bash
python3 -m venv .venv && .venv/bin/pip install -r script/requirements-dev   # once
.venv/bin/python -m pytest container/node-red-tm/schema/tests
```

The tests check:

- the runner: versioning, rollback, backups, drift, and `--check`
- that every static SQL statement in `flows.json` compiles against the migrated schema
- that `schema.sql` matches the migrations

They use synthetic data only. Never add a copy of a device's database.

## Command line

```text
tmdb_migrate.py --db PATH           apply pending migrations (backing up first), then report drift
tmdb_migrate.py --db PATH --check   report version, pending migrations, and drift; change nothing
tmdb_migrate.py --dump-schema       print the schema the migrations create
```

Options:

- `--migrations DIR` defaults to `migrations/` next to the script.
- `--backup-dir DIR` defaults to `backup/` next to the database.

Exit codes:

- `0`: success.
- `1`: a migration or backup failed, or `--check` found pending migrations or drift.
- `2`: the migrations directory is invalid, for example because of a numbering gap.

Output lines start with `tmdb-migrate:`. Drift lines start with `tmdb-migrate: DRIFT`.

- **Pending migrations.** Before applying them to a database that already has tables, the runner copies it to `backup/tmdb-v<version>-<UTC time>.sqlite` and deletes older backups. If free space is under 1.2 times the database size, it skips the backup with a warning.
- **Drift.** After migrating, the runner compares the tables with the schema the migrations create and logs any difference. It never changes them.

Only run apply mode while Node-RED is stopped. `node-red-node-sqlite` sets no busy timeout, so Node-RED's writes fail while a migration holds the lock. `--check` only reads, for a few milliseconds, but a Node-RED write that lands in that instant can still fail.
