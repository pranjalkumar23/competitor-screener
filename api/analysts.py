import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # Vercel doesn't put api/ on the import path
from _yahoo import respond  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        respond(self)

    def log_message(self, *a):
        pass
