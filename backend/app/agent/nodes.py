import os
import json
from typing import Dict, Any, List
from dotenv import load_dotenv
from pathlib import Path
from backend.app.agent.state import AgentState
from backend.app.mcp.tools.sql_tool import execute_readonly_query, get_database_schema
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

def planner_node(state: AgentState) -> Dict[str, Any]:
    trace = list(state.execution_trace)
    trace.append({"step": "planner", "message": "Analyzing question to determine structured and unstructured data requirements."})
    
    plan = [
        "Query customers and orders tables to retrieve order details and discount percentages.",
        "Retrieve partner agreement clauses regarding maximum allowable regional discounts.",
        "Cross-reference database records against contract policy to identify compliance violations."
    ]
    return {
        "plan": plan,
        "current_step": "planning_complete",
        "execution_trace": trace
    }

def sql_node(state: AgentState) -> Dict[str, Any]:
    trace = list(state.execution_trace)
    schema = get_database_schema()
    llm = get_llm()
    
    prompt = f"""You are a database analyst writing standard PostgreSQL queries.
DATABASE SCHEMA:
{schema}

USER QUESTION:
"{state.user_query}"

CRITICAL RULES:
1. Write a direct SELECT query joining `orders` and `customers`.
2. Do NOT use placeholders, colon parameters (like :cap), or variables.
3. Do NOT invent caps or filter discounts in SQL—retrieve all orders for the relevant region or customer so the audit layer can inspect the data.
4. Select columns: o.order_id, c.company_name, c.region, o.product_name, o.quantity, o.unit_price, o.discount_pct, o.order_date.
5. Return ONLY executable SQL. Do not include markdown code blocks, backticks, or explanations."""

    response = llm.invoke(prompt)
    raw_sql = response.content.strip().replace("```sql", "").replace("```", "").strip()
    
    trace.append({"step": "sql_execution", "sql_generated": raw_sql})
    query_data = execute_readonly_query(raw_sql)
    
    return {
        "sql_query": raw_sql,
        "sql_results": query_data,
        "current_step": "sql_complete",
        "execution_trace": trace
    }

def rag_node(state: AgentState) -> Dict[str, Any]:
    trace = list(state.execution_trace)
    llm = get_llm()
    
    prompt = f"""Formulate a concise semantic search query (3-6 words) to retrieve relevant contract policy rules from an enterprise partner agreement for this request:
User request: "{state.user_query}"
Return ONLY the search query string with no explanation."""

    response = llm.invoke(prompt)
    search_query = response.content.strip().strip('"')
    
    trace.append({"step": "rag_search", "rag_query": search_query})
    retrieved = search_policy_documents(search_query, top_k=2)
    
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
    
    prompt = f"""You are an Enterprise Business Intelligence Compliance Auditor.
Synthesize the structured SQL database findings with the retrieved legal policy documentation to address the user request.

User Question:
{state.user_query}

Retrieved Policy Terms (Contract Documentation):
{rag_text}

Database Query Results (Live Supabase Orders):
{sql_text}

Format your response professionally in clean Markdown:
1. **Executive Summary**: Explicitly state whether a compliance violation occurred.
2. **Audit Discrepancies**: Present a markdown table listing any orders that breached policy limits (Order ID, Company Name, Region, Granted Discount, Contract Cap, Over-the-Cap Variance).
3. **Contractual Basis**: Cite the document name/ID and specific section numbers governing this rule.
4. **Recommended Actions**: Clear next steps for finance and partner operations."""

    response = llm.invoke(prompt)
    trace.append({"step": "synthesis", "message": "Final compliance audit generated successfully."})
    
    return {
        "final_response": response.content,
        "current_step": "done",
        "execution_trace": trace
    }
