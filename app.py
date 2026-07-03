#!/usr/bin/env python3
"""Run the Athlete Bunker local server: python app.py [--port 5002]"""
import argparse

from bunker import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Athlete Bunker training analytics")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5002)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    create_app().run(host=args.host, port=args.port, debug=args.debug)
