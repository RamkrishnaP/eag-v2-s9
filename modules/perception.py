# modules/perception.py

from typing import List, Optional
from pydantic import BaseModel
from modules.model_manager import ModelManager
from modules.tools import load_prompt, extract_json_block
from core.context import AgentContext

import json


# Optional logging fallback
try:
    from agent import log
except ImportError:
    import datetime
    def log(stage: str, msg: str):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] [{stage}] {msg}")

model = ModelManager()


prompt_path = "prompts/perception_prompt.txt"

class PerceptionResult(BaseModel):
    intent: str
    entities: List[str] = []
    tool_hint: Optional[str] = None
    tags: List[str] = []
    selected_servers: List[str] = []  # 🆕 NEW field

async def extract_perception(user_input: str, mcp_server_descriptions: dict, history: str = "") -> PerceptionResult:
    """
    Extracts perception details and selects relevant MCP servers based on the user query.
    """

    server_list = []
    for server_id, server_info in mcp_server_descriptions.items():
        description = server_info.get("description", "No description available")
        server_list.append(f"- {server_id}: {description}")

    servers_text = "\n".join(server_list)

    prompt_template = load_prompt(prompt_path)
    

    prompt = prompt_template.format(
        servers_text=servers_text,
        user_input=user_input,
        history=history
    )
    

    try:
        raw = await model.generate_text(prompt)
        raw = raw.strip()
        log("perception", f"Raw output: {raw}")

        # Try parsing into PerceptionResult
        json_block = extract_json_block(raw)
        result = json.loads(json_block)

        # If selected_servers missing, fallback
        if "selected_servers" not in result:
            result["selected_servers"] = list(mcp_server_descriptions.keys())
        print("result", result)

        return PerceptionResult(**result)

    except Exception as e:
        log("perception", f"⚠️ Perception failed: {e}")
        # Fallback: select all servers
        return PerceptionResult(
            intent="unknown",
            entities=[],
            tool_hint=None,
            tags=[],
            selected_servers=list(mcp_server_descriptions.keys())
        )


async def run_perception(context: AgentContext, user_input: Optional[str] = None):

    """
    Clean wrapper to call perception from context.
    """
    # Construct history string
    history_lines = []
    # Get last 10 items to ensure we capture enough context
    items = context.memory.get_session_items()[-10:]
    
    for item in items:
        if item.type == "run_metadata" and item.user_query:
            history_lines.append(f"User: {item.user_query}")
        elif item.type == "final_answer" and item.final_answer:
            # Truncate long answers
            ans = item.final_answer
            if len(ans) > 200:
                ans = ans[:200] + "..."
            history_lines.append(f"Agent: {ans}")
            
    history_str = "\n".join(history_lines) if history_lines else "No previous conversation."

    return await extract_perception(
        user_input = user_input or context.user_input,
        mcp_server_descriptions=context.mcp_server_descriptions,
        history=history_str
    )

