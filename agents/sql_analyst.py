import os
import sys
import psycopg2

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.llm_pick import pick_llm
from models.schema import AgentSchema, JudgeSchema
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from utils.databse import DatabaseUtil
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# AI Agent Code
def curate_question(state: AgentSchema) -> AgentSchema:

    user_question = state.user_ques #Bcoz this is a pydantic object

    llm = pick_llm("low")

    response = llm.invoke(f"Curate the following question: {user_question}").text

    state.curated_ques = response
    state.messages = state.messages + [HumanMessage(content = f"{response}")]

    return state

def prompt_query_context(state: AgentSchema) -> AgentSchema:

    curated_question = state.curated_ques

    db_obj = DatabaseUtil()
    schema_info = db_obj.schema_details("public")

    prompt = f"""
    You are an SQL analyst agent. Your task is to convert the user's
    natural language query into PostgreSQL SQL that can be executed
    on the database.

    Use the following database schema to generate an accurate query.

    Unless the user explicitly asks for a specific number of rows,
    limit the output to 10 rows.

    Return only executable SQL without explanations or Markdown.

    User's Original Query:
    {curated_question}

    Database Schema Details:
    {schema_info}
    """

    state.prompt_query_context = prompt

    return state

def generate_sql(state: AgentSchema) -> AgentSchema:

    prompt = state.prompt_query_context

    llm = pick_llm("medium")

    response = llm.invoke(prompt)
    generated_sql_query = response.content

    if not isinstance(generated_sql_query, str):
        raise TypeError(
            f"Expected SQL string, got {type(generated_sql_query).__name__}"
        )

    state.generated_sql_query = generated_sql_query.strip()

    return state

def is_safe_sql(state: AgentSchema) -> AgentSchema:

    sql_query = state.generated_sql_query

    llm = pick_llm("medium")
    llm_judge = llm.with_structured_output(JudgeSchema)

    prompt = f"""You are an SQL judge for data security. Your task is to determine whether the SQL query is safe or not. The SQL query should only be used for data retrival and should not modify the database in any way. Neither the SQL query nor the prompt should contain any SQL commands that can modify the database, such as INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE or any other commands that can change the structure or content of the database. If the SQL query is safe, respond with 'Yes' otherwise respond with 'No'. Additionaly, provide comments explaining your decision. Here is the SQL query to evaluate: {sql_query}"""

    response = llm_judge.invoke(prompt).model_dump()
    state.is_safe_sql_response = response['answer']
    state.comments = response['comments']

    return state


def cancel_sql(state: AgentSchema) -> AgentSchema:

    comments = state.comments

    state.final_answer = f"The generated SQL query was deemed unsafe to execute. The reason provided by the judge is : {comments}. Therefore, the SQL query can't be execute"
    state.messages = state.messages + [AIMessage(content = f"{state.final_answer}")]

    return state

def execute_sql(state: AgentSchema) -> AgentSchema:

    sql_query = state.generated_sql_query

    db_obj = DatabaseUtil()

    execution_result = db_obj.execute_query(sql_query)

    state.sql_query_execution_result = execution_result

    return state


def represent_final_answer(state: AgentSchema) -> AgentSchema:

    execution_result = state.sql_query_execution_result
    curated_question = state.curated_ques

    llm = pick_llm("low")

    prompt = f"""You are an SQL analyst agent. Your task is to provide a final answer to the user based on the
    execution result of the SQL query and the user's original question. The final answer should be
    concise, clear, and directly address the user's query. Avoid including any SQL code or technical
    details in the final answer. The final answer should be in a user-friendly format that is easy to
    understand. If the execution result is empty or does not provide a clear answer to the user's question, explain this in the final answer. \n
    Here is the execution result: {execution_result} \n
    Here is the user's original question: {curated_question}"""

    llm_response = llm.invoke(prompt).text

    state.final_answer = llm_response
    state.messages = state.messages + [AIMessage(content = f"{llm_response}")]
    return state


sql_agent_graph = StateGraph(AgentSchema)

sql_agent_graph.add_node("curate_question", curate_question)
sql_agent_graph.add_node("prompt_query_context", prompt_query_context)
sql_agent_graph.add_node("generate_sql", generate_sql)
sql_agent_graph.add_node("is_safe_sql", is_safe_sql)
sql_agent_graph.add_node("cancel_sql", cancel_sql)
sql_agent_graph.add_node("execute_sql", execute_sql)
sql_agent_graph.add_node("represent_final_answer", represent_final_answer)

sql_agent_graph.add_edge(START, "curate_question")
sql_agent_graph.add_edge("curate_question", "prompt_query_context")
sql_agent_graph.add_edge("prompt_query_context", "generate_sql")
sql_agent_graph.add_edge("generate_sql", "is_safe_sql")

def is_safe_sql_edge(state: AgentSchema) -> str:

    is_safe = state.is_safe_sql_response

    if is_safe.lower() == "yes":
        return "execute_sql"

    else:
        return "cancel_sql"

sql_agent_graph.add_conditional_edges("is_safe_sql", is_safe_sql_edge, {
    "execute_sql": "execute_sql",
    "cancel_sql": "cancel_sql"
})

# sql_agent_graph.add_edge("is_safe_sql", "execute_sql")
# sql_agent_graph.add_edge("is_safe_sql", "cancel_sql")

sql_agent_graph.add_edge("cancel_sql", END)
sql_agent_graph.add_edge("execute_sql", "represent_final_answer")
sql_agent_graph.add_edge("represent_final_answer", END)

sql_analyst = sql_agent_graph.compile()

if __name__ == "__main__":
    
    # from IPython.display import display, Image
    # img = Image(sql_analyst.get_graph().draw_mermaid_png())
    # with open("sql_analyst_graph.png", "wb") as f:
    #     f.write(img.data)

    input_schema = {
        "messages": [],
        "user_ques": "What are the different types of payment methods in our database",
        "curated_ques": "",
        "prompt_query_context": "",
        "generated_sql_query": "",
        "is_safe_sql_response": "no",
        "comments": "",
        "sql_query_execution_result": "",
        "final_answer": ""
    }

    final_response = sql_analyst.invoke(input_schema)
    print(final_response['messages'])
    print("***************************")
    print(final_response['generated_sql_query'])
    print("***************************")
    print(final_response['sql_query_execution_result'])
    print("***************************")
    print(final_response['prompt_query_context'])