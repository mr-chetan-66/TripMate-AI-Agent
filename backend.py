import os 
import certifi
import json
from dotenv import load_dotenv

load_dotenv()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from typing import TypedDict, Annotated
import operator
import uuid
import asyncio
import psycopg
from psycopg.rows import dict_row

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langchain_groq import ChatGroq
# from tools.tavily_tool import tavily_search
# from tools.flight_tool import search_flights
from mcp_client import tavily_mcp_search, aviation_mcp_call, extract_destination, forecast_mcp_search, weather_mcp_search


def get_database_url():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. Please add your Render PostgreSQL External Database URL to .env"
        )

    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return database_url


GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing. Please add it to your .env file.")


# =========================
# LLM
# =========================

llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=GROQ_API_KEY
)


def compact_prompt_text(value: str, max_chars: int = 1200) -> str:
    if value is None:
        return ""

    text = str(value).strip()
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars].rstrip()
    return f"{truncated}...\n[truncated for model token budget]"


# =========================
# State
# =========================

class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str
    flight_results: str
    hotel_results: str
    itinerary: str
    llm_calls: int
    weather_results: str


# =========================
# Flight Agent
# =========================

# def flight_agent(state: TravelState):
#     query = state["user_query"]
#     flight_data = search_flights(query)

#     return {
#         "flight_results": flight_data,
#         "messages": [
#             AIMessage(content="Flight results fetched.")
#         ],
#         "llm_calls": state.get("llm_calls", 0) + 1
#     }




# Flight Tool Router Prompt
FLIGHT_AGENT_PROMPT = """
You are a travel flight expert.

User Query:
{query}

Airport Information:
{airport_data}

Airline Information:
{airline_data}

Generate:

1. Likely departure airport
2. Likely arrival airport
3. Airlines serving this route
4. Typical flight duration
5. Estimated airfare range
6. Peak season pricing warning
7. Booking advice

Return concise travel guidance.
"""




