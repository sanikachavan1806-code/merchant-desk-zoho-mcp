from __future__ import annotations

import argparse

import uvicorn

from merchantops.config import Settings
from merchantops.service import build_service
from merchantops.web.app import create_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Mira Audio merchant desk")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    settings = Settings()
    app = create_app(build_service(settings))
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
