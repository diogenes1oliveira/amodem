"""Entry point for amodem_duplex."""

import sys

import click

from amodem_duplex.debugtools import cli as pa_cli


@click.group()
def main() -> None:
    """amodem_duplex - Audio Modem Duplex Communication"""


main.add_command(pa_cli.pa_group)


def _main() -> int:
    main()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
