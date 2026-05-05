from __future__ import annotations

import io
import json
import re
import sys
import traceback
from typing import Any

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

DEFAULT_MODEL = "gpt-5.4"
SAMPLE_ROWS = 5


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(model=DEFAULT_MODEL, temperature=0)


def _clean_code_block(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [line for line in lines if not line.strip().startswith("```")]
        return "\n".join(lines).strip()
    return text


def resolve_follow_up_node(state: dict) -> dict:
    question = state["question"]
    conversation_history = state.get("conversation_history", [])

    if not conversation_history:
        return {
            "resolved_question": question,
            "uses_prior_context": False,
            "follow_up_context": "",
            "prior_turn": {},
        }

    prior_turn = conversation_history[-1]
    system_prompt = (
        "You decide whether a new CSV-analysis question depends on the immediately previous turn. "
        "If it does, rewrite it into a standalone question that incorporates the needed prior context. "
        "Reply with only valid JSON using this exact schema: "
        '{"uses_prior_context": boolean, "standalone_question": string, "relevant_context": string}. '
        "Set uses_prior_context to true only when the new question clearly refers to the previous question, "
        "answer, result, chart, or explanation."
    )
    user_prompt = (
        f"New question:\n{question}\n\n"
        "Previous turn:\n"
        f"{json.dumps(prior_turn, ensure_ascii=False, default=str)}"
    )

    response = _get_llm().invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )

    try:
        decision = json.loads(_clean_code_block(response.content))
    except json.JSONDecodeError:
        decision = {}

    if not isinstance(decision, dict):
        decision = {}

    uses_prior_context = bool(decision.get("uses_prior_context", False))
    resolved_question = str(decision.get("standalone_question") or question)
    follow_up_context = str(decision.get("relevant_context") or "")

    return {
        "resolved_question": resolved_question,
        "uses_prior_context": uses_prior_context,
        "follow_up_context": follow_up_context,
        "prior_turn": prior_turn if uses_prior_context else {},
    }


def profile_csv_node(state: dict) -> dict:
    csv_path = state["csv_path"]

    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:
        return {
            "csv_profile": f"Failed to read CSV at {csv_path}: {exc}",
            "execution_error": f"CSV read error: {exc}",
        }

    buffer = io.StringIO()
    df.info(buf=buffer)
    info_text = buffer.getvalue()
    sample_text = df.head(SAMPLE_ROWS).to_markdown(index=False)

    numeric_summary = ""
    numeric_cols = df.select_dtypes(include="number")
    if not numeric_cols.empty:
        numeric_summary = numeric_cols.describe().round(3).to_markdown()

    csv_profile = (
        f"CSV path: {csv_path}\n"
        f"Shape: {df.shape[0]} rows x {df.shape[1]} columns\n\n"
        f"Columns and dtypes:\n{info_text}\n\n"
        f"First {SAMPLE_ROWS} rows:\n{sample_text}\n\n"
        f"Numeric summary:\n{numeric_summary}"
    )

    return {"csv_profile": csv_profile, "execution_error": ""}


