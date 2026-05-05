from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph

from nodes import (
    assess_visualization_node,
    evaluate_node,
    execute_code_node,
    execute_visualization_code_node,
    generate_answer_node,
    generate_code_node,
    generate_visualization_code_node,
    profile_csv_node,
    resolve_follow_up_node,
    route_after_evaluate,
    route_after_follow_up_resolution,
    route_after_visualization_assessment,
)
from backend.result_store import RESULTS_CSV, persist_result

PROJECT_ROOT = Path(__file__).resolve().parent

load_dotenv(PROJECT_ROOT / ".env")


class AgentState(TypedDict, total=False):
    question: str
    resolved_question: str
    uses_prior_context: bool
    follow_up_context: str
    conversation_history: list[dict[str, Any]]
    prior_turn: dict[str, Any]
    csv_path: str
    csv_profile: str
    generated_code: str
    execution_result: Any
    execution_error: str
    evaluation: str
    final_answer: str
    visualization_decision: dict[str, Any]
    generated_visualization_code: str
    visualization_html: str
    visualization_result: str
    visualization_error: str
    retry_count: int
    max_retries: int


def build_agent() -> Any:
    graph = StateGraph(AgentState)

    graph.add_node("resolve_follow_up", resolve_follow_up_node)
    graph.add_node("profile_csv", profile_csv_node)
    graph.add_node("generate_code", generate_code_node)
    graph.add_node("execute_code", execute_code_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("generate_answer", generate_answer_node)
    graph.add_node("assess_visualization", assess_visualization_node)
    graph.add_node("generate_visualization_code", generate_visualization_code_node)
    graph.add_node("execute_visualization_code", execute_visualization_code_node)

    graph.set_entry_point("resolve_follow_up")
    graph.add_conditional_edges(
        "resolve_follow_up",
        route_after_follow_up_resolution,
        {
            "profile_csv": "profile_csv",
            "generate_code": "generate_code",
        },
    )
    graph.add_edge("profile_csv", "generate_code")
    graph.add_edge("generate_code", "execute_code")
    graph.add_edge("execute_code", "evaluate")

    graph.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {
            "generate_code": "generate_code",
            "generate_answer": "generate_answer",
        },
    )

    graph.add_edge("generate_answer", "assess_visualization")
    graph.add_conditional_edges(
        "assess_visualization",
        route_after_visualization_assessment,
        {
            "generate_visualization_code": "generate_visualization_code",
            "end": END,
        },
    )
    graph.add_edge("generate_visualization_code", "execute_visualization_code")
    graph.add_edge("execute_visualization_code", END)
    return graph.compile()


agent = build_agent()


def run_agent(
    question: str,
    cv_path: str,
    conversation_history: list[dict[str, Any]] | None = None,
) -> dict:
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError(
            "OPENAI_API_KEY was not found. Add it to your .env file before running the agent."
        )

    initial_state: AgentState = {
        "question": question,
        "resolved_question": question,
        "uses_prior_context": False,
        "follow_up_context": "",
        "conversation_history": conversation_history or [],
        "prior_turn": {},
        "csv_path": cv_path,
        "csv_profile": "",
        "generated_code": "",
        "execution_result": None,
        "execution_error": "",
        "evaluation": "",
        "final_answer": "",
        "visualization_decision": {},
        "generated_visualization_code": "",
        "visualization_html": "",
        "visualization_result": "",
        "visualization_error": "",
        "retry_count": 0,
        "max_retries": 2,
    }

    final_state: AgentState = agent.invoke(initial_state)

    return {
        "question": final_state.get("question", question),
        "resolved_question": final_state.get("resolved_question", question),
        "uses_prior_context": final_state.get("uses_prior_context", False),
        "follow_up_context": final_state.get("follow_up_context", ""),
        "generated_code": final_state.get("generated_code", ""),
        "execution_result": final_state.get("execution_result"),
        "evaluation": final_state.get("evaluation", "FAIL"),
        "visualization_decision": final_state.get("visualization_decision", {}),
        "generated_visualization_code": final_state.get(
            "generated_visualization_code", ""
        ),
        "visualization_html": final_state.get("visualization_html", ""),
        "visualization_result": final_state.get("visualization_result", ""),
        "visualization_error": final_state.get("visualization_error", ""),
        "final_answer": final_state.get("final_answer", ""),
    }


def append_result_to_csv(
    question: str,
    csv_path: str,
    output: dict,
    results_path: str = RESULTS_CSV,
) -> dict:
    record = persist_result(question, csv_path, output, results_path)
    output["result_id"] = record["result_id"]
    output["result_record"] = record
    return record


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print('Usage: python agent.py "<question>" <path/to/file.csv>')
        raise SystemExit(1)

    q = sys.argv[1]
    p = sys.argv[2]
    result = run_agent(q, p)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