# Flight Agent
async def flight_agent(state: TravelState):
    print("\nINSIDE FLIGHT AGENT\n")

    query = state["user_query"]

    try:

        airports = await aviation_mcp_call(
            "list_airports"
        )

        airlines = await aviation_mcp_call(
            "list_airlines"
        )


        print("\nAIRPORTS:", airports)
        print("\nAIRLINES:", airlines)

        prompt = FLIGHT_AGENT_PROMPT.format(
            query=query,
            airport_data=compact_prompt_text(airports, 2000),
            airline_data=compact_prompt_text(airlines, 2000)
        )

        response = await llm.ainvoke([
            SystemMessage(
                content="You are an expert travel flight planner."
            ),
            HumanMessage(content=prompt)
        ], config={"max_tokens": 350})

        flight_data = compact_prompt_text(response.content, 1000)

    except Exception as e:

        flight_data = f"Flight information unavailable: {str(e)}"

    return {
        "flight_results": flight_data,
        "messages": [
            AIMessage(
                content="Flight recommendations generated"
            )
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }





# =========================
# Hotel Agent
# =========================

async def hotel_agent(state: TravelState):
    query = f"Best hotels for {state['user_query']}"
    # hotel_results = tavily_search(query)
    hotel_results = await tavily_mcp_search(query)

    safe_hotel_results = compact_prompt_text(str(hotel_results), 1000)

    return {
        "hotel_results": safe_hotel_results,
        "messages": [
            AIMessage(content="Hotel information fetched.")
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }




# =========================
# Weather Agent
# =========================

async def weather_agent(state: TravelState):

    city = extract_destination(state["user_query"])

    weather_data = await weather_mcp_search(city)
    forecast_data = await forecast_mcp_search(city)

    weather_summary = compact_prompt_text(
        f"""
        Current Weather:
        {weather_data}

        Forecast:
        {forecast_data}
        """,
        1000
    )

    return {
        "weather_results": weather_summary,
        "messages": [
            AIMessage(
                content="Weather information fetched"
            )
        ]
    }




# =========================
# Itinerary Agent
# =========================

async def itinerary_agent(state: TravelState):
    prompt = f"""
Create a complete travel itinerary.

User Query:
{state['user_query']}

Flight Results:
{compact_prompt_text(state.get('flight_results', ''), 1800)}

Hotel Results:
{compact_prompt_text(state.get('hotel_results', ''), 1800)}

Weather Results:
{compact_prompt_text(state.get('weather_results', ''), 1800)}

Make the itinerary practical, budget-aware, and easy to follow.
"""

    response = await llm.ainvoke([
        SystemMessage(content="You are an expert travel planner."),
        HumanMessage(content=prompt)
    ], config={"max_tokens": 400})

    safe_itinerary = compact_prompt_text(response.content, 1200)

    return {
        "itinerary": safe_itinerary,
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1
    }



# =========================
# Final Response Agent
# =========================

async def final_agent(state: TravelState):
    final_prompt = f"""
Generate the final travel response for the user.

User Request:
{state['user_query']}

Flights:
{compact_prompt_text(state.get('flight_results', ''), 1500)}

Hotels:
{compact_prompt_text(state.get('hotel_results', ''), 1500)}

Weather:
{compact_prompt_text(state.get('weather_results', ''), 1500)}

Itinerary:
{compact_prompt_text(state.get('itinerary', ''), 2000)}

Format the final answer beautifully using these sections:

1. Trip Summary
2. Flight Information
3. Hotel Suggestions
4. Weather Information
5. Day-by-Day Itinerary
6. Estimated Budget
7. Final Recommendations


Important:
- Be clear and practical.
- Mention that live flight API may not provide ticket prices if pricing is unavailable.
- Include weather-based travel advice.
- Keep the response useful for real travel planning.
"""

    response = await llm.ainvoke([
        SystemMessage(content="You are a professional AI travel booking assistant."),
        HumanMessage(content=final_prompt)
    ], config={"max_tokens": 500})

    return {
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1
    }


# =========================
# Build Graph
# =========================

graph = StateGraph(TravelState)

graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("itinerary_agent", itinerary_agent)
graph.add_node("final_agent", final_agent)

graph.add_edge(START, "flight_agent")
graph.add_edge("flight_agent", "hotel_agent")
graph.add_edge("hotel_agent", "weather_agent")
graph.add_edge("weather_agent", "itinerary_agent")
graph.add_edge("itinerary_agent", "final_agent")
graph.add_edge("final_agent", END)


# =========================
# PostgreSQL Checkpointer
# =========================
try:
    DATABASE_URL = get_database_url()

    _conn = psycopg.connect(
        DATABASE_URL,
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=5
    )

    checkpointer = PostgresSaver(_conn)
    checkpointer.setup()
    print("Using PostgreSQL checkpointer.")
except Exception as exc:
    print(f"PostgreSQL unavailable; using in-memory checkpointer instead: {exc}")
    checkpointer = MemorySaver()

travel_graph = graph.compile(checkpointer=checkpointer)



# =========================
# Function for FastAPI
# =========================

async def run_travel_agent(user_input: str, thread_id: str | None = None):
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    result = None
    async for event in stream_travel_agent(user_input, thread_id):
        if event["type"] == "error":
            raise RuntimeError(event["error"])
        if event["type"] == "result":
            result = event["data"]

    if result is None:
        raise RuntimeError("The travel planner finished without a result.")
    return result


TRAVEL_STAGES = {
    "flight_agent": "Searching flight options",
    "hotel_agent": "Finding hotel recommendations",
    "weather_agent": "Checking destination weather",
    "itinerary_agent": "Building your itinerary",
    "final_agent": "Preparing your final travel plan",
}

TRAVEL_STAGE_RUNTIMES = {
    "flight_agent": "Groq / openai/gpt-oss-120b",
    "hotel_agent": "Tavily MCP search",
    "weather_agent": "Weather MCP tools",
    "itinerary_agent": "Groq / openai/gpt-oss-120b",
    "final_agent": "Groq / openai/gpt-oss-120b",
}


async def stream_travel_agent(user_input: str, thread_id: str | None = None):
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {"configurable": {"thread_id": thread_id}}
    state = {
        "messages": [HumanMessage(content=user_input)],
        "user_query": user_input,
        "flight_results": "",
        "hotel_results": "",
        "weather_results": "",
        "itinerary": "",
        "llm_calls": 0,
    }
    stage_names = list(TRAVEL_STAGES)
    completed = 0

    yield {
        "type": "progress",
        "stage": stage_names[0],
        "label": TRAVEL_STAGES[stage_names[0]],
        "runtime": TRAVEL_STAGE_RUNTIMES[stage_names[0]],
        "status": "running",
        "completed": completed,
        "total": len(stage_names),
    }

    try:
        async for update in travel_graph.astream(
            state,
            config=config,
            stream_mode="updates",
        ):
            for stage_name, stage_update in update.items():
                if stage_name not in TRAVEL_STAGES:
                    continue

                for key, value in stage_update.items():
                    if key == "messages":
                        state[key].extend(value)
                    else:
                        state[key] = value

                completed += 1
                yield {
                    "type": "progress",
                    "stage": stage_name,
                    "label": TRAVEL_STAGES[stage_name],
                    "runtime": TRAVEL_STAGE_RUNTIMES[stage_name],
                    "status": "complete",
                    "completed": completed,
                    "total": len(stage_names),
                }

                if completed < len(stage_names):
                    next_stage = stage_names[completed]
                    yield {
                        "type": "progress",
                        "stage": next_stage,
                        "label": TRAVEL_STAGES[next_stage],
                        "runtime": TRAVEL_STAGE_RUNTIMES[next_stage],
                        "status": "running",
                        "completed": completed,
                        "total": len(stage_names),
                    }

        yield {
            "type": "result",
            "data": {
                "thread_id": thread_id,
                "answer": state["messages"][-1].content,
                "flight_results": state.get("flight_results", ""),
                "hotel_results": state.get("hotel_results", ""),
                "weather_results": state.get("weather_results", ""),
                "itinerary": state.get("itinerary", ""),
                "llm_calls": state.get("llm_calls", 0),
            },
        }
    except Exception as exc:
        yield {"type": "error", "error": str(exc)}