def generate_code_node(state: dict) -> dict:
    question = state.get("resolved_question") or state["question"]
    csv_path = state["csv_path"]
    csv_profile = state.get("csv_profile", "")
    retry_count = state.get("retry_count", 0)
    previous_code = state.get("generated_code", "")
    previous_error = state.get("execution_error", "")
    follow_up_context = state.get("follow_up_context", "")
    prior_turn = state.get("prior_turn", {})
    uses_prior_context = bool(state.get("uses_prior_context", False))
    stored_result = (
        prior_turn.get("execution_result") if isinstance(prior_turn, dict) else None
    )

    if uses_prior_context and stored_result is not None:
        system_prompt = (
            "You are writing Python code to answer a follow-up question using a stored analysis result. "
            "Return only executable Python code. The code must:\n"
            "1. use stored_result, prior_turn, and conversation_history as the only data sources\n"
            "2. never read the original CSV or any local file\n"
            "3. never call pd.read_csv, open, Path, or use csv_path\n"
            "4. answer the follow-up question by transforming, filtering, comparing, or explaining the stored result\n"
            "5. assign the final output to a variable named result\n"
            "6. avoid printing\n"
            "7. use only the standard library, pandas, and numpy\n"
            "8. make result JSON-serializable when possible\n"
            "If the stored result does not contain enough information, assign result to a concise explanation "
            "of what is missing instead of recomputing from the dataset."
        )

        retry_block = ""
        if retry_count > 0:
            retry_block = (
                "\n\nPrevious attempt failed or was judged insufficient. "
                "Fix the issue below while still using only stored_result.\n"
                f"Previous code:\n{previous_code}\n\n"
                f"Previous error or issue:\n{previous_error}\n"
            )

        user_prompt = (
            f"Follow-up question:\n{question}\n\n"
            f"Relevant prior context:\n{follow_up_context}\n\n"
            f"stored_result = {json.dumps(stored_result, ensure_ascii=False, default=str)}\n\n"
            f"prior_turn = {json.dumps(prior_turn, ensure_ascii=False, default=str)}"
            f"{retry_block}"
        )

        response = _get_llm().invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
        return {"generated_code": _clean_code_block(response.content)}

    system_prompt = (
        "You are writing Python code to answer a question about a CSV dataset. "
        "Return only executable Python code. The code must:\n"
        "1. import pandas as pd\n"
        "2. read the CSV from the provided csv_path when needed\n"
        "3. answer the question using the real column names in the dataset\n"
        "4. assign the final output to a variable named result\n"
        "5. avoid printing\n"
        "6. use only the standard library, pandas, and numpy\n"
        "7. make result JSON-serializable when possible\n"
        "8. use prior_turn if it is supplied and relevant to the follow-up question\n"
        "If the question asks for explanation, include that explanation inside result as a string, list, or dict."
    )

    retry_block = ""
    if retry_count > 0:
        retry_block = (
            "\n\nPrevious attempt failed or was judged insufficient. "
            "Fix the issue below.\n"
            f"Previous code:\n{previous_code}\n\n"
            f"Previous error or issue:\n{previous_error}\n"
        )

    user_prompt = (
        f"Question:\n{question}\n\n"
        f"csv_path = {csv_path!r}\n\n"
        f"Dataset profile:\n{csv_profile}\n\n"
        f"Follow-up context:\n{follow_up_context}\n\n"
        f"prior_turn = {json.dumps(prior_turn, ensure_ascii=False, default=str)}"
        f"{retry_block}"
    )

    response = _get_llm().invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    code = _clean_code_block(response.content)
    return {"generated_code": code}


def execute_code_node(state: dict) -> dict:
    code = state.get("generated_code", "")
    csv_path = state["csv_path"]
    prior_turn = state.get("prior_turn", {})
    conversation_history = state.get("conversation_history", [])
    uses_prior_context = bool(state.get("uses_prior_context", False))
    stored_result = (
        prior_turn.get("execution_result") if isinstance(prior_turn, dict) else None
    )

    if uses_prior_context and stored_result is not None:
        forbidden_patterns = [
            r"\bpd\.read_csv\s*\(",
            r"\bread_csv\s*\(",
            r"\bopen\s*\(",
            r"\bPath\s*\(",
            r"\bcsv_path\b",
        ]
        if any(re.search(pattern, code) for pattern in forbidden_patterns):
            return {
                "execution_result": None,
                "execution_error": (
                    "Follow-up queries must use stored_result only. "
                    "The generated code tried to access the original dataset or filesystem."
                ),
            }

    env: dict[str, Any] = {
        "csv_path": None if uses_prior_context and stored_result is not None else csv_path,
        "stored_result": stored_result,
        "prior_turn": prior_turn,
        "conversation_history": conversation_history,
    }
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()

    try:
        exec(code, env)
        result = env.get("result", None)
        error = ""
    except Exception:
        result = None
        error = traceback.format_exc()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    return {"execution_result": result, "execution_error": error}


def evaluate_node(state: dict) -> dict:
    question = state.get("resolved_question") or state["question"]
    result = state.get("execution_result")
    error = state.get("execution_error", "")
    retry_count = state.get("retry_count", 0)

    if error:
        return {
            "evaluation": "FAIL",
            "retry_count": retry_count + 1,
        }

    system_prompt = (
        "You are evaluating whether a Python result answers a CSV-analysis question. "
        "Be practical rather than overly strict. Mark PASS if the result directly answers the question "
        "and is plausibly correct and usable. Mark FAIL if it is missing, empty, irrelevant, clearly incomplete, "
        "or does not answer the question. Reply with exactly PASS or FAIL."
    )

    user_prompt = (
        f"Question:\n{question}\n\n"
        f"Execution result:\n{repr(result)}"
    )

    response = _get_llm().invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    verdict = response.content.strip().upper()
    if verdict not in {"PASS", "FAIL"}:
        verdict = "FAIL"

    return {"evaluation": verdict, "retry_count": retry_count + 1}


