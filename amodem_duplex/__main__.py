"""Entry point for amodem_duplex."""

import sys


def _main() -> int:
    """Main entry point for aduplex command."""
    print("amodem_duplex - Audio Modem Duplex Communication", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(_main())

