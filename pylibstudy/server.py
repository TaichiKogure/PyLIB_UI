"""Loopback HTTP transport; no third-party runtime dependencies."""
import argparse
import json
import logging
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .cathodes import catalog as cathode_catalog, DEFAULTS as CATHODE_DEFAULTS
from .datasets import table_preview
from .design import MATERIALS, evaluate_design, templates
from .jobs import PhysicsJobs
from .models import MODEL_REGISTRY
from .physics import DEFAULTS as PHYSICS_DEFAULTS
from .schema import SimulationInput
from .service import SimulationService, export_csv
from .storage import RunRepository

STATIC = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


def create_server(port=8765, data_dir=None, research_python=None):
    repository = RunRepository(Path(data_dir or Path(__file__).resolve().parents[1] / "data") / "runs.sqlite3")
    service = SimulationService(repository)
    jobs = None

    class Handler(BaseHTTPRequestHandler):
        # Large reference/solver snapshots use a length-delimited persistent
        # connection. Avoid closing a socket immediately after a large write.
        protocol_version = "HTTP/1.1"
        timeout = 30

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
            if status >= 400:
                # Invalid/oversized bodies may not have been consumed.
                self.close_connection = True
                self.send_header("Connection", "close")
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

        def reject_post(self, status, error):
            # Consume small rejected bodies so Windows does not reset the socket
            # before the client can read the HTTP error response.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if 0 < length <= 65536:
                    self.connection.settimeout(2)
                    self.rfile.read(length)
            except (ValueError, OSError):
                pass
            return self.send(status, {"error": error})

        def do_GET(self):
            if not self.trusted_host():
                return self.send(403, {"error": "ローカルURLからアクセスしてください。"})
            path = urlsplit(self.path).path
            project_id = parse_qs(urlsplit(self.path).query).get("project_id", ["default"])[0]
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/library.js": ("library.js", "text/javascript; charset=utf-8"),
                      "/design.js": ("design.js", "text/javascript; charset=utf-8"),
                      "/design-insights.js": ("design-insights.js", "text/javascript; charset=utf-8"),
                      "/physics.js": ("physics.js", "text/javascript; charset=utf-8"),
                      "/model-tabs.js": ("model-tabs.js", "text/javascript; charset=utf-8"),
                      "/cathodes.js": ("cathodes.js", "text/javascript; charset=utf-8"),
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
                    return self.send(200, repository.list(project_id))
                if path == "/api/physics/config":
                    return self.send(200, {"defaults": PHYSICS_DEFAULTS, "environment": jobs.availability})
                if path == "/api/cathodes":
                    return self.send(200, {"defaults": CATHODE_DEFAULTS, "catalog": cathode_catalog()})
                if path == "/api/jobs":
                    return self.send(200, repository.jobs(project_id))
                if path == "/api/design/config":
                    return self.send(200, {"templates": templates(), "materials": MATERIALS})
                if path == "/api/designs":
                    return self.send(200, repository.designs(project_id))
                if path == "/api/projects":
                    return self.send(200, repository.projects())
                if path == "/api/comparisons":
                    return self.send(200, repository.comparisons(project_id))
                if path.startswith("/api/results/"):
                    run_id = path.removeprefix("/api/results/")
                    if run_id.endswith("/original"):
                        run_id = run_id.removesuffix("/original")
                        original = service.original(run_id)
                        if original is None:
                            return self.send(404, {"error": "原本が見つかりません。"})
                        record = service.get(run_id)
                        suffix = Path(record["original"]["filename"]).suffix.lower() if record else ".txt"
                        suffix = suffix if suffix in {".csv", ".tsv", ".txt"} else ".txt"
                        return self.send(200, original, "application/octet-stream", f"original-{run_id}{suffix}")
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
            except ValueError as error:
                return self.send(400, {"error": str(error)})
            except Exception:
                logger.exception("Local read failed")
                return self.send(500, {"error": "ローカルのデータを読み込めませんでした。"})

        def do_POST(self):
            origin = self.headers.get("Origin")
            allowed = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
            if not self.trusted_host() or (origin is not None and origin not in allowed):
                return self.reject_post(403, "ローカル画面から実行してください。")
            path = urlsplit(self.path).path
            if path not in {"/api/simulate", "/api/save", "/api/projects", "/api/comparisons", "/api/import/inspect",
                            "/api/import/preview", "/api/import/demo", "/api/design/evaluate", "/api/designs",
                            "/api/jobs", "/api/jobs/cancel", "/api/cathodes/simulate"}:
                return self.send(404, {"error": "APIが見つかりません。"})
            try:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("application/json で送信してください。")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= (
                        3 * 1024 * 1024 if path.startswith(
                            "/api/import/") else 262144 if path == "/api/jobs" else 65536):
                    raise ValueError("リクエストサイズが範囲外です。")
                try:
                    data = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeError):
                    raise ValueError("JSON形式を確認してください。") from None
                if not isinstance(data, dict):
                    raise ValueError("入力はオブジェクトで指定してください。")
                if path == "/api/projects":
                    return self.send(200, repository.create_project(data.get("name")))
                if path == "/api/jobs":
                    if set(data) - {"project_id", "input"}:
                        raise ValueError("ジョブの入力項目を確認してください。")
                    return self.send(202, jobs.submit(data.get("input"), data.get("project_id", "default")))
                if path == "/api/jobs/cancel":
                    if set(data) - {"project_id", "id"}:
                        raise ValueError("取消の入力項目を確認してください。")
                    return self.send(200, jobs.cancel(data.get("id"), data.get("project_id", "default")))
                if path == "/api/design/evaluate":
                    return self.send(200, evaluate_design(data))
                if path == "/api/designs":
                    return self.send(200, repository.save_design(data))
                if path == "/api/comparisons":
                    return self.send(200, repository.save_comparison(data))
                if path == "/api/import/inspect":
                    return self.send(200, table_preview(data))
                if path in {"/api/import/preview", "/api/import/demo"}:
                    return self.send(200, service.preview_import(data, demo=path.endswith("demo")))
                if path == "/api/simulate":
                    project_id = data.pop("project_id", "default")
                    design_id = data.pop("design_id", None)
                    return self.send(200, service.run(data, project_id, design_id))
                if path == "/api/cathodes/simulate":
                    project_id = data.pop("project_id", "default")
                    return self.send(200, service.run_reference(data, project_id))
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

    class LocalServer(ThreadingHTTPServer):
        request_queue_size = 64

        def server_close(self):
            if jobs is not None:
                jobs.close()
            super().server_close()

    server = LocalServer(("127.0.0.1", port), Handler)
    try:
        jobs = PhysicsJobs(repository, research_python)
    except Exception:
        server.server_close()
        raise
    server.daemon_threads = True
    server.service = service
    server.jobs = jobs
    return server


def main():
    parser = argparse.ArgumentParser(description="PyLiBStudy - LIB simulation workbench")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--research-python", type=Path, help="固定した研究用Python 3.13環境")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    server = create_server(args.port, args.data_dir, args.research_python)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"PyLiBStudy: {url}\n終了: Ctrl+C", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
