"""Loopback HTTP transport; no third-party runtime dependencies."""
import argparse
import json
import logging
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .models import MODEL_REGISTRY
from .schema import SimulationInput
from .service import SimulationService, export_csv
from .storage import RunRepository

STATIC = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


def create_server(port=8765, data_dir=None):
    repository = RunRepository(Path(data_dir or Path(__file__).resolve().parents[1] / "data") / "runs.sqlite3")
    service = SimulationService(repository)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            logger.debug(format, *args)

        def send(self, status, body, content_type="application/json; charset=utf-8", filename=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def trusted_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}",
                                                f"localhost:{self.server.server_port}"}

        def do_GET(self):
            if not self.trusted_host():
                return self.send(403, {"error": "ローカルURLからアクセスしてください。"})
            path = urlsplit(self.path).path
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            try:
                if path in assets:
                    name, kind = assets[path]
                    return self.send(200, (STATIC / name).read_bytes(), kind)
                if path == "/api/config":
                    return self.send(200, {"defaults": SimulationInput().snapshot(),
                                           "models": [{"id": m.id, "label": m.label, "version": m.version} for m in
                                                      MODEL_REGISTRY.values()]})
                if path == "/api/runs":
                    return self.send(200, repository.list())
                if path.startswith("/api/results/"):
                    run_id = path.removeprefix("/api/results/")
                    csv_request, json_request = run_id.endswith(".csv"), run_id.endswith(".json")
                    if csv_request or json_request:
                        run_id = run_id[:-4] if csv_request else run_id[:-5]
                    result = service.get(run_id)
                    if result is None:
                        return self.send(404, {"error": "結果が見つかりません。未保存の結果は再計算してください。"})
                    if csv_request:
                        return self.send(200, export_csv(result), "text/csv; charset=utf-8", f"lib-{run_id}.csv")
                    return self.send(200, result, filename=f"lib-{run_id}.json" if json_request else None)
                return self.send(404, {"error": "ページが見つかりません。"})
            except Exception:
                logger.exception("Local read failed")
                return self.send(500, {"error": "ローカルのデータを読み込めませんでした。"})

        def do_POST(self):
            origin = self.headers.get("Origin")
            allowed = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
            if not self.trusted_host() or (origin is not None and origin not in allowed):
                return self.send(403, {"error": "ローカル画面から実行してください。"})
            path = urlsplit(self.path).path
            if path not in {"/api/simulate", "/api/save"}:
                return self.send(404, {"error": "APIが見つかりません。"})
            try:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("application/json で送信してください。")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("リクエストサイズが範囲外です。")
                try:
                    data = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeError):
                    raise ValueError("JSON形式を確認してください。") from None
                if path == "/api/simulate":
                    return self.send(200, service.run(data))
                if not isinstance(data, dict) or not isinstance(data.get("id"), str):
                    raise ValueError("保存する計算IDが必要です。")
                return self.send(200, service.save(data["id"]))
            except ValueError as error:
                return self.send(400, {"error": str(error)})
            except KeyError:
                return self.send(404, {"error": "保存対象が見つかりません。再計算してください。"})
            except Exception:
                logger.exception("Local simulation request failed")
                return self.send(500, {"error": "処理に失敗しました。ローカル保存先とサーバー状態を確認してください。"})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.service = service
    return server


def main():
    parser = argparse.ArgumentParser(description="LIB simulation workbench")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    server = create_server(args.port, args.data_dir)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"PyLIB UI: {url}\n終了: Ctrl+C", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
