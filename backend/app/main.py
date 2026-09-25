import json
import asyncio
import os
import re
from io import BytesIO
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import create_engine
from pypdf import PdfReader

from backend.app.agent.graph import bi_agent
from backend.app.agent.state import AgentState
from backend.app.mcp.tools.rag_tool import retriever

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


def require_tenant_id(x_tenant_id: str | None) -> str:
    tenant_id = x_tenant_id.strip() if x_tenant_id else ""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", tenant_id):
        raise HTTPException(status_code=400, detail="X-Tenant-ID contains invalid characters")
    return tenant_id

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Enterprise BI Copilot Backend"}

@app.post("/api/chat")
async def chat_endpoint(payload: QueryRequest, x_tenant_id: str | None = Header(default=None)):
    tenant_id = require_tenant_id(x_tenant_id)

    async def event_generator():
        initial_state = AgentState(user_query=payload.message, tenant_id=tenant_id)
        
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

                    if node_name in {"synthesizer", "sql_failure"} and node_output.get("final_response"):
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


@app.post("/api/upload/csv")
async def upload_csv(file: UploadFile = File(...), x_tenant_id: str | None = Header(default=None)):
    tenant_id = require_tenant_id(x_tenant_id)
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    database_url = os.getenv("DATABASE_URL")
    if not database_url or not database_url.startswith("postgresql"):
        raise HTTPException(status_code=503, detail="PostgreSQL DATABASE_URL is not configured")

    try:
        dataframe = pd.read_csv(BytesIO(await file.read()))
        dataframe["tenant_id"] = tenant_id
        engine = create_engine(database_url)
        table_name = os.getenv("CSV_TABLE_NAME", "business_data")
        dataframe.to_sql(table_name, engine, if_exists="append", index=False)
        engine.dispose()
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"CSV upload failed: {error}") from error

    return {"filename": file.filename, "tenant_id": tenant_id, "row_count": len(dataframe)}


@app.post("/api/upload/pdf")
async def upload_pdf(file: UploadFile = File(...), x_tenant_id: str | None = Header(default=None)):
    tenant_id = require_tenant_id(x_tenant_id)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    try:
        reader = PdfReader(BytesIO(await file.read()))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        chunks = [chunk.strip() for chunk in text.split("\n\n") if len(chunk.strip()) > 30]
        if not chunks and text.strip():
            chunks = [text.strip()]
        chunk_count = retriever.add_documents(chunks, tenant_id, Path(file.filename).stem)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"PDF upload failed: {error}") from error

    return {"filename": file.filename, "tenant_id": tenant_id, "chunk_count": chunk_count}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
