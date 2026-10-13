import os
import sys
import pandas as pd

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
    output_format: str,
    user_question: str,
) -> str:
    """Transform a file in the active session's temporary folder."""
    try:
        session_folder = get_session_folder().resolve()

        # Prefer the path supplied by the agent if it points to a
        # file inside this session. Otherwise, search this session.
        candidate = (input_file_path or "").strip().strip('"')
        input_path = None

        if candidate:
            supplied_path = os.path.abspath(
                candidate if os.path.isabs(candidate)
                else session_folder / candidate
            )

            try:
                is_inside_session = (
                    os.path.commonpath([
                        str(session_folder),
                        os.path.realpath(supplied_path),
                    ]) == os.path.realpath(session_folder)
                )
            except ValueError:
                is_inside_session = False

            if is_inside_session and os.path.isfile(supplied_path):
                input_path = supplied_path

        # If the model omitted the path or supplied an invalid one,
        # search the current session's extraction directory.
        if input_path is None:
            preferred = (
                session_folder / "data" / "extract" / "extracted_data.csv"
            )
            if preferred.is_file():
                input_path = str(preferred)
            else:
                matches = sorted(
                    (session_folder / "data" / "extract").glob("*.csv")
                ) if (session_folder / "data" / "extract").is_dir() else []

                if matches:
                    input_path = str(matches[0])
                else:
                    return (
                        "No extracted CSV was found in this session. "
                        "Please extract data in this chat first."
                    )

        extension = os.path.splitext(input_path)[1].lower()

        if extension == ".csv":
            df = pd.read_csv(input_path)
        elif extension == ".json":
            df = pd.read_json(input_path, lines=True)
        elif extension == ".parquet":
            df = pd.read_parquet(input_path)
        else:
            return f"Unsupported input format: {extension}"

        fmt = output_format.lower().strip()
        if fmt not in {"csv", "json", "parquet"}:
            return f"Unsupported output format: {output_format}"

        # Keep output inside the active session.
        output_name = f"transformed_data.{fmt}"
        output_path = get_output_path(
            os.path.join(output_folder, output_name)
        )

        # Handle this requested operation deterministically.
        question = user_question.lower()
        if "name" in question and "url" in question:
            missing = {"name", "url"} - set(df.columns)
            if missing:
                return (
                    f"Cannot perform transformation: missing columns "
                    f"{sorted(missing)}. Available columns: {list(df.columns)}"
                )
            df = df[["name", "url"]].drop_duplicates()

        else:
            llm = pick_llm("medium")
            prompt = f"""
Transform the existing pandas DataFrame named df as requested.
Return Python code only. Do not read or write files, import modules,
or specify output paths. Leave the final DataFrame in variable df.

Request: {user_question}
Columns: {list(df.columns)}
Preview:
{df.head(3).to_string(index=False)}
"""
            response = llm.invoke(prompt)
            pandas_code = response.content

            if not isinstance(pandas_code, str):
                return "Error: The model did not return Python code."

            pandas_code = pandas_code.strip()
            if pandas_code.startswith("```"):
                lines = pandas_code.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                pandas_code = "\n".join(lines).strip()

            namespace = {
                "__builtins__": {},
                "pd": pd,
                "df": df.copy(),
            }
            exec(pandas_code, namespace)
            df = namespace.get("df")

            if not isinstance(df, pd.DataFrame):
                return "Error: Transformation must leave a DataFrame named df."

        if fmt == "csv":
            df.to_csv(output_path, index=False)
        elif fmt == "json":
            df.to_json(output_path, orient="records", lines=True)
        else:
            df.to_parquet(output_path, index=False)

        return (
            f"Transformation completed successfully.\n"
            f"Input file: {input_path}\n"
            f"Output file: {output_path}\n"
            f"Format: {fmt}\n"
            f"Rows saved: {len(df)}"
        )

    except Exception as e:
        return f"Transformation failed: {type(e).__name__}: {e}"


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