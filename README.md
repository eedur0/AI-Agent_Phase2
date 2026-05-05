# CSV Analysis Agent

> NOTE: This project is still under development. Future improvements are planned for accuracy, usability, and visualization support.

This project is a chatbot-style CSV analysis agent. A user selects a dataset, asks natural-language questions, receives a final answer, and may receive a Plotly visualization. The system also supports follow-up questions that operate on prior stored results instead of recomputing from the original dataset.

## Project Structure

```text
project/
  agent.py                  # LangGraph agent definition and top-level run function
  nodes.py                  # Agent nodes for profiling, code generation, execution, answers, memory, visualization
  backend/
    webapp.py               # HTTP backend and static frontend server
    result_store.py         # Structured result persistence
    test_agent.py           # Terminal runner / test helper
    test_cases.txt          # Example questions
  frontend/
    index.html              # Chat UI markup
    app.js                  # Frontend state, sessions, requests, rendering
    styles.css              # UI styling
  datasets/
    housing.csv
    AI_Student_Life_Pakistan_2026.csv
  stored_results/           # Full JSON result records
  results.csv               # CSV index/log of all runs
  report.txt                # Design report
```

## Setup

Create a `.env` file in the project root with:

```text
OPENAI_API_KEY=your_api_key_here
```

Install the required Python dependencies in the virtual environment used by the project. The current project expects packages such as `pandas`, `python-dotenv`, `langgraph`, `langchain-openai`, and `plotly`.

## Run The Web App

From the project root:

```bash
./.venv/bin/python backend/webapp.py
```

Then open:

```text
http://127.0.0.1:8000
```

The backend serves both the API and the frontend files.

## Backend API

The backend uses Python's built-in HTTP server. Important endpoints:

- `GET /api/bootstrap`: returns available datasets and example-question metadata
- `GET /api/session`: creates a new backend session
- `POST /api/chat`: receives a user question, runs the agent, and returns a structured response
- `POST /api/reset`: resets a session for a selected dataset
- `POST /api/session/delete`: deletes a backend session
- `POST /api/upload`: uploads a CSV dataset
- `POST /api/dataset/delete`: deletes an uploaded dataset

The frontend calls these endpoints using `fetch()`.

## Agent Flow

The main agent is built in `agent.py` using LangGraph. The graph runs these major stages:

1. Resolve whether the question is a follow-up.
2. If it is not a follow-up, profile the CSV.
3. Generate Python analysis code.
4. Execute the generated code.
5. Evaluate whether the result answers the question.
6. Generate a final natural-language answer.
7. Decide whether visualization is useful.
8. If useful, generate Plotly code and execute it.

The generated analysis code must assign its computed output to a variable named `result`. That value becomes the structured `execution_result`.

## Execution Result Design

Execution results are represented as JSON-compatible structured data. A result may be:

- a scalar, such as one average value
- a dictionary, such as summary statistics
- a list of dictionaries, such as ranked rows or grouped summaries
- nested structures for explanations and examples

`backend/result_store.py` converts pandas and numpy objects into JSON-safe forms before persistence. Full result records are saved in `stored_results/*.json`, and `results.csv` stores a compact index of each run.

Each row in `results.csv` includes:

- `result_id`
- `dataset_name`
- `question`
- `resolved_question`
- `uses_prior_context`
- `execution_result_json`
- `result_json_path`
- `generated_code`
- `final_answer`
- `visualization_decision`
- `visualization_generated`
- `visualization_error`

This design makes it easy to pass results between components, inspect outputs during debugging, and reuse previous results across turns.

## Follow-Up Memory

The system implements basic conversational memory.

The backend keeps per-session history while the server is running. Each history entry stores the question, resolved question, structured execution result, final answer, visualization decision, and visualization HTML.

When a user asks a follow-up such as:

```text
Now show top 5
Filter the previous result
Sort this by average value and plot it as a bar chart
```

`resolve_follow_up_node()` determines whether the new question depends on the previous turn. If it does, the graph routes the query to code generation with `stored_result` from the prior turn. Follow-up execution blocks attempts to read the original CSV using `pd.read_csv`, `csv_path`, `open`, or `Path`.

The frontend also stores displayed chat sessions in browser `localStorage`, so reloading the page restores previous visible conversations and opens a new active session.

## Visualization

Visualization is optional. The visualization component in `nodes.py` has three responsibilities:

1. Decide whether visualization is useful.
2. If useful, choose a chart type and generate Plotly code.
3. Execute the plotting code and return embeddable HTML.

The visualization component must operate on the execution result, not the raw dataset. Generated visualization code receives `result`, `stored_result`, `prior_turn`, and `visualization_decision`. Runtime guards reject visualization code that tries to access the original dataset or filesystem.

If visualization succeeds, the backend returns `visualization_html`. The frontend displays it inside an iframe in the chat response.

## Frontend Behavior

The frontend is a chatbot-style interface with:

- dataset selector
- upload/delete dataset controls
- multiple chat sessions
- text input for questions
- chat history display
- loading indicator while the agent runs
- final answer display
- visualization display if generated
- error messages when requests fail

Responses are routed back to the session that submitted the request. This prevents a response from appearing in the wrong session if the user switches sessions while the agent is thinking.

## Terminal Runner

You can also run an interactive terminal session:

```bash
./.venv/bin/python backend/test_agent.py
```

This prompts for a dataset and lets you ask questions from the terminal. It also writes results to `results.csv` and `stored_results/`.

## Results Files

`results.csv` is a log/index of user questions and agent outputs. It contains both the user query and the generated answer/result metadata.

`stored_results/*.json` contains the full structured result record for each run. These JSON files are useful for debugging, inspecting execution outputs, and demonstrating that results are stored independently of the original dataset.

`results_legacy_*.csv` files are backup copies of older result schemas created when the result format changed.

## Notes And Limitations

- The backend session history is in memory, so backend conversational memory resets if the server restarts.
- The frontend display history persists in browser `localStorage`, but that is separate from backend memory.
- Follow-up quality depends on whether the prior result was structured enough to support the requested operation.
- Visualization quality depends on the structure of the execution result and the generated Plotly code.
- The system uses generated Python code, so runtime guards are used to prevent follow-ups and visualizations from bypassing stored results.
