import os
import sys
import pandas as pd
import re

from utils.session_storage import (
    get_output_path,
    get_session_folder,
)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.llm_pick import pick_llm
from utils.etl_tools import ETLTools
from models.schema import ETLAgentSchema
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langchain.tools import tool
from langchain_groq import ChatGroq
from utils.session_storage import current_session_id


#------------------------------------ AGENT TOOLS ------------------------------------#


@tool
def extract_load_tool(url:str, output_folder:str, format:str) -> str:
    """
    This tool extracts the data from the API (url) and loads it into the
    the desired location (output_folder).

    Args:
        url (str): The API endpoint from which to extract data.
        output_folder (str): The folder where the extracted data will be saved.
        format (str): The format in which to save the extracted data (csv, json, parquet).
    
    Returns:
        str: A message indicating the success or failure of the operation.

    """
    etl_tools = ETLTools()
    return etl_tools.extract_load(url, output_folder, format)


@tool
def transform_load_tool(
    input_file_path: str,
    output_folder: str,
    output_format: str = "csv",
    user_question: str = "",
) -> str:
    """
    Transform extracted data using validated, deterministic operations.

    Supports:
    - Loading CSV, JSON, and Parquet input files
    - Selecting columns in a requested order
    - Removing duplicate rows or duplicates based on a column
    - Dropping rows with missing or blank values in a column
    - Saving the transformed result as CSV, JSON, or Parquet

    Does not execute LLM-generated Python code.
    """

    # ---------------------------------------------------------
    # 1. Resolve the current session's directory
    # ---------------------------------------------------------
    try:
        session_id = current_session_id.get()
    except Exception:
        session_id = None

    if not session_id:
        return (
            "Error: No active session ID was found. "
            "Please start a session before transforming data."
        )

    base_dir = os.path.join("/tmp", "ola_data_agent", str(session_id))

    if not os.path.isdir(base_dir):
        return (
            f"Error: Session directory does not exist: {base_dir}. "
            "Please run extraction first."
        )

    # ---------------------------------------------------------
    # 2. Find the input file
    # ---------------------------------------------------------
    def is_inside_session(path: str) -> bool:
        try:
            return os.path.commonpath(
                [os.path.realpath(base_dir), os.path.realpath(path)]
            ) == os.path.realpath(base_dir)
        except (ValueError, OSError):
            return False

    input_path = None

    if input_file_path:
        candidate = input_file_path.strip().strip('"').strip("'")

        # Accept absolute paths or paths relative to the session.
        if not os.path.isabs(candidate):
            candidate = os.path.join(base_dir, candidate)

        candidate = os.path.realpath(candidate)

        if is_inside_session(candidate) and os.path.isfile(candidate):
            input_path = candidate

    # If the supplied path is missing or invalid, search common
    # extraction directories used by this project.
    if input_path is None:
        search_dirs = [
            os.path.join(base_dir, "extraction"),
            os.path.join(base_dir, "extract"),
            os.path.join(base_dir, "data", "extract"),
            os.path.join(base_dir, "data", "extraction"),
            base_dir,
        ]

        preferred_names = [
            "extracted_data.csv",
            "extracted_data.json",
            "extracted_data.parquet",
        ]

        for folder in search_dirs:
            if not os.path.isdir(folder):
                continue

            # Prefer canonical extraction filenames.
            for filename in preferred_names:
                candidate = os.path.join(folder, filename)
                if os.path.isfile(candidate):
                    input_path = candidate
                    break

            if input_path:
                break

            # Otherwise, use the first supported file found.
            try:
                files = sorted(os.listdir(folder))
            except OSError:
                continue

            for filename in files:
                if filename.lower().endswith(
                    (".csv", ".json", ".parquet")
                ):
                    candidate = os.path.join(folder, filename)
                    if os.path.isfile(candidate):
                        input_path = candidate
                        break

            if input_path:
                break

    if input_path is None:
        return (
            "Error: Could not find an extracted CSV, JSON, or Parquet "
            f"file inside the session directory: {base_dir}. "
            "Run extraction first and check the extraction output path."
        )

    # ---------------------------------------------------------
    # 3. Load the input file
    # ---------------------------------------------------------
    try:
        extension = os.path.splitext(input_path)[1].lower()

        if extension == ".csv":
            df = pd.read_csv(input_path)

        elif extension == ".json":
            try:
                df = pd.read_json(input_path)
            except ValueError:
                # Support JSON files containing records nested under
                # common API response keys, such as {"products": [...]}.
                import json

                with open(input_path, "r", encoding="utf-8") as file:
                    payload = json.load(file)

                if isinstance(payload, list):
                    records = payload
                elif isinstance(payload, dict):
                    records = None

                    for key in (
                        "products",
                        "results",
                        "data",
                        "items",
                        "records",
                    ):
                        value = payload.get(key)
                        if isinstance(value, list):
                            records = value
                            break

                    if records is None:
                        records = [payload]
                else:
                    return (
                        "Error: The JSON input must contain an object "
                        "or a list of records."
                    )

                df = pd.DataFrame(records)

        elif extension in (".parquet", ".pq"):
            df = pd.read_parquet(input_path)

        else:
            return (
                f"Error: Unsupported input file type '{extension}'. "
                "Supported types are CSV, JSON, and Parquet."
            )

    except Exception as exc:
        return f"Error loading input file '{input_path}': {exc}"

    if df.empty:
        return "Error: The input file contains no data rows."

    if len(df.columns) == 0:
        return "Error: The input file contains no columns."

    # Normalize column names to strings and remove surrounding spaces.
    df.columns = [str(column).strip() for column in df.columns]

    original_rows = len(df)
    operations = []

    # ---------------------------------------------------------
    # 4. Select columns in the requested order
    # ---------------------------------------------------------
    question = user_question or ""
    question_lower = question.lower()

    # Recognize phrases such as:
    # "keep only columns id, name, and email in that exact order"
    # "select columns id, name, email"
    # "retain only these columns: id, name, email"
    column_pattern = re.compile(
        r"\b(?:keep|select|retain|include|choose)\s+"
        r"(?:only\s+)?(?:the\s+)?columns?\s*"
        r"(?:in\s+(?:the\s+)?(?:following\s+)?order\s*)?"
        r"(?:in\s+(?:the\s+)?exact\s+order\s*)?"
        r"(?::|are|as|to)?\s*"
        r"(.+?)"
        r"(?=(?:\.\s|;\s|"
        r"\band\s+(?:then\s+)?(?:remove|drop|delete|deduplicate)\b|"
        r"\bremove\s+duplicates?\b|"
        r"\bdrop\s+rows?\b|"
        r"\bremove\s+rows?\b|"
        r"\bsave\s+as\b|"
        r"\bshow\s+(?:the\s+)?first\b|"
        r"\breturn\s+(?:the\s+)?first\b|$)",
        re.IGNORECASE,
    )

    column_match = column_pattern.search(question)

    if column_match:
        raw_columns = column_match.group(1).strip()

        # Remove common wrapping punctuation and list-introducing words.
        raw_columns = re.sub(
            r"^(?:these|the following|the)\s+",
            "",
            raw_columns,
            flags=re.IGNORECASE,
        )
        raw_columns = raw_columns.strip(" .:;[]()")

        # Split common natural-language lists.
        requested_columns = re.split(
            r"\s*,\s*|\s+\band\b\s+|\s*;\s*",
            raw_columns,
            flags=re.IGNORECASE,
        )

        requested_columns = [
            re.sub(r"""^[\s"'`]+|[\s"'`.]+$""", "", col).strip()
            for col in requested_columns
        ]
        requested_columns = [col for col in requested_columns if col]

        # Match names case-insensitively while retaining the actual
        # column spelling in the DataFrame.
        column_lookup = {
            str(column).strip().casefold(): column
            for column in df.columns
        }

        resolved_columns = []
        missing_columns = []

        for requested in requested_columns:
            actual = column_lookup.get(requested.casefold())

            if actual is None:
                missing_columns.append(requested)
            elif actual not in resolved_columns:
                resolved_columns.append(actual)

        if missing_columns:
            return (
                "Error: These requested columns do not exist in the input "
                f"data: {missing_columns}. Available columns: "
                f"{list(df.columns)}"
            )

        if not resolved_columns:
            return (
                "Error: No valid columns were identified in your request. "
                f"Available columns: {list(df.columns)}"
            )

        df = df.loc[:, resolved_columns].copy()
        operations.append(f"Selected columns in requested order: {resolved_columns}")

    # ---------------------------------------------------------
    # 5. Remove duplicate rows or duplicate values by key
    # ---------------------------------------------------------
    remove_duplicates = bool(
        re.search(
            r"\b(remove|drop|delete|deduplicate|dedup|eliminate)\b"
            r".{0,45}\bduplicates?\b",
            question_lower,
        )
        or re.search(
            r"\bduplicates?\b.{0,35}\b(remove|drop|delete|eliminate)\b",
            question_lower,
        )
    )

    if remove_duplicates:
        # Try to identify an explicit key:
        # "remove duplicates based on id"
        # "deduplicate using email"
        key_match = re.search(
            r"\b(?:based\s+on|using|by|according\s+to)\s+"
            r"(?:the\s+)?(?:column\s+)?"
            r"[`'\"]?([A-Za-z_][A-Za-z0-9_ .-]*?)[`'\"]?"
            r"(?=\s*(?:,|\.|;|\band\b|\bwhere\b|\bthen\b|$))",
            question,
            flags=re.IGNORECASE,
        )

        dedupe_column = None

        if key_match:
            requested_key = key_match.group(1).strip().rstrip(" .")
            lookup = {
                str(column).casefold(): column
                for column in df.columns
            }
            dedupe_column = lookup.get(requested_key.casefold())

        # Also recognize common phrasing like "duplicate IDs".
        if dedupe_column is None and re.search(
            r"\bduplicate\s+(?:ids?|identifiers?)\b",
            question_lower,
        ):
            for column in df.columns:
                if str(column).casefold() in ("id", "ids", "identifier"):
                    dedupe_column = column
                    break

        before = len(df)

        if dedupe_column is not None:
            df = df.drop_duplicates(subset=[dedupe_column])
            operations.append(
                f"Removed duplicates based on '{dedupe_column}': "
                f"{before - len(df)} rows removed"
            )
        else:
            df = df.drop_duplicates()
            operations.append(
                f"Removed fully duplicated rows: {before - len(df)} rows removed"
            )

    # ---------------------------------------------------------
    # 6. Drop rows with missing or blank values
    # ---------------------------------------------------------
    # Recognize:
    # "drop rows where name is missing or blank"
    # "remove records with empty email"
    missing_match = re.search(
        r"\b(?:drop|remove|delete|exclude|filter\s+out)\s+"
        r"(?:all\s+)?(?:rows?|records?)\s+"
        r"(?:where|when|with)\s+"
        r"(?:the\s+)?(?:column\s+)?"
        r"[`'\"]?([A-Za-z_][A-Za-z0-9_ .-]*?)[`'\"]?\s+"
        r"(?:is|are|has|have)\s+"
        r"(?:missing|blank|empty|null|nulls|na|n/?a)\b",
        question,
        flags=re.IGNORECASE,
    )

    # Alternative: "drop rows with missing name"
    if missing_match is None:
        missing_match = re.search(
            r"\b(?:drop|remove|delete|exclude|filter\s+out)\s+"
            r"(?:all\s+)?(?:rows?|records?)\s+with\s+"
            r"(?:missing|blank|empty|null|na|n/?a)\s+"
            r"(?:values?\s+in\s+)?(?:the\s+)?"
            r"[`'\"]?([A-Za-z_][A-Za-z0-9_ .-]*?)"
            r"[`'\"]?(?=\s*(?:,|\.|;|\band\b|$))",
            question,
            flags=re.IGNORECASE,
        )

    if missing_match:
        requested_column = missing_match.group(1).strip().rstrip(" .")
        column_lookup = {
            str(column).casefold(): column
            for column in df.columns
        }
        missing_column = column_lookup.get(requested_column.casefold())

        if missing_column is None:
            return (
                f"Error: The column '{requested_column}' requested for "
                f"missing-value removal does not exist in the current "
                f"data. Available columns: {list(df.columns)}"
            )

        before = len(df)
        not_blank = (
            df[missing_column].notna()
            & df[missing_column].astype("string").str.strip().ne("")
        )
        df = df.loc[not_blank].copy()

        operations.append(
            f"Removed rows with missing or blank '{missing_column}': "
            f"{before - len(df)} rows removed"
        )

    # ---------------------------------------------------------
    # 7. Validate output format and create output directory
    # ---------------------------------------------------------
    output_format = (output_format or "csv").lower().strip()
    if output_format.startswith("."):
        output_format = output_format[1:]

    supported_formats = {"csv", "json", "parquet"}

    if output_format not in supported_formats:
        return (
            f"Error: Unsupported output format '{output_format}'. "
            "Choose csv, json, or parquet."
        )

    # Save inside the active session so different sessions do not
    # overwrite each other's files.
    if not output_folder:
        output_folder = os.path.join(base_dir, "transformation")

    if not os.path.isabs(output_folder):
        output_folder = os.path.join(base_dir, output_folder)

    output_folder = os.path.realpath(output_folder)

    if not is_inside_session(output_folder):
        return (
            "Error: The output folder must be inside the current "
            "session directory."
        )

    try:
        os.makedirs(output_folder, exist_ok=True)
    except OSError as exc:
        return f"Error creating output directory: {exc}"

    output_path = os.path.join(
        output_folder,
        f"transformed_data.{output_format}",
    )

    # ---------------------------------------------------------
    # 8. Save transformed data
    # ---------------------------------------------------------
    try:
        if output_format == "csv":
            df.to_csv(output_path, index=False)

        elif output_format == "json":
            df.to_json(
                output_path,
                orient="records",
                indent=2,
                force_ascii=False,
            )

        elif output_format == "parquet":
            df.to_parquet(output_path, index=False)

    except Exception as exc:
        return (
            f"Error saving transformed data to '{output_path}': {exc}"
        )

    # ---------------------------------------------------------
    # 9. Return a compact result
    # ---------------------------------------------------------
    preview = df.head(5).to_string(index=False)

    operation_summary = (
        "\n".join(f"- {operation}" for operation in operations)
        if operations
        else "- No recognized transformation operations were requested."
    )

    return (
        "Transformation completed successfully.\n"
        f"Input file: {input_path}\n"
        f"Output file: {output_path}\n"
        f"Output format: {output_format}\n"
        f"Original row count: {original_rows}\n"
        f"Final row count: {len(df)}\n"
        f"Columns: {list(df.columns)}\n\n"
        f"Operations performed:\n{operation_summary}\n\n"
        f"First {min(5, len(df))} rows:\n{preview}"
    )


