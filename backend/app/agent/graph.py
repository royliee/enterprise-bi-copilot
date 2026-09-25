from langgraph.graph import StateGraph, END
from backend.app.agent.state import AgentState
from backend.app.agent.nodes import planner_node, sql_node, rag_node, synthesizer_node, sql_failure_node

def build_bi_agent_graph():
    workflow = StateGraph(AgentState)

    # Register nodes
    workflow.add_node("planner", planner_node)
    workflow.add_node("sql_executor", sql_node)
    workflow.add_node("rag_executor", rag_node)
    workflow.add_node("synthesizer", synthesizer_node)
    workflow.add_node("sql_failure", sql_failure_node)

    # Set edge flow
    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "rag_executor")
    workflow.add_edge("rag_executor", "sql_executor")
    workflow.add_conditional_edges(
        "sql_executor",
        lambda state: "retry" if state.error_message and state.retry_count <= 3 else (
            "failed" if state.error_message else "success"
        ),
        {"retry": "sql_executor", "failed": "sql_failure", "success": "synthesizer"},
    )
    workflow.add_edge("sql_failure", END)
    workflow.add_edge("synthesizer", END)

    return workflow.compile()

bi_agent = build_bi_agent_graph()
