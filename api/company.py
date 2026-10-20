from http.server import BaseHTTPRequestHandler

from _yahoo import respond


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        respond(self)

    def log_message(self, *a):
        pass
