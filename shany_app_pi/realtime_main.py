"""Entry point experimental: ``python -m shany_app_pi.realtime_main``."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from shany_app_pi.realtime_app import ShanyRealtimeApp


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(name)-28s │ %(levelname)-5s │ %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    ShanyRealtimeApp().run()


if __name__ == "__main__":
    main()
