import json
import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.app.agent.graph import bi_agent
from backend.app.agent.state import AgentState

app = FastAPI(title="Enterprise BI Copilot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QueryRequest(BaseModel):
    message: str

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Enterprise BI Copilot Backend"}

@app.post("/api/chat")
async def chat_endpoint(payload: QueryRequest):
    async def event_generator():
        initial_state = AgentState(user_query=payload.message)
        
        yield {
            "event": "step",
            "data": json.dumps({"step": "start", "message": "Analyzing query and formulating execution plan..."})
        }
        await asyncio.sleep(0.05)

        accumulated_state = {}

        try:
            for chunk in bi_agent.stream(initial_state):
                for node_name, node_output in chunk.items():
                    accumulated_state.update(node_output)
                    step_data = {
                        "node": node_name,
                        "current_step": node_output.get("current_step"),
                        "trace": node_output.get("execution_trace", [])[-1] if node_output.get("execution_trace") else None
                    }
                    yield {
                        "event": "step",
                        "data": json.dumps(step_data)
                    }
                    await asyncio.sleep(0.05)

                    if node_name == "synthesizer" and node_output.get("final_response"):
                        yield {
                            "event": "final",
                            "data": json.dumps({
                                "final_response": node_output.get("final_response"),
                                "sql_query": accumulated_state.get("sql_query"),
                                "sql_results": accumulated_state.get("sql_results"),
                                "rag_results": accumulated_state.get("rag_results")
                            })
                        }
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)})
            }

    return EventSourceResponse(event_generator())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
