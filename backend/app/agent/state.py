from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class AgentState(BaseModel):
    user_query: str
    tenant_id: str
    plan: List[str] = Field(default_factory=list)
    sql_query: Optional[str] = None
    sql_results: Optional[Dict[str, Any]] = None
    rag_query: Optional[str] = None
    rag_results: Optional[Dict[str, Any]] = None
    audit_findings: Optional[str] = None
    final_response: str = ""
    current_step: str = "init"
    execution_trace: List[Dict[str, Any]] = Field(default_factory=list)
