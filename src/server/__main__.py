"""
Starts the app: python -m src.server [--port 8501] [--address 127.0.0.1]

The address 127.0.0.1 keeps it on this machine. With 0.0.0.0 other machines can reach it; the
password then travels unencrypted (plain HTTP), so only do that on a network you trust.

python -m src.server --check loads everything the app needs without starting it, and says what's
missing. The run and install scripts use it, so a problem shows when installing rather than as a
service that won't start.
"""
import argparse
import os
import socket
import sys


def check(quiet: bool = False) -> int:
    """Imports every part of the app and looks for the built front end. Returns 0 when it can start."""
    try:
        from src.server.app import STATIC
    except Exception as e:   # A package that's missing or failed to install
        print(f"Searchables can't start: {type(e).__name__}: {e}")
        print("Run the install script again (deploy/macos or deploy\\windows) to reinstall its packages.")
        return 1
    if not (STATIC / "index.html").exists():
        print(f"Searchables can't start: its interface is missing from {STATIC}.")
        print("It's part of the repository (git pull, or git checkout -- src/server/static); "
              "to build it from source: cd web && npm ci && npm run build")
        return 1
    if not quiet:
        print("Searchables is ready to start.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Searchables: local research tool for standards PDFs and source code.")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--check", action="store_true", help="Check that the app can start, without starting it")
    args = parser.parse_args()
    ready = check(quiet=not args.check)
    if args.check or ready != 0:
        return ready

    # Say plainly when the port is taken (usually another copy of the app, or the background service)
    try:
        with socket.socket(socket.AF_INET6 if ":" in args.address else socket.AF_INET) as probe:
            if os.name != "nt":   # As the server does; on Windows this option would hide a port in use
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((args.address, args.port))
    except OSError as e:
        print(f"Searchables can't listen on {args.address}:{args.port}: {e}")
        print("Something else is using that port, perhaps another copy of the app. Stop it, or choose another with --port.")
        return 1

    import uvicorn

    from src.server.app import app
    print(f"Searchables is running: http://{'127.0.0.1' if args.address == '0.0.0.0' else args.address}:{args.port}", flush=True)
    uvicorn.run(app, host=args.address, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
