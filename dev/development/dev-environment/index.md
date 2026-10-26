______________________________________________________________________

## description: Set up to change the Traffic Monitor: the Node-RED flows, the database schema, and testing on a dev Pi.

# Dev environment

The Traffic Monitor is open source, so you can change your devices to suit your needs. If others would benefit, [join the community](https://docs.trafficmonitor.ai/dev/help-and-faq/where-can-i-get-support/index.md) and [contribute back](https://docs.trafficmonitor.ai/dev/development/contributing/index.md).

The [repository](https://github.com/glossyio/traffic-monitor) is a monorepo with everything needed to run a device: the installer, the container definitions, the Node-RED flows, and these docs.

## Node-RED logic

[Node-RED](https://nodered.org/) runs the Traffic Monitor's logic: it receives events from Frigate and readings from the radar, pairs events with speeds, writes the database, serves the dashboards, and sends data on. The flows are in the repository at `container/node-red-tm/data/flows.json`, and the installer copies them to the device on every run, so changes made only in a device's editor are lost on the next update.

To develop on a device:

1. Open the Node-RED editor at `http://<device>:1880` and log in as `admin` with password `password`.
1. Create a new project and clone your fork of the repository. This replaces the flows on the device, so save any changes first.
1. Point the project's flow and package files at `container/node-red-tm/data/flows.json` and `package.json`, so your edits land in the repository's files.
1. Commit your changes to a branch of your fork.
1. Open a pull request, following [Contributing](https://docs.trafficmonitor.ai/dev/development/contributing/index.md).

## Database schema

The tables are defined by numbered SQL migrations in `container/node-red-tm/schema/migrations/`, not by the flows. Each time `node-red-tm.service` starts, it applies the migrations the database doesn't have yet, before Node-RED opens it. The `README.md` in the schema directory describes the whole process, from writing a migration to testing the upgrade on a Pi.

To change the schema:

1. Add the next numbered migration, regenerate `schema.sql`, and update the table docs under [Data](https://docs.trafficmonitor.ai/dev/data-and-payloads/data-overview/index.md).

1. Run the tests, using the dev environment from [Contributing](https://docs.trafficmonitor.ai/dev/development/contributing/index.md):

   ```
   .venv/bin/python -m pytest container/node-red-tm/schema/tests
   ```

To try a migration on a dev device, apply it while Node-RED is stopped. Deploying from the Node-RED editor doesn't restart the service, so it doesn't apply migrations. These commands use the default owner (`tmadmin`) and install folder, and run the migration script from your Node-RED project's clone:

```
sudo systemctl stop node-red-tm.service
sudo runuser -u tmadmin -- python3 \
    /opt/traffic-monitor/node-red-tm/data/projects/<project>/container/node-red-tm/schema/tmdb_migrate.py \
    --db /opt/traffic-monitor/node-red-tm/db/tmdb.sqlite
sudo systemctl start node-red-tm.service
```

The database records each migration it applies. If you change a migration after applying it, restore the copy saved in `/opt/traffic-monitor/node-red-tm/db/backup/` and apply it again.

## Testing on a dev Pi

`script/devpi/tmdev.py` deploys your working copy to a bench Pi over SSH, runs commands on it, and records a PR's Pi test plan as a checklist. Every deploy, command, and check goes into a run log on your machine, so you can see later what ran on which Pi and how it went.

The Pis are defined in an inventory file that lists each Pi's address, login, and SSH key, plus the hardware it should have. That file and the run log stay on your machine, outside the repository. `script/devpi/README.md` covers setup and use.

Warning

Use these tools only with bench units, not field devices. Deploys pass `-y` to the installer, so the Pi reboots whenever the installer needs it.
