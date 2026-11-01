"""Minimal Render health endpoint for the private Rugger Master repository.

Public status ONLY. No signing, trading, or user credentials. The separate
PAPER Helius pipeline is intentionally not launched until explicitly configured.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/healthz", "/api/status"):
            self.send_error(404);return
        data=json.dumps({
            "schema":"rugger-render-readonly-status-v1",
            "engine":"Rugger Master",
            "status":"DEPLOYED_IDLE",
            "helius_connected":False,
            "paper_cycle_active":False,
            "master_live_connected":False,
            "financial_order_submitted":False,
            "live_trading_enabled":False,
            "read_only":True,
            "next_step":"configure bounded Helius capture and verify PAPER runtime",
        },separators=(",",":")).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers();self.wfile.write(data)
    def log_message(self,*args):
        pass

def main():
    os.environ["RUGGER_NO_DOTENV"]="1"
    os.environ["RUGGER_LIVE_ENABLED"]="0"
    raw=os.environ.get("PORT","10000")
    if not raw.isascii() or not raw.isdigit() or not 1<=int(raw)<=65535:
        raise ValueError("invalid Render port")
    ThreadingHTTPServer(("0.0.0.0",int(raw)),Handler).serve_forever()

if __name__=="__main__":
    main()
