from langchain_core.messages import HumanMessage
from agents.data_agent import data_agent

response = data_agent.invoke({
    "messages": [
        HumanMessage(
            content="Show me the top 5 users with the highest ratings"
        )
    ],
    "route_response": ""
})

print(response)