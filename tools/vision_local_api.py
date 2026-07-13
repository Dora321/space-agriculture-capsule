#!/usr/bin/env python3
"""Launch the loopback-only Camera Module 3 operational API."""

from __future__ import annotations

import argparse
import os

from vision.local_api import serve


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("SPACEFARM_VISION_LOCAL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SPACEFARM_VISION_LOCAL_PORT", "8791")))
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
