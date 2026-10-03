"""CLI setup and GTK tray entry point."""

import argparse
import getpass
import sys

from .settings import load_settings, settings_path
from .setup_service import REGIONS, connect_account


def setup(provider: str, region: str) -> None:
    print(f"Setting up {provider}. Create your own OAuth client as described in README.md.")
    client_id = input("OAuth client ID: ").strip()
    client_secret = getpass.getpass("OAuth client secret (blank if Google desktop client has none): ").strip()

    def choose(accounts: list[dict]) -> int:
        for index, item in enumerate(accounts, 1):
            print(f"{index}. {item['primaryEmailAddress']}")
        return int(input("Mailbox number: ")) - 1

    account = connect_account(provider, client_id, client_secret, region, choose)
    print(f"Connected {account['email']}. Start the app with: mail-tray")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gmail + Zoho desktop mail notifier")
    sub = parser.add_subparsers(dest="command")
    add = sub.add_parser("setup", help="Open guided setup, or use a provider for terminal setup")
    add.add_argument("provider", nargs="?", choices=["gmail", "zoho"])
    add.add_argument("--region", default="com", choices=REGIONS, help="Zoho data center")
    sub.add_parser("config", help="Create and show the settings.ini path")
    args = parser.parse_args()
    try:
        if args.command == "setup":
            if args.provider:
                setup(args.provider, args.region)
            else:
                from .setup_web import run
                run()
        elif args.command == "config":
            load_settings()
            print(settings_path())
        else:
            from .tray import run
            run()
    except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
        print(f"Mail Tray: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
