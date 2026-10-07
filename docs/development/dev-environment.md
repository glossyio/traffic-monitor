---
description: Set up to contribute back to the Traffic Monitor project
---

# Dev Environment

The Traffic Monitor software is completely open source, so you are welcome to modify your devices to fit your needs. If you think others will benefit from your changes, you are welcome to [join the community](../help-and-faq/where-can-i-get-support.md) and [contribute back](contributing.md)!

The [Traffic Monitor OSS repo](https://github.com/glossyio/traffic-monitor) is set up as a [monorepo](https://en.wikipedia.org/wiki/Monorepo) containing everything to get the TM up and running.

## Node-RED logic

[Node-RED](https://nodered.org/) provides the primary logic engine to the Traffic Monitor including:

* Accepting input from other applications, such as Frigate for object detection, and sensors such as the radar for speed measurement.
* Enriching events by attaching speed
* Saving payloads and data internally
* Sending data to downstream applications

To get started developing:&#x20;

1. Access the Node-RED interface:  `http://<you_ip>:1880` and enter the default username and password.
2. Start a New Project and Clone \[your fork of] the traffic-monitor repo.  This will completely reset the current project, so ensure you have saved any changes.
3. Change `flows.json` and `package.json` to the `node-red-tm/data` directory locations so changes will be incorporated
4. Commit changes to the \[forked] repo in a new branch.
5. PR changes following the [contributing.md](contributing.md "mention") guidelines.

## Database schema

The tables in the Traffic Monitor database are defined by numbered SQL migrations in `container/node-red-tm/schema/migrations/`, not by the Node-RED flows. Every time `node-red-tm.service` starts, it applies the migrations the database doesn't have yet, before Node-RED opens it. The schema directory's `README.md` describes the full process, from writing a migration to testing the upgrade on a Pi and opening the PR.

To change the schema:

1. Add the next numbered migration, regenerate `schema.sql`, and update the table docs in [data-and-payloads](../data-and-payloads/data-overview.md).
2. Run the tests, using the dev environment from [contributing.md](contributing.md "mention"):

   ```bash
   .venv/bin/python -m pytest container/node-red-tm/schema/tests
   ```

To try a migration on a dev device, apply it while Node-RED is stopped. Deploying from the Node-RED editor doesn't restart the service, so it doesn't apply migrations. These commands use the default code owner (`tmadmin`) and install directory (`/opt/traffic-monitor`), and run the migration script from your Node-RED project's clone:

```bash
sudo systemctl stop node-red-tm.service
sudo runuser -u tmadmin -- python3 \
    /opt/traffic-monitor/node-red-tm/data/projects/<project>/container/node-red-tm/schema/tmdb_migrate.py \
    --db /opt/traffic-monitor/node-red-tm/db/tmdb.sqlite
sudo systemctl start node-red-tm.service
```

The database records each migration it applies. If you change a migration after applying it, restore the copy saved in `/opt/traffic-monitor/node-red-tm/db/backup/` and apply it again.

## Testing on a dev Pi

`script/devpi/tmdev.py` deploys your working copy to a bench Pi over SSH, runs commands on it, and records a PR's Pi test plan as a checklist. Every deploy, command, and check goes into a run log on your machine, so you can see later what ran on which Pi and how it went.

The Pis are defined in an inventory file that lists each Pi's address, login, and SSH key, plus the hardware it should have. That file and the run log stay on your machine, outside the repo. `script/devpi/README.md` covers setup and use.

{% hint style="warning" %}
Use these tools only with bench units, not field devices. Deploys pass `-y` to `tmsetup.sh`, so the Pi reboots when the installer needs it.
{% endhint %}
