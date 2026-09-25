import os
import json
import re
from typing import Dict, Any, List
from dotenv import load_dotenv
from pathlib import Path
from sqlalchemy import MetaData, Table, create_engine, inspect, select
from backend.app.agent.state import AgentState
from backend.app.mcp.tools.sql_tool import DATABASE_URL, DB_PATH, execute_readonly_query
from backend.app.mcp.tools.rag_tool import search_policy_documents

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
ZERO_ROW_RETRY_MESSAGE = (
    "The query executed successfully but returned 0 results. Please review your string matching "
    "(case sensitivity) and numerical filters, rewrite the query, and try again."
)

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

def get_active_table_schema(tenant_id: str) -> str:
    table_name = os.getenv("CSV_TABLE_NAME", "business_data")
    database_url = DATABASE_URL or f"sqlite:///{DB_PATH}"
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
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
        metadata = MetaData()
        table = Table(table_name, metadata, schema=schema_name, autoload_with=engine)
        with engine.connect() as connection:
            sample_query = select(table).limit(3)
            if "tenant_id" in table.c:
                sample_query = select(table).where(table.c.tenant_id == tenant_id).limit(3)
            sample_rows = [
                dict(row)
                for row in connection.execute(sample_query).mappings().all()
            ]
        sample_text = json.dumps(sample_rows, indent=2, default=str)
        return (
            f"TABLE {qualified_name} (\n"
            + ",\n".join(column_lines)
            + f"\n)\n\nFIRST 3 ROWS (sample values):\n{sample_text}"
        )
    finally:
        engine.dispose()

def initialize_run_node(state: AgentState) -> Dict[str, Any]:
    return {
        "error_message": None,
        "retry_count": 0,
        "logical_retry_count": 0,
        "plan": [],
        "sql_query": None,
        "sql_results": None,
        "rag_query": None,
        "rag_results": None,
        "audit_findings": None,
        "executive_summary": "",
        "detailed_findings": "",
        "final_response": "",
        "current_step": "init",
        "execution_trace": [],
    }

def router_node(state: AgentState) -> Dict[str, Any]:
    assistant_history = [
        message for message in state.messages if message.get("role") == "assistant"
    ]
    if not assistant_history:
        return {"conversation_route": "new_audit", "current_step": "routing"}

    llm = get_llm()
    recent_history = "\n".join(
        f"{message.get('role', 'user')}: {message.get('content', '')}"
        for message in state.messages[-6:]
    )
    prompt = f"""Classify the current user message for an enterprise BI assistant.
Return exactly FOLLOW_UP if it asks a clarification, explanation, or question about existing data or the current audit report.
Return exactly NEW_AUDIT if it requests new data, calculations, metrics, or a different investigation.
Do not answer the user.

CONVERSATION:
{recent_history}

CURRENT USER MESSAGE:
{state.user_query}"""
    route = llm.invoke(prompt).content.strip().upper()
    return {
        "conversation_route": "follow_up" if "FOLLOW_UP" in route else "new_audit",
        "current_step": "routing",
    }

def parse_synthesis_response(response: str) -> tuple[str, str]:
    detailed_marker = "Detailed Findings"
    detailed_index = response.lower().find(detailed_marker.lower())
    if detailed_index < 0:
        return response.strip().replace("**", ""), ""
    executive = response[:detailed_index].strip()
    executive = executive.removeprefix("**Executive Summary**:").strip()
    executive = re.sub(r"(?m)^\s*\*\*\s*$", "", executive).strip().replace("**", "")
    detailed = response[detailed_index + len(detailed_marker):].strip()
    detailed = detailed.removeprefix("**:").strip()
    return executive, detailed

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
    schema = get_active_table_schema(state.tenant_id)
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
4. When filtering text columns in the WHERE clause, you MUST use the ILIKE operator instead of '=' to ensure case-insensitive matching.
5. You are generating SQL for PostgreSQL. You MUST wrap any column names that contain spaces or uppercase letters in double quotes (for example, "Order ID" or "Sales"). Never use square brackets.
6. Do not use placeholders, parameters, variables, or destructive SQL.
7. SQL GENERATION TEMPLATE:
You must strictly follow this template for aggregations. Do not add any extra arithmetic, constants, or multipliers.
Correct: SELECT SUM("Column Name") FROM table_name WHERE "Category" = 'Value';
INCORRECT: SELECT SUM("Column Name" * 8) FROM table_name;
Only output the raw, unmodified aggregate of the requested column.
8. Return ONLY executable SQL. Do not include markdown, backticks, or explanations."""

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

    logical_retry_count = state.logical_retry_count
    current_step = "sql_retry" if error_message else "sql_complete"
    if query_data and query_data.get("row_count") == 0 and logical_retry_count == 0:
        logical_retry_count += 1
        error_message = ZERO_ROW_RETRY_MESSAGE
        current_step = "sql_logical_retry"
        trace.append({"step": "sql_zero_rows", "message": ZERO_ROW_RETRY_MESSAGE})
    
    return {
        "sql_query": raw_sql,
        "sql_results": query_data,
        "error_message": error_message,
        "retry_count": next_retry_count,
        "logical_retry_count": logical_retry_count,
        "current_step": current_step,
        "execution_trace": trace
    }

def follow_up_chat_node(state: AgentState) -> Dict[str, Any]:
    trace = list(state.execution_trace)
    llm = get_llm()
    report = "\n\n".join(
        part for part in (state.executive_summary, state.detailed_findings) if part
    ) or state.final_response or "No audit report is available."
    prompt = f"""You are answering a follow-up question about an existing Enterprise BI audit.
