from __future__ import annotations

import json
import mimetypes
import os
import secrets
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import append_result_to_csv, run_agent
from backend.test_agent import load_test_cases

HOST = "127.0.0.1"
PORT = 8000
BACKEND_DIR = Path(__file__).resolve().parent
WEB_DIR = PROJECT_ROOT / "frontend"
DATASETS_DIR = PROJECT_ROOT / "datasets"
RESULTS_CSV = PROJECT_ROOT / "results.csv"
PROTECTED_DATASETS = {"housing.csv", "AI_Student_Life_Pakistan_2026.csv"}


def list_datasets() -> list[str]:
    dataset_names = {
        path.name
        for path in DATASETS_DIR.glob("*.csv")
        if path.name != RESULTS_CSV.name
    }
    return sorted(dataset_names)


def list_uploaded_datasets() -> list[str]:
    if not DATASETS_DIR.exists():
        return []
    return sorted(
        path.name
        for path in DATASETS_DIR.glob("*.csv")
        if path.name not in PROTECTED_DATASETS
    )


def resolve_dataset_path(dataset_name: str) -> Path | None:
    candidate = DATASETS_DIR / dataset_name
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def unique_upload_path(filename: str) -> Path:
    safe_name = Path(filename).name
    stem = Path(safe_name).stem or "uploaded_dataset"
    suffix = Path(safe_name).suffix.lower() or ".csv"
    if suffix != ".csv":
        suffix = ".csv"

    candidate = DATASETS_DIR / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = DATASETS_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def delete_uploaded_dataset(dataset_name: str) -> bool:
    safe_name = Path(dataset_name).name
    if not safe_name:
        return False

    if safe_name in PROTECTED_DATASETS:
        return False

    target = (DATASETS_DIR / safe_name).resolve()
    datasets_root = DATASETS_DIR.resolve()

    try:
        target.relative_to(datasets_root)
    except ValueError:
        return False

    if not target.exists() or not target.is_file() or target.suffix.lower() != ".csv":
        return False

    target.unlink()
    return True


def load_example_questions() -> dict[str, list[str]]:
    examples: dict[str, list[str]] = {}
    for case in load_test_cases():
        dataset = case["cv_path"]
        examples.setdefault(dataset, []).append(case["question"])
    return examples


def build_history_entry(question: str, output: dict) -> dict:
    result_record = output.get("result_record", {})
    return {
        "result_id": output.get("result_id", result_record.get("result_id", "")),
        "question": question,
        "resolved_question": output.get("resolved_question", question),
        "execution_result": result_record.get(
            "execution_result",
            output.get("execution_result"),
        ),
        "final_answer": result_record.get("final_answer", output.get("final_answer", "")),
        "visualization_decision": result_record.get(
            "visualization_decision",
            output.get("visualization_decision", {}),
        ),
        "visualization_html": result_record.get(
            "visualization_html",
            output.get("visualization_html", ""),
        ),
    }


EXAMPLE_QUESTIONS = load_example_questions()
SESSIONS: dict[str, dict[str, object]] = {}


class AgentWebHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        parsed_path = urlparse(path).path
        if parsed_path.startswith("/static/"):
            target = WEB_DIR / parsed_path.removeprefix("/static/")
        elif parsed_path == "/":
            target = WEB_DIR / "index.html"
        else:
            target = PROJECT_ROOT / parsed_path.lstrip("/")
        return str(target)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/bootstrap":
            self._handle_bootstrap()
            return
        if parsed.path == "/api/session":
            self._handle_new_session()
            return
        if parsed.path == "/":
            self.path = "/"
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/chat":
            self._handle_chat()
            return
        if parsed.path == "/api/reset":
            self._handle_reset()
            return
        if parsed.path == "/api/session/delete":
            self._handle_delete_session()
            return
        if parsed.path == "/api/upload":
            self._handle_upload()
            return
        if parsed.path == "/api/dataset/delete":
            self._handle_delete_dataset()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _read_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        if not raw_body:
            return {}
        return json.loads(raw_body.decode("utf-8"))

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_bootstrap(self) -> None:
        datasets = list_datasets()
        self._send_json(
            {
                "datasets": datasets,
                "default_dataset": datasets[0] if datasets else "",
                "uploaded_datasets": list_uploaded_datasets(),
                "example_questions": EXAMPLE_QUESTIONS,
            }
        )

    def _handle_new_session(self) -> None:
        session_id = secrets.token_hex(16)
        SESSIONS[session_id] = {"dataset": "", "history": []}
        self._send_json({"session_id": session_id})

    def _handle_reset(self) -> None:
        payload = self._read_json()
        session_id = str(payload.get("session_id", ""))
        dataset = str(payload.get("dataset", ""))
        if session_id not in SESSIONS:
            SESSIONS[session_id] = {"dataset": dataset, "history": []}
        else:
            SESSIONS[session_id]["dataset"] = dataset
            SESSIONS[session_id]["history"] = []
        self._send_json({"ok": True})

    def _handle_delete_session(self) -> None:
        payload = self._read_json()
        session_id = str(payload.get("session_id", ""))
        if session_id in SESSIONS:
            del SESSIONS[session_id]
        self._send_json({"ok": True})

    def _handle_chat(self) -> None:
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._send_json(
                {"error": "Request body must be valid JSON."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        session_id = str(payload.get("session_id", "")).strip()
        dataset = str(payload.get("dataset", "")).strip()
        question = str(payload.get("question", "")).strip()

        if not session_id:
            self._send_json(
                {"error": "session_id is required."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        if not dataset:
            self._send_json(
                {"error": "dataset is required."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        if not question:
            self._send_json(
                {"error": "question is required."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        dataset_path = resolve_dataset_path(dataset)
        if dataset_path is None:
            self._send_json(
                {"error": f"Unknown dataset: {dataset}"},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        session = SESSIONS.setdefault(session_id, {"dataset": dataset, "history": []})
        if session.get("dataset") != dataset:
            session["dataset"] = dataset
            session["history"] = []

        history = list(session.get("history", []))

        try:
            output = run_agent(
                question=question,
                cv_path=str(dataset_path),
                conversation_history=history,
            )
            append_result_to_csv(
                question,
                str(dataset_path),
                output,
                results_path=str(RESULTS_CSV),
            )
        except Exception as exc:
            self._send_json(
                {"error": str(exc)},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        session["history"] = history + [build_history_entry(question, output)]
        self._send_json(
            {
                "message": {
                    "question": question,
                    "answer": output.get("final_answer", ""),
                    "execution_result": output.get("execution_result"),
                    "visualization_html": output.get("visualization_html", ""),
                }
            }
        )

    def _handle_upload(self) -> None:
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._send_json(
                {"error": "Request body must be valid JSON."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        filename = str(payload.get("filename", "")).strip()
        content = payload.get("content", "")
        if not filename.lower().endswith(".csv"):
            self._send_json(
                {"error": "Please upload a .csv file."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
        if not isinstance(content, str) or not content.strip():
            self._send_json(
                {"error": "Uploaded CSV content was empty."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        DATASETS_DIR.mkdir(exist_ok=True)
        upload_path = unique_upload_path(filename)
        upload_path.write_text(content, encoding="utf-8")

        self._send_json(
            {
                "dataset": upload_path.name,
                "datasets": list_datasets(),
                "uploaded_datasets": list_uploaded_datasets(),
            },
            status=HTTPStatus.CREATED,
        )

    def _handle_delete_dataset(self) -> None:
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._send_json(
                {"error": "Request body must be valid JSON."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        dataset = str(payload.get("dataset", "")).strip()
        if not dataset:
            self._send_json(
                {"error": "dataset is required."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        if not delete_uploaded_dataset(dataset):
            self._send_json(
                {"error": "Only uploaded CSV files can be deleted."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        datasets = list_datasets()
        self._send_json(
            {
                "ok": True,
                "datasets": datasets,
                "default_dataset": datasets[0] if datasets else "",
                "uploaded_datasets": list_uploaded_datasets(),
            }
        )


def run_server(host: str = HOST, port: int = PORT) -> None:
    mimetypes.add_type("application/javascript", ".js")
    server = ThreadingHTTPServer((host, port), AgentWebHandler)
    print(f"Agent web app running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    port = int(os.getenv("PORT", str(PORT)))
    run_server(port=port)