def generate_answer_node(state: dict) -> dict:
    question = state.get("resolved_question") or state["question"]
    result = state.get("execution_result")
    evaluation = state.get("evaluation", "FAIL")
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)
    follow_up_context = state.get("follow_up_context", "")

    if evaluation != "PASS":
        return {
            "final_answer": (
                f"The agent could not verify a correct answer after {min(retry_count, max_retries)} retry cycle(s). "
                "Please review the dataset columns, the question wording, or relax the evaluator further."
            )
        }

    system_prompt = (
        "You are a helpful data analyst. Turn the computed result into a concise natural-language answer. "
        "If the result is structured, summarize it clearly. Do not mention code or retries. "
        "Use plain text and simple Markdown bullets when helpful. "
        "Do not use LaTeX or math delimiters such as \\(...\\), \\[...\\], \\le, \\ge, "
        "\\textbf{...}, \\mathbf{...}, or \\emph{...}. "
        "Write comparison symbols directly as <=, >=, <, or >."
    )
    user_prompt = (
        f"Question:\n{question}\n\n"
        f"Relevant prior context:\n{follow_up_context}\n\n"
        f"Computed result:\n{json.dumps(result, ensure_ascii=False, default=str)}"
    )

    response = _get_llm().invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    return {"final_answer": response.content.strip()}


def assess_visualization_node(state: dict) -> dict:
    question = state.get("resolved_question") or state["question"]
    result = state.get("execution_result")
    final_answer = state.get("final_answer", "")
    evaluation = state.get("evaluation", "FAIL")

    if evaluation != "PASS":
        return {
            "visualization_decision": {
                "needed": False,
                "chart_type": "none",
                "reason": "No verified result is available to visualize.",
                "data_focus": "",
            }
        }

    system_prompt = (
        "You decide whether a CSV-analysis answer would benefit from a visualization. "
        "Consider the user's question, the computed result, and the final answer. "
        "Recommend a visualization when it would make comparisons, distributions, trends, relationships, "
        "rankings, or geographic patterns clearer. Do not recommend one for a single scalar answer "
        "unless the question explicitly asks for visual presentation. "
        "Reply with only valid JSON using this exact schema: "
        '{"needed": boolean, "chart_type": string, "reason": string, "data_focus": string}. '
        'Use "none" for chart_type when needed is false.'
    )
    user_prompt = (
        f"Question:\n{question}\n\n"
        f"Computed result:\n{json.dumps(result, ensure_ascii=False, default=str)}\n\n"
        f"Final answer:\n{final_answer}"
    )

    response = _get_llm().invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )

    try:
        decision = json.loads(_clean_code_block(response.content))
    except json.JSONDecodeError:
        decision = {
            "needed": False,
            "chart_type": "none",
            "reason": "Visualization decision could not be parsed.",
            "data_focus": "",
        }

    if not isinstance(decision, dict):
        decision = {}

    normalized_decision = {
        "needed": bool(decision.get("needed", False)),
        "chart_type": str(decision.get("chart_type") or "none"),
        "reason": str(decision.get("reason") or ""),
        "data_focus": str(decision.get("data_focus") or ""),
    }
    if not normalized_decision["needed"]:
        normalized_decision["chart_type"] = "none"

    return {"visualization_decision": normalized_decision}


def route_after_visualization_assessment(state: dict) -> str:
    decision = state.get("visualization_decision", {})
    if isinstance(decision, dict) and decision.get("needed"):
        return "generate_visualization_code"
    return "end"


def route_after_follow_up_resolution(state: dict) -> str:
    prior_turn = state.get("prior_turn", {})
    if state.get("uses_prior_context") and isinstance(prior_turn, dict):
        if prior_turn.get("execution_result") is not None:
            return "generate_code"
    return "profile_csv"


