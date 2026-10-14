import os
import sys
import pandas as pd
import shutil

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

from utils.llm_pick import pick_llm
from utils.etl_tools import (
    ETLTools,
    EXTRACT_DIR,
    TRANSFORM_DIR,
    touch_activity,
    cleanup_old_files,
)
from models.schema import ETLAgentSchema
from langchain_core.messages import ToolMessage
from langgraph.graph import StateGraph, START, END
from langchain.tools import tool


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
    """Transform the latest extracted dataset and save the result."""
    try:
        cleanup_old_files()

        # Always use the latest extracted file.
        candidates = [
            path
            for path in EXTRACT_DIR.glob("extracted_data.*")
            if path.suffix.lower() in {".csv", ".json", ".parquet"}
        ]

        if not candidates:
            return "No extracted file found. Please extract data first."

        input_path = candidates[0]
        df = ETLTools._read_file(input_path)

        # Validate output format.
        fmt = (output_format or "csv").lower().strip()
        if fmt not in {"csv", "json", "parquet"}:
            return f"Unsupported output format: {output_format}"

        question = (user_question or "").lower()

        # Apply common product cleanup when requested.
        product_columns = [
            "id", "title", "category", "price", "rating", "stock"
        ]

        if (
            all(column in df.columns for column in product_columns)
            and all(column in question for column in product_columns)
        ):
            df = df[product_columns].copy()
            df = df.drop_duplicates(subset=["id"])
            df["title"] = df["title"].astype("string").str.strip()
            df = df[df["title"].notna() & df["title"].ne("")].copy()

        else:
            # Use the LLM to generate transformations for other requests.
            llm = pick_llm("medium")
            prompt = f"""
You are transforming an existing pandas DataFrame named df.

Return Python code only. Do not import modules, read files, or write files.
Use only pandas operations available through pd.
Leave the final DataFrame in the variable df.

User request:
{user_question}

Available columns:
{list(df.columns)}

Data preview:
{df.head(5).to_string(index=False)}

If a requested column does not exist, leave df unchanged.
"""
            response = llm.invoke(prompt)
            pandas_code = response.content

            if not isinstance(pandas_code, str):
                return "Transformation failed: The model did not return code."

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
                return (
                    "Transformation failed: Expected a pandas DataFrame "
                    "named df."
                )

        # Replace the previous transformed output.
        shutil.rmtree(TRANSFORM_DIR, ignore_errors=True)
        TRANSFORM_DIR.mkdir(parents=True, exist_ok=True)

        output_path = TRANSFORM_DIR / f"transformed_data.{fmt}"

        if fmt == "csv":
            df.to_csv(output_path, index=False)
        elif fmt == "json":
            df.to_json(output_path, orient="records", lines=True)
        else:
            df.to_parquet(output_path, index=False)

        touch_activity()

        return (
            "Transformation completed successfully.\n"
            f"Input file: {input_path}\n"
            f"Output file: {output_path}\n"
            f"Format: {fmt}\n"
            f"Total rows: {len(df)}\n"
            f"Columns: {list(df.columns)}\n"
            f"Preview (first 5 rows):\n"
            f"{df.head(5).to_string(index=False)}"
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