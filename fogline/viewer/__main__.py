import argparse
from pathlib import Path

import uvicorn

from fogline.viewer.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the read-only Fogline map on this machine.")
    parser.add_argument("--runs", type=Path, default=Path("runs"), help="folder of run folders")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(args.runs.resolve()), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
