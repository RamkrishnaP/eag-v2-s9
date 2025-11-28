# core/context.py

import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel

from core.session import MultiMCP  # For dispatcher typing
from modules.memory import MemoryItem, MemoryManager

# Import conversation indexer (try simple version first, then full version)
try:
    from modules.conversation_indexer_simple import ConversationIndexer

    CONVERSATION_INDEXER_AVAILABLE = True
except ImportError:
    try:
        from modules.conversation_indexer import ConversationIndexer

        CONVERSATION_INDEXER_AVAILABLE = True
    except ImportError:
        CONVERSATION_INDEXER_AVAILABLE = False
        ConversationIndexer = None


class StrategyProfile(BaseModel):
    planning_mode: str
    exploration_mode: Optional[str] = None
    memory_fallback_enabled: bool
    max_steps: int
    max_lifelines_per_step: int


class AgentProfile:
    def __init__(self):
        with open("config/profiles.yaml", "r") as f:
            config = yaml.safe_load(f)

        self.name = config["agent"]["name"]
        self.id = config["agent"]["id"]
        self.description = config["agent"]["description"]

        self.strategy = StrategyProfile(**config["strategy"])
        self.memory_config = config["memory"]
        self.llm_config = config["llm"]
        self.persona = config["persona"]

    def __repr__(self):
        return f"<AgentProfile {self.name} ({self.strategy})>"


class ToolTrace:
    def __init__(self, tool_name: str, arguments: dict, result: Any):
        self.tool_name = tool_name
        self.arguments = arguments
        self.result = result


class AgentContext:
    """Holds all session state, user input, memory, and strategies."""

    def __init__(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        dispatcher: Optional[MultiMCP] = None,
        mcp_server_descriptions: Optional[List[Any]] = None,
        use_conversation_history: bool = True,
    ):
        if session_id is None:
            today = datetime.now()
            ts = int(time.time())
            uid = uuid.uuid4().hex[:6]
            session_id = (
                f"{today.year}/{today.month:02}/{today.day:02}/session-{ts}-{uid}"
            )

        self.user_input = user_input
        self.agent_profile = AgentProfile()
        self.memory = MemoryManager(session_id=session_id)
        self.session_id = self.memory.session_id
        self.dispatcher = dispatcher  # 🆕 Added formally
        self.mcp_server_descriptions = mcp_server_descriptions  # 🆕 Added formally
        self.step = 0
        self.task_progress = []  # 🆕 Will track tool executions
        self.tool_calls: List[ToolTrace] = []  # 🆕 Track tool calls for history
        self.final_answer = None

        # 🧠 Initialize conversation indexer and get historical context
        self.conversation_indexer = None
        self.historical_context = None
        if use_conversation_history and CONVERSATION_INDEXER_AVAILABLE:
            try:
                self.conversation_indexer = ConversationIndexer()
                # Index conversations in background (only new ones)
                self.conversation_indexer.index_conversations()
                # Get relevant historical context for current query
                self.historical_context = (
                    self.conversation_indexer.get_relevant_context(
                        user_input,
                        top_k=3,  # Get top 3 most relevant past conversations
                    )
                )
            except Exception as e:
                print(f"[context] ⚠️ Failed to load conversation history: {e}")
                self.historical_context = None

        # Log session start
        self.add_memory(
            MemoryItem(
                timestamp=time.time(),
                text=f"Started new session with input: {user_input} at {datetime.utcnow().isoformat()}",
                type="run_metadata",
                session_id=self.session_id,
                tags=["run_start"],
                user_query=user_input,
                metadata={
                    "start_time": datetime.now().isoformat(),
                    "step": self.step,
                    "has_historical_context": self.historical_context is not None,
                },
            )
        )

    def add_memory(self, item: MemoryItem):
        """Add item to memory"""
        self.memory.add(item)

    def save_final_answer(self, final_answer: str, success: bool = True):
        """Save the final answer to memory for indexing"""
        self.add_memory(
            MemoryItem(
                timestamp=time.time(),
                text=final_answer,
                type="final_answer",
                session_id=self.session_id,
                final_answer=final_answer,
                tags=["run_end", "final"],
                success=success,
                metadata={
                    "end_time": datetime.now().isoformat(),
                    "step": self.step,
                    "total_tool_calls": len(self.tool_calls),
                },
            )
        )

    def format_history_for_llm(self) -> str:
        if not self.tool_calls:
            return "No previous actions"

        history = []
        for i, trace in enumerate(self.tool_calls, 1):
            result_str = str(trace.result)
            if i < len(self.tool_calls):  # Previous steps
                if len(result_str) > 50:
                    result_str = f"{result_str[:50]}... [RESPONSE TRUNCATED]"
            # else: last step gets full result

            history.append(
                f"{i}. Used {trace.tool_name} with {trace.arguments}\nResult: {result_str}"
            )

        return "\n\n".join(history)

    def log_subtask(self, tool_name: str, status: str = "pending"):
        """Log the start of a new subtask."""
        self.task_progress.append(
            {
                "step": self.step,
                "tool": tool_name,
                "status": status,
            }
        )

    def update_subtask_status(self, tool_name: str, status: str):
        """Update the status of an existing subtask."""
        for item in reversed(self.task_progress):
            if item["tool"] == tool_name and item["step"] == self.step:
                item["status"] = status
                break

    def __repr__(self):
        return f"<AgentContext step={self.step}, session_id={self.session_id}>"
