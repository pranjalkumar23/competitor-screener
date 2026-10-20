#!/usr/bin/env python3
"""Local dev server: static files from this folder + the same /api/* handlers Vercel runs. Run: python3 server.py [port]"""
import functools, os, sys, urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "api"))
from _yahoo import respond  # noqa: E402


class H(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if urllib.parse.urlparse(self.path).path.startswith("/api/"):
            return respond(self)
        return super().do_GET()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5901
    ThreadingHTTPServer(("127.0.0.1", port), functools.partial(H, directory=HERE)).serve_forever()
