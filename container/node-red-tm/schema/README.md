# tmdb schema

The schema of the Traffic Monitor database (`tmdb.sqlite`) lives here as numbered SQL migrations. `tmdb_migrate.py` applies the ones a database doesn't have yet and records the version in SQLite's `PRAGMA user_version`. Node-RED reads and writes the tables but doesn't create them.

| Path | Purpose |
|---|---|
| `migrations/NNNN_name.sql` | One schema change per file, applied in order |
| `schema.sql` | The full current schema, generated from the migrations. Read this to see the data model. |
| `tmdb_migrate.py` | The runner. Standard library only, Python 3.11+ |
| `tests/` | pytest suite that runs off-device with synthetic data |

## Changing the schema

Work on a branch from `dev`. Ship the migration in the same PR as the flow changes that use it, because a device applies the migration on the same restart that loads the new flows.

1. **Plan the change.** Prefer additive changes (see the rules below). On devices you can reach, check for drift first:

   ```bash
   sudo journalctl -u node-red-tm.service -b | grep 'tmdb-migrate: DRIFT'
   ```

2. **Write the migration** as `migrations/NNNN_short_name.sql`, using the next number.
3. **Regenerate `schema.sql`:**

   ```bash
   python3 container/node-red-tm/schema/tmdb_migrate.py --dump-schema > container/node-red-tm/schema/schema.sql
   ```

4. **Update the flows and docs.** Change the nodes that write or read the new table or column, usually a prepared `INSERT` and the function node that builds its `$params`. Update the table docs in `docs/data-and-payloads/`.
5. **Run the tests** (see [Running the tests](#running-the-tests)).
   - They don't see SQL that function nodes build in JavaScript, so check those queries on the Pi.
   - If the migration transforms data, as a table rebuild or backfill does, add a test that migrates a synthetic database from the previous version and checks the rows.
6. **Test the upgrade on a Pi** (see [Testing on a Pi](#testing-on-a-pi)).
7. **Open the PR to `dev`.** In the template's Testing section, include:
   - the `tmdb-migrate` log lines and the `--check` result from the Pi
   - how long a heavy migration took
   - whether the change is additive or destructive; a destructive change also needs a line in the release notes

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

## On the device

`tmsetup.sh -t node-red-tm` copies `tmdb_migrate.py`, `migrations/`, `schema.sql`, and this README to `{{ tmsetup_codedir }}/node-red-tm/schema/` and overwrites them on every run.

- `node-red-tm.service` runs the script as `ExecStartPre`, as the code owner, so the tables are current before any flow runs.
- If a migration fails, it's rolled back, and Node-RED starts anyway on the previous version.
- Deploying from the Node-RED editor doesn't restart the service, so it doesn't apply migrations. See "Database schema" in `docs/development/dev-environment.md`.

Read the runner's output:

```bash
sudo journalctl -u node-red-tm.service -b | grep tmdb-migrate
```

Check a database without changing it (default code owner and install directory shown):

```bash
sudo runuser -u tmadmin -- python3 /opt/traffic-monitor/node-red-tm/schema/tmdb_migrate.py \
    --db /opt/traffic-monitor/node-red-tm/db/tmdb.sqlite --check
```

## Testing on a Pi

Use a test Pi, not a field device. It should run the current `dev` with a database that has data, so you test the upgrade from the previous version. It shouldn't have an active Node-RED project, or Node-RED loads the project's flows instead of the deployed ones. The paths below use the default install directory.

1. Run the `--check` command from [On the device](#on-the-device). Expect `up to date at version <N-1>` and exit code 0.
2. In the Pi's clone of the repo, check out your branch: `git fetch && git switch <branch>`.
3. If the migration is heavy, such as an index or table rebuild on a `radar_*` table, time it on a copy of the database. The time includes the backup the device makes first, and it must stay well under the service's 30-minute start timeout. Put the copy on the SD card, because `/tmp` may be in RAM:

   ```bash
   mkdir -p ~/tmdb-timing
   sudo systemctl stop node-red-tm.service
   sudo cp /opt/traffic-monitor/node-red-tm/db/tmdb.sqlite ~/tmdb-timing/
   sudo systemctl start node-red-tm.service
   sudo chown -R "$USER": ~/tmdb-timing
   time python3 container/node-red-tm/schema/tmdb_migrate.py \
       --db ~/tmdb-timing/tmdb.sqlite --backup-dir ~/tmdb-timing/backup
   rm -rf ~/tmdb-timing
   ```

4. Deploy with `bash script/tmsetup.sh -t node-red-tm`.
5. Read the runner's output (see [On the device](#on-the-device)).
   - Expect `backed up … tmdb-v<N-1>-….sqlite`, then `applied NNNN_short_name.sql`, then `migrated … from version <N-1> to <N>`, and no new `DRIFT` lines.
   - An `ERROR` line means the migration was rolled back and Node-RED is running on the previous schema.
6. Run `--check` again. Expect `up to date at version <N>` and exit code 0.
7. Check that data arrives.
   - In the Node-RED editor, click the `select latest 5 rows from <table>` inject on the table's tab and read the debug sidebar. New rows should fill the new column.
   - Also open the dashboards that read the table.
8. Restart with `sudo systemctl restart node-red-tm.service`. The log should say `up to date at version <N>`, and `db/backup/` should still hold just the one backup.

Before you switch the test Pi to a branch without your migration, clean up by hand. The deploy copies migration files but never deletes them, and the runner leaves a database alone when it's newer than its migrations.

1. Stop `node-red-tm.service`.
2. Delete your migration from `/opt/traffic-monitor/node-red-tm/schema/migrations/`.
3. If you need the previous schema back, copy the pre-migration backup from `/opt/traffic-monitor/node-red-tm/db/backup/` over `tmdb.sqlite`, as `tmadmin`. Rows written since the migration are lost.
4. Deploy the other branch, then start `node-red-tm.service`.

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
