"""
Starts the app: python -m src.server [--port 8501] [--address 127.0.0.1]

The address 127.0.0.1 keeps it on this machine. With 0.0.0.0 other machines can reach it; the
password then travels unencrypted (plain HTTP), so only do that on a network you trust.
"""
import argparse

import uvicorn

from src.server.app import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Searchables: local research tool for standards PDFs and source code.")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--address", default="127.0.0.1")
    args = parser.parse_args()
    print(f"Searchables is running: http://{'127.0.0.1' if args.address == '0.0.0.0' else args.address}:{args.port}")
    uvicorn.run(app, host=args.address, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
