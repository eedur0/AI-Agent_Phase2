from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import append_result_to_csv, run_agent
from backend.result_store import RESULT_FIELDS

TEST_CASES_PATH = Path(__file__).resolve().parent / "test_cases.txt"
RESULTS_CSV = PROJECT_ROOT / "results.csv"
DEFAULT_DATASET = "datasets/housing.csv"


def resolve_dataset_input(dataset: str) -> str:
    candidate = Path(dataset)
    if candidate.exists():
        return str(candidate)

    dataset_name = candidate.name
    nested_candidate = PROJECT_ROOT / "datasets" / dataset_name
    if nested_candidate.exists():
        return str(nested_candidate)

    return dataset


def load_test_cases(path: Path = TEST_CASES_PATH) -> list[dict[str, str]]:
    if not path.exists():
        return []

    cases: list[dict[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        csv_path, separator, question = line.partition("|")
        if not separator:
            continue

        cases.append(
            {
                "cv_path": csv_path.strip(),
                "question": question.strip(),
            }
        )

    return cases


def initialize_results_csv() -> None:
    with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        writer.writeheader()


def prompt_for_dataset() -> str:
    print(f"Dataset path [{DEFAULT_DATASET}]: ", end="", flush=True)
    dataset = input().strip()
    if not dataset:
        dataset = DEFAULT_DATASET
    return resolve_dataset_input(dataset)


def render_terminal_formatting(text: str) -> str:
    formatted = text
    replacements = [
        (r"\\textit\{([^{}]+)\}", "\033[3m\\1\033[0m"),
        (r"\\textbf\{([^{}]+)\}", "\033[1m\\1\033[0m"),
        (r"\\mathbf\{([^{}]+)\}", "\033[1m\\1\033[0m"),
        (r"\\emph\{([^{}]+)\}", "\033[3m\\1\033[0m"),
        (r"\\underline\{([^{}]+)\}", "\033[4m\\1\033[0m"),
        (r"\*\*\*([^*]+)\*\*\*", "\033[1m\033[3m\\1\033[0m"),
        (r"\*\*([^*]+)\*\*", "\033[1m\\1\033[0m"),
        (r"__([^_]+)__", "\033[1m\\1\033[0m"),
        (r"`([^`]+)`", "\033[96m\\1\033[0m"),
    ]
    for pattern, replacement in replacements:
        formatted = re.sub(pattern, replacement, formatted)
    formatted = re.sub(
        r"(^|[\s(])\*([^*]+)\*(?=[\s).,!?;:]|$)",
        lambda match: f"{match.group(1)}\033[3m{match.group(2)}\033[0m",
        formatted,
    )
    formatted = re.sub(
        r"(^|[\s(])_([^_]+)_(?=[\s).,!?;:]|$)",
        lambda match: f"{match.group(1)}\033[3m{match.group(2)}\033[0m",
        formatted,
    )
    return formatted


def print_output(output: dict) -> None:
    print("\nAnswer:")
    print(render_terminal_formatting(output.get("final_answer", "")))

    if output.get("visualization_html"):
        print("\nVisualization generated and ready for the web UI.")


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
        "visualization_html": bool(
            result_record.get("visualization_html", output.get("visualization_html"))
        ),
    }


def interactive_session() -> None:
    initialize_results_csv()

    dataset = prompt_for_dataset()
    conversation_history: list[dict] = []

    examples = load_test_cases()
    if examples:
        print(f"Loaded {len(examples)} example test case(s) from {TEST_CASES_PATH}.")

    print("Type a question and press Enter. Type END to quit.")
    print("To switch datasets during the session, type: DATASET <path/to/file.csv>")

    while True:
        print("\nQuestion> ", end="", flush=True)
        question = input().strip()

        if not question:
            continue

        if question.upper() == "END":
            print("Session ended.")
            break

        if question.upper().startswith("DATASET "):
            new_dataset = question[8:].strip()
            if new_dataset:
                dataset = resolve_dataset_input(new_dataset)
                conversation_history = []
                print(f"Dataset changed to: {dataset}")
                print("Conversation history cleared for the new dataset.")
            continue

        output = run_agent(
            question=question,
            cv_path=dataset,
            conversation_history=conversation_history,
        )
        append_result_to_csv(question, dataset, output, results_path=str(RESULTS_CSV))
        print_output(output)
        conversation_history.append(build_history_entry(question, output))


if __name__ == "__main__":
    interactive_session()
