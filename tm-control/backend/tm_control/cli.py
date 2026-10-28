"""Command line for tm-control. On a device, run it as `tm-control <command>`."""

import argparse
import json
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

    commands.add_parser(
        "claim-status", help="print whether the device is claimed", description="Print claimed or unclaimed."
    )
    commands.add_parser(
        "set-setup-code",
        help="store the setup code read from stdin (unclaimed devices only)",
        description="Read the setup code from one line of stdin and store its hash while the device is unclaimed. "
        "Prints stored, or prints claimed and exits 3 when the device is already claimed.",
    )
    reset_parser = commands.add_parser(
        "reset-admin",
        help="delete every user and print a new setup code (run with sudo)",
        description="Unclaim the device: delete every user and print a new setup code for claiming it again. "
        "Must run as root.",
    )
    reset_parser.add_argument(
        "--setup-code-file",
        type=Path,
        help="where to keep the root-only copy of the code (default: /etc/traffic-monitor/setup-code, "
        "or TM_CONTROL_SETUP_CODE_FILE)",
    )

    commands.add_parser(
        "fake-reset",
        help="start the fake device over, unclaimed, and print its setup code (fake mode only)",
        description="With TM_CONTROL_FAKE=1, delete the fake device's state (by default in ./.tm-control-fake/state) "
        "and print a new setup code. Refuses outside fake mode.",
    )
    commands.add_parser(
        "dump-openapi",
        help="print the API's OpenAPI document as JSON (for development)",
        description="Print the OpenAPI document the UI's client is typed from. Builds the app in fake mode with "
        "throwaway state, so it needs no device files.",
    )

    args = parser.parse_args(argv)
    if args.command == "migrate":
        return migrate.run(args.frigate_config, dry_run=args.dry_run)
    if args.command == "serve":
        return serve()
    if args.command == "dump-openapi":
        from tm_control import fake

        print(json.dumps(fake.openapi_document(), indent=2))
        return 0
    # Imported here, like serve's imports, so that `migrate` doesn't need the auth dependencies.
    from tm_control.core import claim_cli
    from tm_control.core.settings import Settings

    settings = Settings.from_env()
    if args.command == "fake-reset":
        from tm_control import fake

        return claim_cli.run(fake.reset, settings)
    if args.command == "claim-status":
        return claim_cli.run(claim_cli.claim_status, settings)
    if args.command == "set-setup-code":
        return claim_cli.run(claim_cli.set_setup_code, settings)
    if args.command == "reset-admin":
        return claim_cli.run(claim_cli.reset_admin, settings, setup_code_file=args.setup_code_file)
    return 2
