from langchain_groq import ChatGroq
from langchain_mistralai import ChatMistralAI
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

load_dotenv()

def pick_llm(Level: str):
    if Level.lower() == "low":
        llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0)
    elif Level.lower() == 'medium':
        llm = ChatGroq(model="openai/gpt-oss-120b", temperature=2)
    elif Level.lower() == 'high':
        llm = ChatGoogleGenerativeAI(model = 'gemini-3.6-flash', temperature = 0)
    else:
        raise ValueError(f"Unsupported level: {Level}")
    return llm

