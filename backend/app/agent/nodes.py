import os
import json
from typing import Dict, Any, List
from dotenv import load_dotenv
from pathlib import Path
from sqlalchemy import create_engine, inspect
from backend.app.agent.state import AgentState
from backend.app.mcp.tools.sql_tool import DATABASE_URL, DB_PATH, execute_readonly_query
from backend.app.mcp.tools.rag_tool import search_policy_documents

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

def get_llm():
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "groq" and os.getenv("GROQ_API_KEY"):
        from langchain_groq import ChatGroq
        return ChatGroq(model_name=os.getenv("MODEL_NAME", "openai/gpt-oss-120b"), temperature=0.0)
    elif os.getenv("GEMINI_API_KEY"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.0)
    else:
        raise ValueError("Missing API key in .env (configure GROQ_API_KEY or GEMINI_API_KEY)")

def get_active_table_schema() -> str:
    table_name = os.getenv("CSV_TABLE_NAME", "business_data")
    database_url = DATABASE_URL or f"sqlite:///{DB_PATH}"
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        schema_name = "public" if database_url.startswith("postgresql") else None
        if not inspector.has_table(table_name, schema=schema_name):
            available_tables = inspector.get_table_names(schema=schema_name)
            return f"No active table named '{table_name}' was found. Available tables: {available_tables}"
        columns = inspector.get_columns(table_name, schema=schema_name)
        column_lines = [f"  {column['name']} {column['type']}" for column in columns]
        qualified_name = f"{schema_name}.{table_name}" if schema_name else table_name
        return f"TABLE {qualified_name} (\n" + ",\n".join(column_lines) + "\n)"
    finally:
        engine.dispose()

def planner_node(state: AgentState) -> Dict[str, Any]:
    trace = list(state.execution_trace)
    llm = get_llm()
    prompt = f"""You are planning a generic business intelligence investigation.
Create a short 3-step plan for answering the user's question using the uploaded structured data and relevant uploaded documents.
Do not assume any table names, column names, industries, regions, metrics, or business rules.
Derive all rules and thresholds only from the user's question and retrieved documents later in the pipeline.
Return one concise step per line and no numbering or explanation.

USER QUESTION:
{state.user_query}"""
    response = llm.invoke(prompt)
    plan = [line.strip(" -") for line in response.content.splitlines() if line.strip()][:3]
    trace.append({"step": "planner", "message": "Created a data-source-neutral investigation plan."})
    return {
        "plan": plan,
        "current_step": "planning_complete",
        "execution_trace": trace
    }

def sql_node(state: AgentState) -> Dict[str, Any]:
    trace = list(state.execution_trace)
    schema = get_active_table_schema()
    llm = get_llm()
    policy_context = "\n---\n".join(
        result["text"] for result in (state.rag_results or {}).get("results", [])
    ) or "No policy documents matched this request."
    retry_context = (
        f"PREVIOUS SQL ERROR (rewrite the query to fix it): {state.error_message}"
        if state.error_message
        else "No previous SQL attempt failed."
    )
    
    prompt = f"""You are a database analyst writing a standard PostgreSQL read-only query.
DATABASE SCHEMA:
{schema}

USER QUESTION:
"{state.user_query}"

RETRIEVED DOCUMENT CONTEXT:
{policy_context}

{retry_context}

CRITICAL RULES:
1. Use only tables and columns present in the schema. Do not invent identifiers.
2. Apply business filtering only when supported by the user's question or retrieved document context.
3. Every query MUST restrict rows to tenant_id = '{state.tenant_id}' or an equivalent tenant-safe JOIN condition.
4. Do not use placeholders, parameters, variables, or destructive SQL.
5. Return ONLY executable SQL. Do not include markdown, backticks, or explanations."""

    response = llm.invoke(prompt)
    raw_sql = response.content.strip().replace("```sql", "").replace("```", "").strip()
    
    trace.append({"step": "sql_execution", "sql_generated": raw_sql})
    if "tenant_id" not in raw_sql.lower():
        query_data = {"error": "Security violation: Generated SQL must include a tenant_id restriction"}
    else:
        query_data = execute_readonly_query(raw_sql)

    error_message = query_data.get("error") if query_data else None
    next_retry_count = state.retry_count + 1 if error_message else state.retry_count
    if error_message:
        trace.append({"step": "sql_error", "message": error_message, "retry_count": next_retry_count})
    
    return {
        "sql_query": raw_sql,
        "sql_results": query_data,
        "error_message": error_message,
        "retry_count": next_retry_count,
        "current_step": "sql_retry" if error_message else "sql_complete",
        "execution_trace": trace
    }

def rag_node(state: AgentState) -> Dict[str, Any]:
    trace = list(state.execution_trace)
    llm = get_llm()
    
    prompt = f"""Formulate a concise semantic search query (3-6 words) to retrieve relevant rules, definitions, constraints, or policies from the user's uploaded documents:
User request: "{state.user_query}"
Return ONLY the search query string with no explanation."""

    response = llm.invoke(prompt)
    search_query = response.content.strip().strip('"')
    
    trace.append({"step": "rag_search", "rag_query": search_query})
    retrieved = search_policy_documents(search_query, tenant_id=state.tenant_id, top_k=2)
    
    return {
        "rag_query": search_query,
        "rag_results": retrieved,
        "current_step": "rag_complete",
        "execution_trace": trace
    }

def synthesizer_node(state: AgentState) -> Dict[str, Any]:
    trace = list(state.execution_trace)
    llm = get_llm()
    
    sql_text = json.dumps(state.sql_results, indent=2) if state.sql_results else "No SQL data"
    rag_text = "\n---\n".join([r["text"] for r in state.rag_results.get("results", [])]) if state.rag_results else "No documents found"
    
    prompt = f"""You are an Enterprise Business Intelligence analyst.
Synthesize the structured data findings with relevant retrieved document evidence to address the user request.
Do not invent business rules, thresholds, fields, or conclusions. Clearly distinguish calculated findings from rules stated in the documents.

User Question:
{state.user_query}

Retrieved Policy Terms (Contract Documentation):
{rag_text}

Database Query Results:
{sql_text}

Format your response professionally in clean Markdown with an executive summary, relevant findings, evidence citations when available, and recommended next steps."""

    response = llm.invoke(prompt)
    trace.append({"step": "synthesis", "message": "Final compliance audit generated successfully."})
    
    return {
        "final_response": response.content,
        "current_step": "done",
        "execution_trace": trace
    }

def sql_failure_node(state: AgentState) -> Dict[str, Any]:
    trace = list(state.execution_trace)
    trace.append({"step": "sql_failed", "message": "SQL execution failed after the maximum retry count."})
    return {
        "final_response": (
            "The structured-data query could not be completed after "
            f"an initial attempt and {state.retry_count - 1} retries.\n\nError: {state.error_message}"
        ),
        "current_step": "failed",
        "execution_trace": trace,
    }
