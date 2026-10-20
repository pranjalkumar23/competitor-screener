import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _yahoo import respond
    _err = None
except Exception:  # TEMP diagnostics
    respond, _err = None, traceback.format_exc()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if respond is None:
            body = _err.encode()
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)
            return
        respond(self)

    def log_message(self, *a):
        pass
