from __future__ import annotations

import csv
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_CSV = PROJECT_ROOT / "results.csv"
RESULTS_DIR = PROJECT_ROOT / "stored_results"

RESULT_FIELDS = [
    "result_id",
    "dataset_name",
    "question",
    "resolved_question",
    "uses_prior_context",
    "execution_result_json",
    "result_json_path",
    "generated_code",
    "final_answer",
    "visualization_decision",
    "visualization_generated",
    "visualization_error",
]


def make_json_safe(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, pd.Series):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def build_result_record(question: str, csv_path: str, output: dict) -> dict:
    result_id = str(output.get("result_id") or uuid.uuid4())
    execution_result = make_json_safe(output.get("execution_result"))
    visualization_decision = make_json_safe(output.get("visualization_decision", {}))

    return {
        "schema_version": 1,
        "result_id": result_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_name": Path(csv_path).name,
        "question": question,
        "resolved_question": output.get("resolved_question", question),
        "uses_prior_context": bool(output.get("uses_prior_context", False)),
        "follow_up_context": output.get("follow_up_context", ""),
        "generated_code": output.get("generated_code", ""),
        "execution_result": execution_result,
        "evaluation": output.get("evaluation", "FAIL"),
        "final_answer": output.get("final_answer", ""),
        "visualization_decision": visualization_decision,
        "visualization_generated": bool(output.get("visualization_html")),
        "visualization_result": output.get("visualization_result", ""),
        "visualization_html": output.get("visualization_html", ""),
        "visualization_error": output.get("visualization_error", ""),
    }


def write_result_record(record: dict, results_dir: Path = RESULTS_DIR) -> Path:
    results_dir.mkdir(exist_ok=True)
    result_path = results_dir / f"{record['result_id']}.json"
    result_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return result_path


def append_result_index(
    record: dict,
    result_path: Path,
    results_path: Path = RESULTS_CSV,
) -> None:
    file_exists = results_path.exists()
    if file_exists:
        with open(results_path, newline="", encoding="utf-8") as existing:
            reader = csv.reader(existing)
            current_header = next(reader, [])
        if current_header != RESULT_FIELDS:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            archive_path = results_path.with_name(
                f"{results_path.stem}_legacy_{timestamp}{results_path.suffix}"
            )
            shutil.move(str(results_path), archive_path)
            file_exists = False

    row = {
        "result_id": record["result_id"],
        "dataset_name": record["dataset_name"],
        "question": record["question"],
        "resolved_question": record["resolved_question"],
        "uses_prior_context": record["uses_prior_context"],
        "execution_result_json": json.dumps(
            record["execution_result"],
            ensure_ascii=False,
            default=str,
        ),
        "result_json_path": str(result_path.relative_to(PROJECT_ROOT)),
        "generated_code": record["generated_code"],
        "final_answer": record["final_answer"],
        "visualization_decision": json.dumps(
            record["visualization_decision"],
            ensure_ascii=False,
            default=str,
        ),
        "visualization_generated": record["visualization_generated"],
        "visualization_error": record["visualization_error"],
    }

    with open(results_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def persist_result(
    question: str,
    csv_path: str,
    output: dict,
    results_path: str | Path,
) -> dict:
    record = build_result_record(question, csv_path, output)
    result_path = write_result_record(record)
    append_result_index(record, result_path, Path(results_path))
    return record


def load_result_record(result_id: str, results_dir: Path = RESULTS_DIR) -> dict | None:
    result_path = results_dir / f"{result_id}.json"
    if not result_path.exists():
        return None
    return json.loads(result_path.read_text(encoding="utf-8"))
