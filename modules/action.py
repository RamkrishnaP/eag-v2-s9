# modules/action.py

import asyncio
import json
import types
from typing import Any, Dict, Union

from pydantic import BaseModel

# Optional logging fallback
try:
    from agent import log
except ImportError:
    import datetime

    def log(stage: str, msg: str):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] [{stage}] {msg}")


class ToolCallResult(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    result: Union[str, list, dict]
    raw_response: Any


MAX_TOOL_CALLS_PER_PLAN = 5


async def run_python_sandbox(code: str, dispatcher: Any) -> str:
    print("[action] 🔍 Entered run_python_sandbox()")

    # Create a fresh module scope
    sandbox = types.ModuleType("sandbox")

    try:
        # Patch MCP client with real dispatcher
        class SandboxMCP:
            def __init__(self, dispatcher):
                self.dispatcher = dispatcher
                self.call_count = 0

            async def call_tool(self, tool_name: str, input_dict: dict):
                self.call_count += 1
                if self.call_count > MAX_TOOL_CALLS_PER_PLAN:
                    raise RuntimeError(
                        f"Exceeded max tool calls ({MAX_TOOL_CALLS_PER_PLAN}) in solve() plan."
                    )
                # REAL tool call now
                result = await self.dispatcher.call_tool(tool_name, input_dict)

                # Extract text content from MCP response object
                # MCP responses have format: CallToolResult(content=[TextContent(type='text', text='...')])
                if hasattr(result, "content") and result.content:
                    # Extract text from first content item
                    if isinstance(result.content, list) and len(result.content) > 0:
                        first_content = result.content[0]
                        if hasattr(first_content, "text"):
                            text_content = first_content.text

                            # Many MCP tools return JSON strings like '{"result": "..."}'
                            # Try to parse and extract the "result" field if present
                            try:
                                parsed = json.loads(text_content)
                                if isinstance(parsed, dict) and "result" in parsed:
                                    return parsed["result"]
                            except (json.JSONDecodeError, TypeError):
                                pass  # Not JSON, return as-is

                            return text_content

                # Fallback: return as-is if structure doesn't match expected format
                return result

        sandbox.mcp = SandboxMCP(dispatcher)

        # Preload safe built-ins into the sandbox
        import json
        import re

        sandbox.__dict__["json"] = json
        sandbox.__dict__["re"] = re

        # Execute solve fn dynamically
        exec(compile(code, "<solve_plan>", "exec"), sandbox.__dict__)

        solve_fn = sandbox.__dict__.get("solve")
        if solve_fn is None:
            raise ValueError("No solve() function found in plan.")

        if asyncio.iscoroutinefunction(solve_fn):
            result = await solve_fn()
        else:
            result = solve_fn()

        # Clean result formatting
        if isinstance(result, dict) and "result" in result:
            return f"{result['result']}"
        elif isinstance(result, dict):
            return f"{json.dumps(result)}"
        elif isinstance(result, list):
            return f"{' '.join(str(r) for r in result)}"
        else:
            return f"{result}"

    except Exception as e:
        log("sandbox", f"⚠️ Execution error: {e}")
        return f"[sandbox error: {str(e)}]"
