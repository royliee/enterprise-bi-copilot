from langgraph.graph import StateGraph, END
from backend.app.agent.state import AgentState
from backend.app.agent.nodes import planner_node, sql_node, rag_node, synthesizer_node

def build_bi_agent_graph():
    workflow = StateGraph(AgentState)

    # Register nodes
    workflow.add_node("planner", planner_node)
    workflow.add_node("sql_executor", sql_node)
    workflow.add_node("rag_executor", rag_node)
    workflow.add_node("synthesizer", synthesizer_node)

    # Set edge flow
    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "sql_executor")
    workflow.add_edge("sql_executor", "rag_executor")
    workflow.add_edge("rag_executor", "synthesizer")
    workflow.add_edge("synthesizer", END)

    return workflow.compile()

bi_agent = build_bi_agent_graph()
