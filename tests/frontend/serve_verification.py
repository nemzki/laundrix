"""Verification UI fixture only: isolated database and provider; never real documents or keys."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.frontend.serve_react import app
from tests.identity.fakes import FakeProvider
from werkzeug.serving import make_server, WSGIRequestHandler

app.config['IDV_ENABLED'] = True
app.extensions['idv_provider'] = FakeProvider()

if __name__ == '__main__':
    class QuietHandler(WSGIRequestHandler):
        def log_request(self, code='-', size='-'):
            pass
    server = make_server('127.0.0.1', 8773, app, threaded=False, request_handler=QuietHandler)
    print('Isolated verification UI fixtures ready', flush=True)
    server.serve_forever()
