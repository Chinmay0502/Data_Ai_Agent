import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents import sql_analyst
from utils.llm_pick import pick_llm
from utils.etl_tools import ETLTools
from models.schema import RouterSchema, DataAgentSchema
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langchain.tools import tool
from langchain_groq import ChatGroq
from agents.etl_analyst import etl_analyst
from agents.sql_analyst import sql_analyst


llm = pick_llm("medium")

llm_router = llm.with_structured_output(RouterSchema)


# ---------------------------- DATA AGENT GRAPH ---------------------------- #


def router_node(state: DataAgentSchema):
    """Route database questions to SQL and extraction/transformation
    requests to ETL."""

    message = state.messages[-1].content

    prompt = f"""
    Classify the user's request into exactly one category.

    Choose "sql" when the user wants to query or analyze data
    already stored in a database.

    Choose "etl" when the user wants to extract data from an API
    or file, transform data, or save/load data to a file.

    For API extraction, CSV/JSON creation, and ETL pipelines,
    always choose "etl".

    Do not write code or answer the user's request.
    Return the structured response matching RouterSchema.

    User request:
    {message}
    """

    response = llm_router.invoke(prompt)

    route_response = response.answer.strip().lower()

    if route_response not in ("sql", "etl"):
        raise ValueError(f"Invalid router response: {route_response}")

    state.route_response = route_response

    return state

def etl_node(state:DataAgentSchema):

    message = state.messages[-1].content

    response = etl_analyst.invoke(
             {"messages":[HumanMessage(content=f"""
            {message}
    """)]}
        ) 
    state.messages = state.messages + [response]

    return state

def sql_node(state:DataAgentSchema):

    message = state.messages[-1].content

    input_schema = {
        "messages": [],
        "user_ques": f"{message}",
        "curated_ques": "",
        "prompt_query_context": "",
        "generated_sql_query": "",
        "is_safe_sql_response": "no",
        "comments": "",
        "sql_query_execution_result": "",
        "final_answer": ""
    }

    response = sql_analyst.invoke(input_schema)

    state.messages = state.messages + [response]

    return state




data_agent_graph = StateGraph(DataAgentSchema)

data_agent_graph.add_node("router_node", router_node)
data_agent_graph.add_node("etl_node", etl_node)
data_agent_graph.add_node("sql_node", sql_node)

data_agent_graph.add_edge(START, "router_node")

def route_edge(state: DataAgentSchema) -> str:
    if state.route_response == "sql":
        return "sql_node"
    elif state.route_response == "etl":
        return "etl_node"
    else:
        raise ValueError(f"Invalid route response: {state.route_response}")


data_agent_graph.add_conditional_edges("router_node", route_edge,
                                      {
                                          "sql_node": "sql_node",
                                          "etl_node": "etl_node"
                                      })

data_agent = data_agent_graph.compile()

# # Optional|
# from IPython.display import display, Image
# img = Image(data_agent.get_graph().draw_mermaid_png())
# with open("data_agent_graph.png", "wb") as f:
#     f.write(img.data)



# if __name__ == "__main__":

#     response = data_agent.invoke(
#         {"messages":[HumanMessage(content="What are the differnt type of payment method in our database")],
#         "route_response": ""}
#     )

#     print(response)