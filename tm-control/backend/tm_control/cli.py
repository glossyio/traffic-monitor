"""Command line for tm-control. On a device, run it as `tm-control <command>`."""

import argparse
import logging
from pathlib import Path

from tm_control.core import migrate


def serve():
    """Run the web app. The TM_CONTROL_* environment variables configure it (see core/settings.py)."""
    # Imported here so that `migrate` keeps working even if the web dependencies are broken.
    import uvicorn

    from tm_control.app import create_app
    from tm_control.core.settings import Settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        log_config=None,
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tm-control", description="Traffic Monitor control app")
    commands = parser.add_subparsers(dest="command", required=True)

    migrate_parser = commands.add_parser("migrate", help="update config files from older installs")
    migrate_parser.add_argument("--frigate-config", type=Path, required=True, help="path to Frigate's config.yml")
    migrate_parser.add_argument("--dry-run", action="store_true", help="report what would change without writing")

    commands.add_parser(
        "serve",
        help="run the web app",
        description="Run the web app. TM_CONTROL_BIND (default 127.0.0.1:8090) and the other TM_CONTROL_* "
        "environment variables configure it.",
    )

    args = parser.parse_args(argv)
    if args.command == "migrate":
        return migrate.run(args.frigate_config, dry_run=args.dry_run)
    if args.command == "serve":
        return serve()
    return 2
