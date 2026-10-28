"""Command line for tm-control. On a device, run it as `tm-control <command>`."""

import argparse
from pathlib import Path

from tm_control.core import migrate


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tm-control", description="Traffic Monitor control app")
    commands = parser.add_subparsers(dest="command", required=True)

    migrate_parser = commands.add_parser("migrate", help="update config files from older installs")
    migrate_parser.add_argument("--frigate-config", type=Path, required=True, help="path to Frigate's config.yml")
    migrate_parser.add_argument("--dry-run", action="store_true", help="report what would change without writing")

    args = parser.parse_args(argv)
    if args.command == "migrate":
        return migrate.run(args.frigate_config, dry_run=args.dry_run)
    return 2