# Toolkit 
tools = [extract_load_tool, transform_load_tool]

llm = pick_llm("medium")
llm_bind = llm.bind_tools(tools)


# ---------------------------------------- AGENT GRAPH ---------------------------------------- #


def llm_node(state: ETLAgentSchema):
    messages = state.messages

    # Keep only a small amount of recent context.
    recent_messages = messages[-4:]

    prompt = f"""
You are a Python Data Analyst with tools for extracting,
transforming, and saving data.

Use the available tools to perform the user's ETL request.
After a tool finishes, inspect its result and continue if needed.
When the task is complete, clearly report the result.

Recent conversation:
{recent_messages}
"""

    final_answer = llm_bind.invoke(prompt)

    return {
        "messages": [final_answer]
    }


def tool_node(state:ETLAgentSchema):
    """
    This node is responsible for invoking the appropriate tool based on the user's question and the context provided by the LLM.
    """

    tools_results = []

    tools_by_name = {tool.name: tool for tool in tools}

    tool_calls = state.messages[-1].tool_calls

    for tool_call in tool_calls:

        tool = tools_by_name[tool_call['name']]
        observation = tool.invoke(tool_call['args'])

        tools_results.append(ToolMessage(content=observation, tool_call_id = tool_call['id']))

    state.messages = state.messages + tools_results

    return state   