Use only the current audit report, its database findings, and its retrieved policy context below.
Do not run SQL, invent new calculations, or introduce policies, thresholds, or facts that are not present in this context.

CURRENT AUDIT REPORT:
{report}

DATABASE FINDINGS:
{json.dumps(state.sql_results, indent=2) if state.sql_results else "No database findings available."}

RETRIEVED POLICY CONTEXT:
{json.dumps(state.rag_results, indent=2) if state.rag_results else "No policy context available."}

FOLLOW-UP QUESTION:
{state.user_query}

Answer directly and concisely."""
    response = llm.invoke(prompt).content
    messages = [*state.messages, {"role": "assistant", "content": response}]
    trace.append({"step": "follow_up", "message": "Answered from the current audit context without rerunning SQL."})
    original_summary = response.strip()
    cleaned_summary = re.sub(r'\*+', '', original_summary).strip()
    executive_summary = cleaned_summary
    detailed_findings = state.detailed_findings
    return {
        "final_response": response,
        "executive_summary": executive_summary,
        "detailed_findings": detailed_findings,
        "sql_query": state.sql_query,
        "sql_results": state.sql_results,
        "rag_results": state.rag_results,
        "messages": messages,
        "current_step": "done",
        "execution_trace": trace,
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
    
    prompt = f"""You are an Enterprise Business Intelligence analyst. Your job is to synthesize database results and corporate policy.

You must structure your response using exactly these two sections:
1. **Executive Summary**: A brief 1-3 sentence summary of the findings and a brief mention of the relevant policy rule.
2. **Detailed Findings**: A clear markdown table showing the exact numerical results derived from the database query.

CRITICAL CONSTRAINTS:
- ZERO MATH RULE: You are strictly forbidden from performing any mathematical calculations (e.g., calculating percentage differences, sums, or absolute differences). You must ONLY report the exact numbers provided to you in the database query results.
- CRITICAL RAG RULE: You are strictly forbidden from inventing numbers, tiers, or policies. Do not mention specific dollar amounts or tiers unless they are explicitly written in the provided RAG context text. Stick only to the provided facts.
- Do not guess the type of organization (e.g., do not say 'the university' or 'the hospital' unless explicitly named in the text). Refer to the source document exactly as it is titled or simply as 'the corporate policy'.
- STRICT GROUNDING RULE: You must ONLY reference policies, rules, or thresholds that are explicitly provided in the retrieved document context. NEVER invent, assume, or hallucinate external business rules, tier limits, or monetary thresholds. If the policy context does not mention a specific number, do not write one.
- DO NOT generate an 'Evidence' section.
- DO NOT generate an 'Interpretation' section.
- DO NOT generate 'Recommended Next Steps', 'Action Items', or any business advice.
- Stop generating text immediately after the Detailed Findings table.

User Question:
{state.user_query}

Retrieved Policy Terms (Contract Documentation):
{rag_text}

Database Query Results:
{sql_text}
"""

    response = llm.invoke(prompt)
    executive_summary, detailed_findings = parse_synthesis_response(response.content)
    original_summary = executive_summary
    cleaned_summary = re.sub(r'\*+', '', original_summary).strip()
    executive_summary = cleaned_summary
    final_response = "\n\n".join(
        part for part in (executive_summary, detailed_findings) if part
    )
    trace.append({"step": "synthesis", "message": "Final compliance audit generated successfully."})
    
    return {
        "final_response": final_response,
        "executive_summary": executive_summary,
        "detailed_findings": detailed_findings,
        "messages": [*state.messages, {"role": "assistant", "content": response.content}],
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
