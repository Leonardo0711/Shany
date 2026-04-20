"""
Entry point: ``python -m shany_app``

Configura logging legible y arranca la aplicación.
"""

import logging
import sys
from pathlib import Path

# Permitir que el botón "Run" funcione añadiendo la carpeta raíz al PATH
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from shany_app_pi.app import ShanyApp


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(name)-28s │ %(levelname)-5s │ %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    app = ShanyApp()
    app.run()


if __name__ == "__main__":
    main()