# Nodes & Edges
etl_analyst_graph = StateGraph(ETLAgentSchema)
etl_analyst_graph.add_node("llm_node", llm_node)
etl_analyst_graph.add_node("tool_node", tool_node)

etl_analyst_graph.add_edge(START, "llm_node")

def is_tool_call(state:ETLAgentSchema):
    tool_calls = state.messages[-1].tool_calls

    if tool_calls:
        return "tool_node"
    else:
        return "end"

etl_analyst_graph.add_conditional_edges(
    "llm_node",is_tool_call,
    {
        "tool_node": "tool_node",
        "end": END
    }
)

etl_analyst_graph.add_edge("tool_node", "llm_node")

etl_analyst = etl_analyst_graph.compile()

# if __name__ == "__main__":
    # Compile the Graph
    

    # Optional
    # from IPython.display import display, Image
    # img = Image(etl_analyst.get_graph().draw_mermaid_png())
    # with open("etl_analyst_graph.png", "wb") as f:
    #     f.write(img.data)

    # response = etl_analyst.invoke(
    #     {"messages":[HumanMessage(content="I want to extract the data from the API endpoint 'https://pokeapi.co/api/v2/pokemon' and save it to data/extract folder in the csv folder")]}
    # )z

#     response = etl_analyst.invoke(
#          {"messages":[HumanMessage(content=f"""
#             I want to transform the data stored in the 'D:\\programming codes\\New Beginning\\Agentic AI Using Langraph\\Ola_Data_Agent\\data\\extract\\extracted_data.csv' file 
#             and save the transformed data in the 'D:\\programming codes\\New Beginning\\Agentic AI Using Langraph\\Ola_Data_Agent\\data\\transform\\transformed_data.csv' folder in the csv format.
#             The transformation should filter the data to show bulbasaur pokemon only.
# """)]}
#     )    

#     print(response)