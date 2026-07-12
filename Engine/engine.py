#!/usr/bin/env python3
"""AutoLyricMac local engine.

Step 1: exposes a health check, both as a CLI command and as a local
HTTP endpoint the Mac app polls.

Usage:
    python3 engine.py health            # prints {"status": "ok"}
    python3 engine.py serve [--port N]  # HTTP server, GET /health
"""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

DEFAULT_PORT = 8765

HEALTH_PAYLOAD = {"status": "ok"}


class EngineRequestHandler(BaseHTTPRequestHandler):
    server_version = "AutoLyricMacEngine/0.1"

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps(HEALTH_PAYLOAD).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        print(f"[engine] {self.address_string()} {fmt % args}", flush=True)


def cmd_health():
    print(json.dumps(HEALTH_PAYLOAD))


def cmd_serve(port):
    server = HTTPServer(("127.0.0.1", port), EngineRequestHandler)
    print(f"AutoLyricMac engine listening on http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="AutoLyricMac local engine")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="print engine health as JSON")
    serve = sub.add_parser("serve", help="run the local HTTP engine server")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)

    args = parser.parse_args()
    if args.command == "health":
        cmd_health()
    elif args.command == "serve":
        cmd_serve(args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
