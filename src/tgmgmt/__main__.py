"""Entry point: ``python -m tgmgmt`` or installed ``tgmgmt`` script."""
from __future__ import annotations

from tgmgmt.app import build_application


def main() -> None:
    app = build_application()
    app.run_polling(drop_pending_updates=True, allowed_updates=None)


if __name__ == "__main__":
    main()