def generate_visualization_code_node(state: dict) -> dict:
    question = state.get("resolved_question") or state["question"]
    result = state.get("execution_result")
    decision = state.get("visualization_decision", {})
    follow_up_context = state.get("follow_up_context", "")
    prior_turn = state.get("prior_turn", {})
    stored_result = (
        prior_turn.get("execution_result") if isinstance(prior_turn, dict) else None
    )

    system_prompt = (
        "You are writing Python code to visualize a stored CSV-analysis result. "
        "Return only executable Python code. The code must:\n"
        "1. import pandas as pd\n"
        "2. import plotly.express as px or plotly.graph_objects as go\n"
        "3. use result, stored_result, prior_turn, and visualization_decision as the only data sources\n"
        "4. never read the original CSV or any local file\n"
        "5. assign the embeddable chart HTML to a variable named visualization_html using fig.to_html(...)\n"
        "6. avoid printing and avoid fig.show()\n"
        "7. use only the standard library, pandas, numpy, and plotly\n"
        "8. assign a short chart description string to visualization_result\n"
        "9. never call pd.read_csv, open, Path, or use csv_path\n"
        "Make the visualization self-contained with a clear title, axis labels, and readable hover labels. "
        "Make the layout spacious and readable: use fig.update_layout(height=620, margin=dict(t=120, b=120, l=90, r=90)), "
        "place legends below or to the right of the plot so they do not overlap the title, and keep titles concise. "
        "For bar charts, use visible spacing such as bargap=0.35 and bargroupgap=0.15, and rotate or wrap long x-axis labels. "
        "Avoid crowding multiple metrics into one tight plot; use grouped bars, facets, subplots, or separate traces with clear spacing when needed. "
        "If result is not detailed enough to plot, create a simple explanatory HTML placeholder and set "
        "visualization_result to explain which structured fields are missing."
    )
    user_prompt = (
        f"Question:\n{question}\n\n"
        "The final HTML should be suitable for embedding in an iframe srcdoc. "
        "Prefer fig.to_html(full_html=False, include_plotlyjs='cdn').\n\n"
        f"Visualization decision:\n{json.dumps(decision, ensure_ascii=False, default=str)}\n\n"
        f"Follow-up context:\n{follow_up_context}\n\n"
        f"prior_turn = {json.dumps(prior_turn, ensure_ascii=False, default=str)}\n\n"
        f"stored_result = {json.dumps(stored_result, ensure_ascii=False, default=str)}\n\n"
        f"Current computed result:\n{json.dumps(result, ensure_ascii=False, default=str)}"
    )

    response = _get_llm().invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )
    return {
        "generated_visualization_code": _clean_code_block(response.content),
        "visualization_html": "",
        "visualization_error": "",
    }


def execute_visualization_code_node(state: dict) -> dict:
    code = state.get("generated_visualization_code", "")
    result = state.get("execution_result")
    decision = state.get("visualization_decision", {})
    prior_turn = state.get("prior_turn", {})
    stored_result = (
        prior_turn.get("execution_result") if isinstance(prior_turn, dict) else None
    )

    forbidden_patterns = [
        r"\bpd\.read_csv\s*\(",
        r"\bread_csv\s*\(",
        r"\bopen\s*\(",
        r"\bPath\s*\(",
        r"\bcsv_path\b",
    ]
    if any(re.search(pattern, code) for pattern in forbidden_patterns):
        return {
            "visualization_html": "",
            "visualization_result": "",
            "visualization_error": (
                "Visualizations must use execution_result only. "
                "The generated code tried to access the original dataset or filesystem."
            ),
        }

    env: dict[str, Any] = {
        "result": result,
        "stored_result": stored_result,
        "prior_turn": prior_turn,
        "visualization_decision": decision,
        "visualization_html": "",
    }
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()

    try:
        exec(code, env)
        visualization_html = str(env.get("visualization_html", "") or "").strip()
        if not visualization_html:
            raise ValueError("Visualization code did not assign visualization_html.")
        error = ""
        visualization_result = env.get("visualization_result", "")
    except Exception:
        visualization_html = ""
        visualization_result = ""
        error = traceback.format_exc()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    return {
        "visualization_html": visualization_html,
        "visualization_result": visualization_result,
        "visualization_error": error,
    }


def route_after_evaluate(state: dict) -> str:
    evaluation = state.get("evaluation", "FAIL")
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    if evaluation == "PASS":
        return "generate_answer"
    if retry_count >= max_retries:
        return "generate_answer"
    return "generate_code"
