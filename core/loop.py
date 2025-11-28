# modules/loop.py

import asyncio
import re

from core.context import AgentContext, ToolTrace
from core.session import MultiMCP
from core.strategy import select_decision_prompt_path
from modules.action import run_python_sandbox
from modules.decision import generate_plan
from modules.model_manager import ModelManager
from modules.perception import run_perception
from modules.tools import summarize_tools
from modules.heuristics import HeuristicsEngine

try:
    from agent import log
except ImportError:
    import datetime

    def log(stage: str, msg: str):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] [{stage}] {msg}")


class AgentLoop:
    def __init__(self, context: AgentContext):
        self.context = context
        self.mcp = self.context.dispatcher
        self.model = ModelManager()
        self.heuristics = HeuristicsEngine()

    async def _try_cached_answer(self):
        """
        Check if a highly similar past conversation exists and can be reused.
        Returns cached answer if similarity > 85% and the past query was successful.
        """
        try:
            # Search for similar conversations
            similar_convos = self.context.conversation_indexer.search_conversations(
                self.context.user_input, top_k=1
            )

            if not similar_convos:
                return None

            best_match = similar_convos[0]
            similarity = best_match.get("similarity_score", 0)

            # Only use cache if:
            # 1. Similarity is very high (>85%)
            # 2. The past conversation was successful
            # 3. There's a final answer available
            if (
                similarity > 0.85
                and best_match.get("success")
                and best_match.get("final_answer")
            ):
                log(
                    "loop",
                    f"📋 Found highly similar past query (similarity: {similarity:.1%})",
                )
                log("loop", f"   Past query: {best_match['initial_query']}")
                log("loop", f"   Past answer: {best_match['final_answer'][:100]}...")

                # Ask LLM if the cached answer is appropriate for current query
                validation_prompt = f"""You have two queries and a past answer. Determine if the past answer is appropriate for the current query.

PAST QUERY: {best_match["initial_query"]}
CURRENT QUERY: {self.context.user_input}
PAST ANSWER: {best_match["final_answer"]}

If the past answer fully addresses the current query, respond with:
REUSE: [the past answer]

If the queries are different enough that the past answer doesn't apply, respond with:
SEARCH_NEEDED

Your response:"""

                validation = await self.model.generate_text(validation_prompt)

                if validation.strip().startswith("REUSE:"):
                    cached_answer = validation.split("REUSE:", 1)[1].strip()
                    return f"FINAL_ANSWER: {cached_answer}"

            return None

        except Exception as e:
            log("loop", f"⚠️ Error checking cached answers: {e}")
            return None

    async def run(self):
        max_steps = self.context.agent_profile.strategy.max_steps
        allow_final_analysis = (
            False  # Flag to allow one extra iteration for data analysis
        )

        # 🧠 Check if we can use a cached answer from historical conversations
        if self.context.historical_context and self.context.conversation_indexer:
            cached_answer = await self._try_cached_answer()
            if cached_answer:
                log("loop", "✅ Using cached answer from similar past conversation")
                self.context.save_final_answer(cached_answer, success=True)
                return {"status": "done", "result": cached_answer}

        for step in range(max_steps):
            print(f"🔁 Step {step + 1}/{max_steps} starting...")

            self.context.step = step
            lifelines_left = self.context.agent_profile.strategy.max_lifelines_per_step

            while lifelines_left >= 0:
                # 0. Heuristics Check on Query
                query_warnings = self.heuristics.check_query(self.context.user_input)
                if query_warnings:
                    print(f"[heuristics] ⚠️ Query warnings: {query_warnings}")

                # === Perception ===
                user_input_override = getattr(self.context, "user_input_override", None)
                perception = await run_perception(
                    context=self.context,
                    user_input=user_input_override or self.context.user_input,
                )

                print(f"[perception] {perception}")

                selected_servers = perception.selected_servers
                selected_tools = self.mcp.get_tools_from_servers(selected_servers)
                if not selected_tools:
                    log("loop", "⚠️ No tools selected — aborting step.")
                    break

                # === Planning ===
                tool_descriptions = summarize_tools(selected_tools)
                prompt_path = select_decision_prompt_path(
                    planning_mode=self.context.agent_profile.strategy.planning_mode,
                    exploration_mode=self.context.agent_profile.strategy.exploration_mode,
                )

                # Use user_input_override if set, otherwise use original user_input
                planning_input = user_input_override or self.context.user_input

                plan = await generate_plan(
                    user_input=planning_input,
                    perception=perception,
                    memory_items=self.context.memory.get_session_items(),
                    tool_descriptions=tool_descriptions,
                    prompt_path=prompt_path,
                    step_num=step + 1,
                    max_steps=max_steps,
                    historical_context=self.context.historical_context,
                )
                print(f"[plan] {plan}")

                # === Execution ===
                if re.search(r"^\s*(async\s+)?def\s+solve\s*\(", plan, re.MULTILINE):
                    print("[loop] Detected solve() plan — running sandboxed...")

                    self.context.log_subtask(
                        tool_name="solve_sandbox", status="pending"
                    )
                    result = await run_python_sandbox(plan, dispatcher=self.mcp)

                    success = False
                    if isinstance(result, str):
                        result = result.strip()
                        if result.startswith("FINAL_ANSWER:"):
                            # Extract the answer content
                            answer_content = result.split("FINAL_ANSWER:", 1)[1].strip()

                            # Check if the "answer" is actually raw search results that need extraction
                            is_raw_search_results = (
                                "Found" in answer_content
                                and "search results" in answer_content
                            ) or (
                                "URL:" in answer_content
                                and "Summary:" in answer_content
                            )

                            if is_raw_search_results:
                                # Convert to FURTHER_PROCESSING_REQUIRED to trigger extraction
                                log(
                                    "loop",
                                    "🔍 Detected raw search results in FINAL_ANSWER - triggering extraction...",
                                )
                                result = (
                                    f"FURTHER_PROCESSING_REQUIRED: {answer_content}"
                                )
                                # Continue to FURTHER_PROCESSING_REQUIRED handler below
                            else:
                                # Clean final answer
                                success = True
                                self.context.final_answer = result
                                self.context.update_subtask_status(
                                    "solve_sandbox", "success"
                                )
                                self.context.memory.add_tool_output(
                                    tool_name="solve_sandbox",
                                    tool_args={"plan": plan},
                                    tool_result={"result": result},
                                    success=True,
                                    tags=["sandbox"],
                                )
                                self.context.save_final_answer(
                                    self.context.final_answer, success=True
                                )
                                return {
                                    "status": "done",
                                    "result": self.context.final_answer,
                                }

                        if result.startswith("FURTHER_PROCESSING_REQUIRED:"):
                            content = result.split("FURTHER_PROCESSING_REQUIRED:")[
                                1
                            ].strip()

                            # Check if content indicates an error or empty result
                            # Note: Ignore "Image file not found" as that's just missing images, not missing content
                            is_error_or_empty = (
                                content.startswith("ERROR:")
                                or (
                                    (
                                        "Failed to search:" in content
                                        or "Failed to fetch"
                                    )
                                    and len(content) < 200
                                )
                                or len(content.strip()) < 10
                            )

                            # Check if content is just search results (URLs/summaries) without actual detailed content
                            # Search results typically have "URL:" markers and summaries but not the full content
                            is_search_results_only = (
                                (
                                    "search results:" in content.lower()
                                    or "Found 5 search results" in content
                                )
                                and "URL:" in content
                                and "Summary:" in content
                            )

                            if is_error_or_empty:
                                # Data fetch failed, allow retry with different approach
                                self.context.user_input_override = (
                                    f"Original user task: {self.context.user_input}\n\n"
                                    f"Previous attempt failed with:\n{content}\n\n"
                                    f"Try a different approach to answer the user's question using a different FUNCTION_CALL."
                                )
                            elif is_search_results_only:
                                # We have search results with URLs, but need to fetch actual content from one of the URLs
                                self.context.user_input_override = (
                                    f"Original user task: {self.context.user_input}\n\n"
                                    f"You received these search results:\n{content}\n\n"
                                    f"The search results show URLs but not the actual content. "
                                    f"Use a tool to fetch the full content from one of the URLs above to get the actual answer. "
                                    f"For example, use 'convert_webpage_url_into_markdown' or similar tool to extract the content."
                                )
                            else:
                                # Data was successfully fetched, extract the answer directly using LLM
                                log(
                                    "loop",
                                    "🔍 Valid content detected - extracting answer directly...",
                                )

                                extraction_prompt = (
                                    f"TASK: Extract the answer to this question from the data below.\n\n"
                                    f"QUESTION: {self.context.user_input}\n\n"
                                    f"DATA:\n{content}\n\n"
                                    f"INSTRUCTIONS:\n"
                                    f"- Read the DATA carefully\n"
                                    f"- Extract the most relevant answer to the QUESTION\n"
                                    f"- Return your response in EXACTLY this format: FINAL_ANSWER: [your answer]\n"
                                    f"- Do NOT make any new tool calls\n"
                                    f"- Do NOT search for additional information\n"
                                    f"- Use ONLY the data provided above"
                                )

                                try:
                                    extracted_answer = await self.model.generate_text(
                                        extraction_prompt
                                    )
                                    # Ensure it starts with FINAL_ANSWER:
                                    if not extracted_answer.strip().startswith(
                                        "FINAL_ANSWER:"
                                    ):
                                        extracted_answer = (
                                            f"FINAL_ANSWER: {extracted_answer.strip()}"
                                        )

                                    self.context.final_answer = extracted_answer.strip()
                                    log(
                                        "loop",
                                        f"✅ Answer extracted: {self.context.final_answer}",
                                    )

                                    self.context.save_final_answer(
                                        self.context.final_answer, success=True
                                    )
                                    return {
                                        "status": "done",
                                        "result": self.context.final_answer,
                                    }
                                except Exception as e:
                                    log(
                                        "loop",
                                        f"⚠️ Direct extraction failed: {e}, falling back to normal flow",
                                    )
                                    # Fall back to setting user_input_override and continuing
                                    self.context.user_input_override = extraction_prompt

                            # Only log and continue if we didn't already return (error or search results case)
                            if (
                                hasattr(self.context, "user_input_override")
                                and self.context.user_input_override
                            ):
                                log(
                                    "loop",
                                    f"📨 Forwarding intermediate result to next step:\n{self.context.user_input_override}\n\n",
                                )
                                log(
                                    "loop",
                                    f"🔁 Continuing based on FURTHER_PROCESSING_REQUIRED — Step {step + 1} continues...",
                                )
                            # If this is the last step, set flag to allow final analysis
                            if step == max_steps - 1:
                                allow_final_analysis = True
                            # Break from lifelines loop and continue to next iteration
                            break
                        elif result.startswith("[sandbox error:"):
                            success = False
                            self.context.final_answer = (
                                "FINAL_ANSWER: [Execution failed]"
                            )
                        else:
                            success = True
                            self.context.final_answer = f"FINAL_ANSWER: {result}"
                    else:
                        self.context.final_answer = f"FINAL_ANSWER: {result}"

                    if success:
                        self.context.update_subtask_status("solve_sandbox", "success")
                    else:
                        self.context.update_subtask_status("solve_sandbox", "failure")

                    self.context.memory.add_tool_output(
                        tool_name="solve_sandbox",
                        tool_args={"plan": plan},
                        tool_result={"result": result},
                        success=success,
                        tags=["sandbox"],
                    )

                    self.context.tool_calls.append(
                        ToolTrace(
                            tool_name="solve_sandbox",
                            arguments={"plan": plan},
                            result=result,
                        )
                    )

                    # Heuristics Check on Result
                    result_warnings = self.heuristics.check_result(result)
                    if result_warnings:
                        print(f"[heuristics] ⚠️ Result warnings: {result_warnings}")

                    if success and "FURTHER_PROCESSING_REQUIRED:" not in result:
                        self.context.save_final_answer(
                            self.context.final_answer, success=True
                        )
                        return {"status": "done", "result": self.context.final_answer}
                    else:
                        lifelines_left -= 1
                        log("loop", f"🛠 Retrying... Lifelines left: {lifelines_left}")
                        continue
                else:
                    log(
                        "loop",
                        f"⚠️ Invalid plan detected — retrying... Lifelines left: {lifelines_left - 1}",
                    )
                    lifelines_left -= 1
                    continue

        # If we have data to analyze after max_steps, do one final analysis
        if (
            allow_final_analysis
            and hasattr(self.context, "user_input_override")
            and self.context.user_input_override
        ):
            log("loop", "🔍 Performing final data analysis...")
            print(f"🔁 Final analysis step (analyzing fetched data)...")

            # Use ModelManager to directly analyze the data without planning phase
            # This prevents the LLM from trying to fetch more data
            analysis_prompt = f"""You have already fetched data to answer this question: {self.context.user_input}

Here is the data you fetched:
{self.context.user_input_override}

Analyze this data carefully and provide a concise answer to the question.
Return your response in EXACTLY this format:
FINAL_ANSWER: [your concise answer based on the data above]

Do NOT say you need more information or suggest calling more tools. Use ONLY the data provided above."""

            try:
                analysis_result = await self.model.generate_text(analysis_prompt)
                # Ensure it starts with FINAL_ANSWER:
                if not analysis_result.strip().startswith("FINAL_ANSWER:"):
                    analysis_result = f"FINAL_ANSWER: {analysis_result.strip()}"
                self.context.final_answer = analysis_result.strip()
                self.context.save_final_answer(self.context.final_answer, success=True)
                return {"status": "done", "result": self.context.final_answer}
            except Exception as e:
                log("loop", f"⚠️ Final analysis failed: {e}")
                # Fallback: Return a generic answer
                self.context.final_answer = "FINAL_ANSWER: Analysis could not be completed. Please review the fetched data manually."
                self.context.save_final_answer(self.context.final_answer, success=False)
                return {"status": "done", "result": self.context.final_answer}

        log("loop", "⚠️ Max steps reached without finding final answer.")
        self.context.final_answer = "FINAL_ANSWER: [Max steps reached]"
        self.context.save_final_answer(self.context.final_answer, success=False)
        return {"status": "done", "result": self.context.final_answer}
