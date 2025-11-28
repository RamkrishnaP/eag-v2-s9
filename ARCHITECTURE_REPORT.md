# CORTEX-R AGENT: TECHNICAL ARCHITECTURE REPORT

**Project:** Cortex-R - Reasoning-Driven AI Agent Framework  
**Version:** 0.1.0  
**Agent ID:** cortex_r_002  
**Report Date:** 2025-11-28

---

## EXECUTIVE SUMMARY

Cortex-R is a sophisticated AI agent framework implementing a cognitive architecture pattern (Perception → Decision → Action) with multi-tool orchestration capabilities. The system uses the Model Context Protocol (MCP) to manage distributed tool servers, employs strategic planning mechanisms, and maintains persistent memory with semantic search capabilities.

**Key Capabilities:**
- Multi-step reasoning with configurable retry mechanisms
- Distributed tool management via MCP protocol
- Dual planning strategies (conservative and exploratory)
- Persistent session memory with FAISS-based semantic retrieval
- Multimodal document processing with AI-powered image captioning
- Sandboxed Python code execution for safe tool orchestration
- Support for multiple LLM backends (Gemini, Ollama)

---

## 1. SYSTEM ARCHITECTURE OVERVIEW

### 1.1 Design Philosophy

The architecture follows three core principles:

1. **Cognitive Loop Pattern:** Mimics human problem-solving with distinct perception, decision, and action phases
2. **Tool Abstraction:** MCP protocol provides standardized interface to heterogeneous tool servers
3. **Stateless Resilience:** Servers reconnect per-call, eliminating persistent connection failures

### 1.2 Architecture Layers

```
┌─────────────────────────────────────────────────────┐
│                   User Interface                     │
│                    (agent.py)                        │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                   Core Layer                         │
│  ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌─────────┐ │
│  │ Context  │ │   Loop   │ │ MultiMCP│ │Strategy │ │
│  └──────────┘ └──────────┘ └─────────┘ └─────────┘ │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│               Processing Modules                     │
│  ┌──────────┐ ┌─────────┐ ┌────────┐ ┌──────────┐  │
│  │Perception│ │Decision │ │ Action │ │  Memory  │  │
│  └──────────┘ └─────────┘ └────────┘ └──────────┘  │
│  ┌──────────┐ ┌─────────┐                           │
│  │  Model   │ │  Tools  │                           │
│  │ Manager  │ │  Utils  │                           │
│  └──────────┘ └─────────┘                           │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                  MCP Tool Servers                    │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────┐ │
│  │Math Server   │ │Docs Server   │ │Web Server   │ │
│  │(17 tools)    │ │(3 tools)     │ │(2 tools)    │ │
│  └──────────────┘ └──────────────┘ └─────────────┘ │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              Storage & External Services             │
│  ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌─────────┐ │
│  │Memory DB │ │  FAISS   │ │Documents│ │ Gemini/ │ │
│  │  (JSON)  │ │  Index   │ │  Store  │ │ Ollama  │ │
│  └──────────┘ └──────────┘ └─────────┘ └─────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## 2. CORE COMPONENTS

### 2.1 Entry Point (agent.py)

**Purpose:** Main application controller and REPL interface

**Key Responsibilities:**
- Load configuration from `config/profiles.yaml`
- Initialize MultiMCP dispatcher with all registered servers
- Manage interactive session lifecycle
- Process user queries through AgentLoop
- Handle response types (FINAL_ANSWER vs FURTHER_PROCESSING_REQUIRED)
- Graceful error handling and shutdown

**Session Management:**
- Sessions persist across queries until `new` command
- Session IDs follow format: `YYYY/MM/DD/session-{timestamp}-{uuid}`
- Memory automatically restored from previous sessions

**Control Flow:**
```python
while True:
    user_input → AgentContext → AgentLoop.run()
    
    if result contains "FINAL_ANSWER:":
        display result → await next query
    
    elif result contains "FURTHER_PROCESSING_REQUIRED:":
        update context → re-run AgentLoop
    
    else:
        display raw result
```

---

### 2.2 Core Layer

#### 2.2.1 AgentContext (core/context.py)

**Purpose:** Central state management hub

**AgentProfile Class:**
- Parses `config/profiles.yaml` on initialization
- Loads strategy configuration (planning mode, max steps, lifelines)
- Configures memory settings (persistence, summarization, tagging)
- Sets LLM backend (text generation, embeddings)
- Defines persona (tone, verbosity, behavior tags)

**AgentContext Class:**
- **State Management:**
  - Stores current user input and step number
  - Maintains reference to MultiMCP dispatcher
  - Holds MCP server descriptions for perception
  - Tracks task progress and subtask statuses
  
- **Memory Integration:**
  - Instantiates MemoryManager with session ID
  - Logs session start metadata
  - Provides convenience methods for memory operations
  
- **Session Lifecycle:**
  - Generates unique date-based session identifiers
  - Supports session continuation across queries
  - Tracks final answer state

**Key Methods:**
- `add_memory()`: Store memory items
- `log_subtask()`: Begin tracking tool execution
- `update_subtask_status()`: Mark tool success/failure

---

#### 2.2.2 AgentLoop (core/loop.py)

**Purpose:** Main execution engine implementing cognitive loop

**Configuration:**
- Max steps: 3 (configurable via profiles.yaml)
- Lifelines per step: 3 (retry attempts)
- Step-based iteration with fallback mechanisms

**Execution Phases:**

**Phase 1: Perception**
- Calls `run_perception()` with user input or override
- Extracts intent, entities, tool hints, and selected servers
- Logs perception results

**Phase 2: Tool Selection**
- Fetches tools only from servers selected by perception
- Aborts step if no tools available
- Generates tool descriptions for planning

**Phase 3: Planning**
- Selects decision prompt based on strategy (conservative/exploratory)
- Calls `generate_plan()` with:
  - User input
  - Perception results
  - Memory items from current session
  - Tool descriptions
  - Step metadata
- Receives `async def solve()` function as string

**Phase 4: Execution**
- Validates plan contains `solve()` function signature
- Invokes `run_python_sandbox()` with plan code
- Parses sandbox output for control keywords:
  - **FINAL_ANSWER:** Task complete, return to user
  - **FURTHER_PROCESSING_REQUIRED:** Intermediate result, continue loop
  - **[sandbox error:]:** Execution failed, consume lifeline and retry

**Phase 5: Memory Logging**
- Records tool execution in memory
- Updates subtask status (pending → success/failure)
- Stores tool arguments and results with success flag

**Retry Logic:**
- Each step has 3 lifelines
- Lifeline consumed on:
  - Sandbox execution errors
  - Invalid plan generation
  - Tool call failures
- After exhausting lifelines, advances to next step

**Termination Conditions:**
- **Success:** FINAL_ANSWER received
- **Continuation:** FURTHER_PROCESSING_REQUIRED (updates context and re-runs)
- **Failure:** Max steps reached without resolution

---

#### 2.2.3 MultiMCP (core/session.py)

**Purpose:** Stateless multi-server MCP dispatcher

**Architecture:**
- Stateless design: no persistent connections
- Each tool call spawns fresh subprocess
- Maps tools to their originating servers

**Data Structures:**
- `tool_map`: `{tool_name → {config, tool}}`
- `server_tools`: `{server_id → [tool_list]}`

**Initialization Process:**
```python
for each server_config:
    spawn subprocess with StdioServerParameters
    create ClientSession
    list_tools()
    populate tool_map and server_tools
    close session
```

**Tool Execution:**
```python
call_tool(tool_name, arguments):
    lookup tool in tool_map
    get server config
    spawn fresh subprocess
    create ClientSession
    execute tool call
    return result
    close session
```

**Benefits:**
- No connection state to manage
- Automatic recovery from server crashes
- Parallel execution possible (independent subprocesses)

**Methods:**
- `initialize()`: Discover all tools from all servers
- `call_tool()`: Route tool call to appropriate server
- `get_tools_from_servers()`: Filter tools by server IDs
- `list_all_tools()`: Return all available tool names
- `get_all_tools()`: Return all tool objects

---

#### 2.2.4 Strategy System (core/strategy.py)

**Purpose:** Adaptive planning strategy selection

**Strategy Types:**

**Conservative Mode:**
- Plans exactly 1 tool call per step
- Uses filtered tools from perception
- Fallback to all tools if filter yields nothing
- Direct, focused approach for clear tasks

**Exploratory Mode - Parallel:**
- Plans multiple independent tool calls
- Executes all in parallel
- Aggregates results
- Best for tasks requiring diverse data sources

**Exploratory Mode - Sequential:**
- Plans chain of tools with fallback logic
- Try primary tool → if fails, try secondary
- Preserves intermediate results
- Best for tasks with uncertain paths

**Memory Fallback Mechanism:**
- Enabled when `memory_fallback_enabled: true`
- On replanning (after failure):
  - Searches memory for recently successful tools
  - Retrieves last 5 successful tool names
  - Filters available tools to this subset
  - Generates new plan with proven tools

**Prompt Selection:**
- Maps strategy to appropriate prompt template:
  - Conservative → `decision_prompt_conservative.txt`
  - Exploratory+Parallel → `decision_prompt_exploratory_parallel.txt`
  - Exploratory+Sequential → `decision_prompt_exploratory_sequential.txt`

**Key Functions:**
- `select_decision_prompt_path()`: Choose prompt based on strategy
- `conservative_plan()`: Single-tool planning
- `exploratory_plan()`: Multi-tool planning with fallbacks
- `generate_plan()`: LLM-based plan generation
- `find_recent_successful_tools()`: Memory search for successful tools

---

## 3. PROCESSING MODULES

### 3.1 Perception Module (modules/perception.py)

**Purpose:** Analyze user intent and select relevant servers

**Input:**
- User query string
- MCP server descriptions dict

**Processing:**
1. Build server catalog text from descriptions
2. Load `perception_prompt.txt` template
3. Inject server catalog and user query
4. Call LLM via ModelManager
5. Parse JSON response

**Output (PerceptionResult):**
- `intent`: User's goal (e.g., "calculate", "search", "extract")
- `entities`: Key information (names, numbers, URLs, concepts)
- `tool_hint`: Suggested tool name (optional)
- `selected_servers`: Array of relevant server IDs
- `tags`: Categorization labels

**Error Handling:**
- If JSON parsing fails, selects all servers (safe fallback)
- Logs perception errors to stderr
- Never blocks execution due to perception failure

**Usage Example:**
```
User Query: "Find the square root of 144"
Output:
{
  "intent": "mathematical calculation",
  "entities": ["144", "square root"],
  "tool_hint": "sqrt",
  "selected_servers": ["math"]
}
```

---

### 3.2 Decision Module (modules/decision.py)

**Purpose:** Generate executable Python plan (solve function)

**Input:**
- User input
- Perception results
- Memory items from session
- Tool descriptions
- Prompt template path
- Step metadata

**Processing:**
1. Format memory items as bullet list
2. Load prompt template
3. Inject tool descriptions and user input
4. Call LLM to generate plan
5. Strip code fences (```python)
6. Validate presence of `async def solve()`

**Output:**
- Valid Python function string
- OR `FINAL_ANSWER: [error message]`

**Plan Structure:**
```python
import json

async def solve():
    # FUNCTION_CALL: 1
    """Tool docstring..."""
    input = {"input": {...}}
    result = await mcp.call_tool('tool_name', input)
    parsed = json.loads(result.content[0].text)["result"]
    
    # FUNCTION_CALL: 2 (if needed)
    """Next tool docstring..."""
    input = {"input": {"data": parsed}}
    result2 = await mcp.call_tool('tool2', input)
    final = json.loads(result2.content[0].text)["result"]
    
    # FINAL RESULT
    return f"FINAL_ANSWER: {final}"
```

**Validation:**
- Checks for `async def solve()` or `def solve()` signature
- Rejects plans without valid function definition
- Logs plan generation to stderr

---

### 3.3 Action Module (modules/action.py)

**Purpose:** Safe execution of generated Python plans

**Sandbox Environment:**
- Isolated module namespace (`types.ModuleType`)
- Preloaded safe modules: `json`, `re`
- Custom MCP client with call limiting

**SandboxMCP Class:**
- Wraps real MultiMCP dispatcher
- Tracks call count per execution
- Enforces max limit (5 calls)
- Prevents infinite loops and resource exhaustion

**Execution Flow:**
1. Create fresh module scope
2. Inject SandboxMCP instance as `mcp`
3. Compile plan code
4. Execute with `exec()`
5. Extract `solve()` function
6. Detect if async or sync
7. Call function appropriately
8. Parse and format result

**Result Formatting:**
- Dict with "result" key → Extract value
- Generic dict → JSON stringify
- List → Join as space-separated string
- Other types → String conversion

**Error Handling:**
- Catches all exceptions
- Returns `[sandbox error: {message}]`
- Prevents sandbox escape
- Logs errors to stderr

**Security Features:**
- No access to file system (except via tools)
- No network access (except via tools)
- No subprocess spawning
- Limited to provided built-ins

---

### 3.4 Memory Module (modules/memory.py)

**Purpose:** Persistent session storage and retrieval

**MemoryItem Model (Pydantic):**
```python
{
    "timestamp": float,           # Unix timestamp
    "type": str,                  # run_metadata | tool_call | tool_output | final_answer
    "text": str,                  # Human-readable description
    "tool_name": Optional[str],   # Tool identifier
    "tool_args": Optional[dict],  # Tool input
    "tool_result": Optional[dict],# Tool output
    "final_answer": Optional[str],# Final response
    "success": Optional[bool],    # Execution outcome
    "tags": List[str],            # Categorization
    "metadata": dict              # Additional context
}
```

**MemoryManager Class:**

**Initialization:**
- Accepts session ID and memory directory
- Computes file path: `memory/YYYY/MM/DD/session-{id}.json`
- Loads existing memory if file exists
- Initializes empty list otherwise

**Persistence:**
- Immediate write on every `add()` call
- Creates directory structure if missing
- JSON serialization with indentation
- Atomic writes (no partial data)

**Storage Structure:**
```
memory/
  2025/
    11/
      28/
        session-1732823456-a1b2c3.json
        session-1732825678-d4e5f6.json
```

**Key Methods:**
- `load()`: Read from disk into memory
- `save()`: Write to disk
- `add()`: Append item and save
- `add_tool_call()`: Log tool invocation
- `add_tool_output()`: Log tool result with success flag
- `add_final_answer()`: Store final response
- `find_recent_successes()`: Backward search for successful tools (returns last 5)
- `add_tool_success()`: Retroactively mark tool success
- `get_session_items()`: Return all items

**Use Cases:**
- Context preservation across queries
- Strategy learning (memory fallback)
- Debugging and auditing
- Session replay

---

### 3.5 Model Manager (modules/model_manager.py)

**Purpose:** Unified LLM backend abstraction

**Supported Backends:**
- **Gemini API** (Google GenAI)
- **Ollama** (local models)

**Initialization:**
1. Load `config/models.json` (backend definitions)
2. Load `config/profiles.yaml` (active model selection)
3. Extract text generation model key
4. Determine backend type
5. Initialize client

**Gemini Setup:**
- Reads `GEMINI_API_KEY` from environment variables
- Creates `genai.Client` instance
- Uses model from config (e.g., "gemini-1.5-pro")

**Ollama Setup:**
- Reads API endpoint from config (default: `http://localhost:11434`)
- No authentication required (local service)
- Supports models: phi4, gemma3:12b, qwen2.5:32b-instruct

**generate_text() Method:**
- Accepts prompt string
- Routes to appropriate backend
- Returns stripped text response

**Backend Implementations:**

**_gemini_generate():**
```python
response = client.models.generate_content(model=model, contents=prompt)
# Safe extraction handling multiple response formats
return response.text.strip()
```

**_ollama_generate():**
```python
response = requests.post(url, json={
    "model": model,
    "prompt": prompt,
    "stream": False
})
return response.json()["response"].strip()
```

**Error Handling:**
- Raises NotImplementedError for unsupported backends
- Propagates API errors to caller
- Logs failures to stderr

---

### 3.6 Tools Utilities (modules/tools.py)

**Purpose:** Helper functions for tool management

**Key Functions:**

**extract_json_block():**
- Regex search for ```json...``` code blocks
- Extracts JSON content
- Fallback to full text if no block found
- Used for parsing LLM responses

**summarize_tools():**
- Converts tool list to formatted string
- Template: `- {tool_name}: {description}`
- Used in decision prompts

**filter_tools_by_hint():**
- Accepts tools list and hint string
- Case-insensitive substring matching
- Returns filtered subset or all tools if no matches
- Used by perception module

**get_tool_map():**
- Converts list to dict: `{name → tool}`
- Fast lookup by name

**load_prompt():**
- Reads template file from disk
- Returns full text content
- Used by perception and decision modules

---

## 4. MCP TOOL SERVERS

### 4.1 Math Server (mcp_server_1.py)

**Server ID:** `math`  
**Framework:** FastMCP  
**Transport:** stdio  
**Tool Count:** 17

**Tool Categories:**

**Basic Arithmetic:**
- `add(a, b)` → a + b
- `subtract(a, b)` → a - b
- `multiply(a, b)` → a × b
- `divide(a, b)` → a ÷ b

**Advanced Math:**
- `power(a, b)` → a^b
- `cbrt(a)` → ∛a (cube root)
- `factorial(a)` → a!
- `remainder(a, b)` → a mod b

**Trigonometry:**
- `sin(a)` → sine (radians)
- `cos(a)` → cosine (radians)
- `tan(a)` → tangent (radians)

**String Operations:**
- `strings_to_chars_to_int(string)` → Converts each char to ASCII value
  - Example: "INDIA" → [73, 78, 68, 73, 65]

**List Operations:**
- `int_list_to_exponential_sum(numbers)` → Σ(e^x) for each x
  - Example: [1, 2, 3] → e^1 + e^2 + e^3 = 30.19
- `fibonacci_numbers(n)` → First n Fibonacci numbers
  - Example: n=7 → [0, 1, 1, 2, 3, 5, 8]

**Image Processing:**
- `create_thumbnail(image_path)` → Resize to 100x100 PNG

**Special:**
- `mine(a, b)` → Custom operation: a - b - b

**Input/Output Models:**
- All tools use Pydantic models from `models.py`
- Strict type validation
- Consistent structure: `{Input, Output}` pairs

**Usage Example:**
```python
# Tool docstring
"""Add two numbers. Usage: input={"input": {"a": 1, "b": 2}}"""
input = {"input": {"a": 5, "b": 3}}
result = await mcp.call_tool('add', input)
# result.content[0].text = '{"result": 8}'
```

---

### 4.2 Documents Server (mcp_server_2.py)

**Server ID:** `documents`  
**Framework:** FastMCP  
**Transport:** stdio  
**Tool Count:** 3

**Core Tools:**

#### 4.2.1 search_stored_documents(query)

**Purpose:** Semantic search over document corpus

**Process:**
1. Ensure FAISS index exists (triggers indexing if missing)
2. Generate query embedding via Ollama (nomic-embed-text)
3. Search FAISS index for top-5 similar chunks
4. Retrieve metadata for matched chunks
5. Format results with source attribution

**Output Example:**
```
[
  "Anmol Singh paid $2.5M for his DLF apartment via Capbridge.\n[Source: dlf.md, ID: dlf_3]",
  "Capbridge facilitated the transaction in Q2 2024.\n[Source: dlf.md, ID: dlf_7]"
]
```

**Automatic Indexing:**
- Checks for `faiss_index/index.bin` and `metadata.json`
- If missing, calls `process_documents()`
- Runs on first search query

---

#### 4.2.2 convert_webpage_url_into_markdown(url)

**Purpose:** Extract clean web content

**Process:**
1. Fetch URL with Trafilatura
2. Extract main content (removes ads, nav, footers)
3. Preserve tables and images
4. Convert images to captions via Ollama vision model
5. Replace `![](src)` with `**Image:** {caption}`
6. Return clean markdown

**Features:**
- Handles JavaScript-rendered content
- Preserves semantic structure
- Removes boilerplate
- Maintains readability

**Example:**
```
Input: https://theschoolof.ai/
Output:
# The School of AI
Leading AI education platform...

**Image:** Screenshot showing course dashboard with enrollment statistics
```

---

#### 4.2.3 extract_pdf(file_path)

**Purpose:** Convert PDF to markdown

**Process:**
1. Validate file exists
2. Extract with PyMuPDF4LLM
3. Save images to `documents/images/`
4. Rewrite image paths in markdown
5. Replace images with AI captions
6. Delete original images
7. Return markdown text

**Features:**
- Preserves formatting (headers, lists, tables)
- Extracts embedded images
- Handles multi-column layouts
- Maintains reading order

**Example:**
```
Input: documents/financial_report.pdf
Output:
# Q4 Financial Report

**Image:** Bar chart showing revenue growth of 23% YoY

## Key Metrics
- Revenue: $1.2M
- Profit: $340K
```

---

#### 4.2.4 Supporting Functions

**get_embedding(text):**
- HTTP POST to Ollama API (`http://localhost:11434/api/embeddings`)
- Model: nomic-embed-text
- Returns numpy array (768 dimensions, float32)

**caption_image(path_or_url):**
- Loads image (local file or URL)
- Encodes to base64
- Sends to Ollama vision model (gemma3:12b)
- Prompt: "Describe this image for alt-text"
- Returns caption string
- Deletes local image file after processing

**replace_images_with_captions(markdown):**
- Regex: `!\[(.*?)\]\((.*?)\)`
- Calls `caption_image()` for each match
- Replaces with: `**Image:** {caption}`
- Handles errors gracefully

**semantic_merge(text):**
- LLM-based intelligent chunking
- Processes 512-word chunks
- Asks LLM: "Does this contain multiple topics?"
- If yes, extracts second topic boundary
- Splits at topic change
- Reuses leftover words in next iteration
- Avoids mid-sentence breaks

**process_documents():**
- Scans `documents/` directory for files
- Computes MD5 hash for each file
- Checks against cache (`doc_index_cache.json`)
- Skips unchanged files
- **Per new/modified file:**
  1. Detect type (PDF, HTML, other)
  2. Extract to markdown (PyMuPDF4LLM, Trafilatura, or MarkItDown)
  3. Run semantic chunking
  4. Generate embeddings for each chunk
  5. Add to FAISS index
  6. Append metadata
  7. Update cache
  8. Save index immediately
- Runs on server startup (background thread)

**Storage Structure:**
```
faiss_index/
  index.bin                # FAISS vector index (L2 distance)
  metadata.json            # Chunk text + source attribution
  doc_index_cache.json     # File hash cache for change detection
```

**Metadata Format:**
```json
[
  {
    "doc": "dlf.md",
    "chunk": "Anmol Singh purchased a DLF apartment...",
    "chunk_id": "dlf_3"
  }
]
```

---

### 4.3 Web Search Server (mcp_server_3.py)

**Server ID:** `websearch`  
**Framework:** FastMCP  
**Transport:** stdio  
**Tool Count:** 2

**Tools:**

**duckduckgo_search_results(query, max_results=10):**
- Web search via DuckDuckGo API
- Returns title, URL, snippet
- Respects max_results parameter

**download_raw_html_from_url(url):**
- Fetches raw HTML content
- No parsing or extraction
- Returns complete page source

---

## 5. CONFIGURATION SYSTEM

### 5.1 profiles.yaml Structure

**Agent Configuration:**
```yaml
agent:
  name: Cortex-R
  id: cortex_r_002
  description: >
    A reasoning-driven AI agent capable of using external tools
    and memory to solve complex tasks step-by-step.
```

**Strategy Configuration:**
```yaml
strategy:
  planning_mode: conservative    # conservative | exploratory
  exploration_mode: parallel     # parallel | sequential
  memory_fallback_enabled: true  # Use successful tools on failure
  max_steps: 3                   # Maximum agent loop iterations
  max_lifelines_per_step: 3      # Retries per step
```

**Memory Configuration:**
```yaml
memory:
  memory_service: true            # Enable persistence
  summarize_tool_results: true    # Store condensed outputs
  tag_interactions: true          # LLM-generated tags
  storage:
    base_dir: "memory"
    structure: "date"             # YYYY/MM/DD hierarchy
```

**LLM Configuration:**
```yaml
llm:
  text_generation: gemini         # gemini | phi4 | gemma3:12b | qwen2.5:32b-instruct-q4_0
  embedding: nomic                # nomic-embed-text
```

**Persona Configuration:**
```yaml
persona:
  tone: concise
  verbosity: low
  behavior_tags: [rational, focused, tool-using]
```

**MCP Servers Configuration:**
```yaml
mcp_servers:
  - id: math
    script: mcp_server_1.py
    cwd: /path/to/S9
    description: "Math tools, string-int conversions, fibonacci, python sandbox"
    capabilities: [add, subtract, multiply, ...]
    basic_tools: [run_python_sandbox]
```

---

### 5.2 models.json Structure

**Purpose:** Define available LLM backends

**Example:**
```json
{
  "models": {
    "gemini": {
      "type": "gemini",
      "model": "gemini-1.5-pro"
    },
    "phi4": {
      "type": "ollama",
      "model": "phi4:latest",
      "url": {
        "generate": "http://localhost:11434/api/generate"
      }
    }
  }
}
```

---

## 6. PROMPT ENGINEERING

### 6.1 Perception Prompt

**File:** `prompts/perception_prompt.txt`

**Structure:**
- System role definition
- MCP server catalog
- User query
- Output format specification (JSON)
- Server selection rules

**Key Instructions:**
- Match user intent to server capabilities
- Extract entities (names, numbers, URLs)
- Suggest specific tool if possible
- Select all relevant servers (not just one)
- Fallback to all servers if uncertain

---

### 6.2 Decision Prompts

**Conservative Mode** (`decision_prompt_conservative.txt`):

**Key Rules:**
- Plan exactly 1 tool call
- Follow tool docstring usage exactly
- Parse results: `json.loads(result.content[0].text)["result"]`
- Never inline json.loads in f-strings
- Return `FINAL_ANSWER:` or `FURTHER_PROCESSING_REQUIRED:`
- Include tool docstring before each call

**Exploratory Modes:**

**Parallel** (`decision_prompt_exploratory_parallel.txt`):
- Plan multiple independent tool calls
- Execute all in parallel
- Aggregate results
- Useful for diverse data gathering

**Sequential** (`decision_prompt_exploratory_sequential.txt`):
- Plan chain of tools with try/except
- Fallback logic for failures
- Preserve intermediate results
- Useful for uncertain paths

**Common Patterns:**

**Pattern 1: Dependent Tools**
```python
# Tool 1 output feeds Tool 2
result1 = await mcp.call_tool('tool1', input1)
parsed = json.loads(result1.content[0].text)["result"]

input2 = {"input": {"data": parsed}}
result2 = await mcp.call_tool('tool2', input2)
```

**Pattern 2: Document Fetching**
```python
# Fetch document, then signal need for processing
result = await mcp.call_tool('extract_pdf', {"file_path": "doc.pdf"})
return f"FURTHER_PROCESSING_REQUIRED: {result}"
```

**Pattern 3: Fallback Logic**
```python
try:
    result = await mcp.call_tool('primary_tool', input)
except Exception:
    result = await mcp.call_tool('backup_tool', input)
```

---

## 7. DATA FLOW & EXECUTION

### 7.1 Complete Request Lifecycle

```
1. USER INPUT
   ↓
2. AGENT.PY
   - Load config
   - Initialize MultiMCP
   - Create AgentContext
   ↓
3. AGENT LOOP START (Step 1/3)
   ↓
4. PERCEPTION PHASE
   - Load perception prompt
   - Inject server catalog + query
   - Call LLM
   - Parse intent, entities, selected_servers
   ↓
5. TOOL SELECTION
   - Get tools from selected servers only
   - Generate tool descriptions
   ↓
6. DECISION PHASE
   - Select prompt based on strategy
   - Inject tools + query
   - Call LLM
   - Receive async def solve() code
   ↓
7. VALIDATION
   - Check for solve() signature
   - If invalid → retry (consume lifeline)
   ↓
8. EXECUTION PHASE
   - Create sandbox module
   - Inject SandboxMCP
   - Execute solve()
   - Parse result
   ↓
9. RESULT ANALYSIS
   ├─ FINAL_ANSWER: → Return to user
   ├─ FURTHER_PROCESSING_REQUIRED: → Update context, goto step 3
   └─ [sandbox error:] → Retry (consume lifeline)
   ↓
10. MEMORY UPDATE
    - Log tool calls
    - Store results
    - Mark success/failure
    ↓
11. NEXT STEP OR COMPLETE
    - If more steps available → goto step 3
    - If max steps reached → return error
    - If FINAL_ANSWER → complete
```

---

### 7.2 Memory Persistence Flow

```
SESSION START
  ↓
1. Generate session ID: 2025/11/28/session-{ts}-{uuid}
2. Create memory directory: memory/2025/11/28/
3. Check for existing session file
   ↓
   ├─ EXISTS → Load items
   └─ NOT EXISTS → Initialize empty list
   ↓
4. Log session start metadata
5. Save to disk
   ↓
DURING EXECUTION
  ↓
6. Before tool call → add_tool_call()
7. After tool call → add_tool_output(success=True/False)
8. Immediate save to disk
   ↓
SESSION END
  ↓
9. Log final answer
10. Save to disk
11. Memory available for future sessions
```

---

### 7.3 Document Indexing Flow

```
SERVER STARTUP
  ↓
1. Check for faiss_index/index.bin
   ↓
   ├─ EXISTS → Skip indexing
   └─ NOT EXISTS → Trigger process_documents()
   ↓
2. Scan documents/ directory
3. For each file:
   ↓
   4. Compute MD5 hash
   5. Check doc_index_cache.json
      ↓
      ├─ UNCHANGED → Skip
      └─ NEW/MODIFIED → Process
      ↓
   6. Detect file type (PDF, HTML, other)
   7. Extract to markdown
      ├─ PDF → PyMuPDF4LLM
      ├─ HTML → Trafilatura
      └─ Other → MarkItDown
      ↓
   8. Run semantic_merge() chunking
   9. For each chunk:
      ├─ Generate embedding
      ├─ Add to FAISS index
      └─ Store metadata
      ↓
   10. Update cache
   11. Save index to disk
   ↓
READY FOR SEARCH QUERIES
```

---

## 8. KEY DESIGN PATTERNS & TECHNIQUES

### 8.1 Cognitive Architecture Pattern

**Inspiration:** Mimics human problem-solving

**Three Phases:**
1. **Perception:** Understand what is needed
2. **Decision:** Plan how to achieve it
3. **Action:** Execute the plan

**Benefits:**
- Clear separation of concerns
- Modular and testable
- Mirrors human reasoning

---

### 8.2 Stateless Server Pattern

**Problem:** Persistent connections can fail and require complex recovery

**Solution:** Reconnect per tool call

**Implementation:**
- MultiMCP spawns fresh subprocess for each call
- No persistent state in servers
- Automatic recovery from crashes

**Trade-offs:**
- Higher latency per call (subprocess spawn)
- Lower complexity (no connection management)
- Better reliability (no stale connections)

---

### 8.3 Sandboxed Code Generation

**Problem:** LLM-generated code may be unsafe

**Solution:** Execute in controlled environment

**Constraints:**
- No file system access (except via tools)
- No network access (except via tools)
- No subprocess spawning
- Limited built-ins (json, re only)
- Call count limiting (max 5 per plan)

**Benefits:**
- Safe execution of arbitrary code
- Prevents resource exhaustion
- Isolates failures

---

### 8.4 Semantic Chunking via LLM

**Problem:** Fixed-size chunking breaks context

**Solution:** Use LLM to detect topic boundaries

**Process:**
1. Take 512-word chunk
2. Ask LLM: "Does this contain multiple topics?"
3. If yes, extract second topic start
4. Split at boundary
5. Reuse leftover words

**Benefits:**
- Preserves semantic coherence
- Improves RAG retrieval quality
- Avoids mid-sentence breaks

---

### 8.5 Image-to-Text via Vision LLM

**Problem:** Images not searchable in RAG

**Solution:** Generate captions with vision model

**Process:**
1. Detect images in markdown (PDF extraction, web scraping)
2. Encode image to base64
3. Send to Ollama vision model (gemma3:12b)
4. Prompt: "Describe for alt-text"
5. Replace image with caption
6. Delete original image

**Benefits:**
- Makes visual content searchable
- Reduces storage requirements
- Enables multimodal understanding

---

### 8.6 Memory-Guided Strategy

**Problem:** Repeated failures waste resources

**Solution:** Learn from successful tool usage

**Process:**
1. Track tool success/failure in memory
2. On replanning, query memory for recent successes
3. Filter tools to proven subset
4. Generate new plan with higher success probability

**Benefits:**
- Adaptive behavior
- Reduced trial-and-error
- Session-level learning

---

## 9. CONFIGURATION & EXTENSIBILITY

### 9.1 Adding New MCP Server

**Steps:**
1. Create server script (e.g., `mcp_server_4.py`)
2. Implement tools using FastMCP
3. Define Pydantic models in `models.py`
4. Add server to `config/profiles.yaml`:
   ```yaml
   - id: new_server
     script: mcp_server_4.py
     cwd: /path/to/S9
     description: "Server purpose"
     capabilities: [tool1, tool2]
   ```
5. Restart agent
6. Server automatically discovered on initialization

---

### 9.2 Adding New LLM Backend

**Steps:**
1. Add model definition to `config/models.json`:
   ```json
   "new_model": {
     "type": "new_backend",
     "model": "model-name",
     "url": "http://api-endpoint"
   }
   ```
2. Implement `_new_backend_generate()` in `ModelManager`:
   ```python
   def _new_backend_generate(self, prompt: str) -> str:
       # Implementation
       return response
   ```
3. Update `generate_text()` to route to new backend
4. Set in `config/profiles.yaml`:
   ```yaml
   llm:
     text_generation: new_model
   ```

---

### 9.3 Adding New Strategy

**Steps:**
1. Create prompt template: `prompts/decision_prompt_new_strategy.txt`
2. Add strategy to `select_decision_prompt_path()`:
   ```python
   elif planning_mode == "new_strategy":
       return "prompts/decision_prompt_new_strategy.txt"
   ```
3. Optionally implement custom planning logic in `strategy.py`
4. Set in `config/profiles.yaml`:
   ```yaml
   strategy:
     planning_mode: new_strategy
   ```

---

## 10. PERFORMANCE & SCALABILITY

### 10.1 Performance Characteristics

**Cold Start (First Query):**
- MultiMCP initialization: ~2-3 seconds (3 servers)
- Document indexing (if needed): ~30-60 seconds (depends on corpus size)
- First tool call: ~1-2 seconds (subprocess spawn + execution)

**Warm Query (Subsequent):**
- Perception: ~1-2 seconds (LLM call)
- Planning: ~2-4 seconds (LLM call with context)
- Execution: ~1-2 seconds per tool call
- Total: ~5-10 seconds per query

**Memory Overhead:**
- MultiMCP tool map: ~1MB (for 20 tools)
- Session memory: ~10KB per query
- FAISS index: ~5MB per 1000 chunks
- Document cache: ~100KB per document

---

### 10.2 Scalability Considerations

**Horizontal Scaling:**
- MCP servers can run on separate machines
- Update server configs with remote endpoints
- Requires network transport (not stdio)

**Vertical Scaling:**
- Add more tools to existing servers
- Increase max_steps for complex tasks
- Use more powerful LLM backends

**Optimization Opportunities:**
- Cache LLM responses (perception, planning)
- Parallelize tool calls (exploratory mode)
- Precompute embeddings for static documents
- Use faster embedding models

---

### 10.3 Bottlenecks

**Current Bottlenecks:**
1. **LLM Latency:** Perception + Planning = ~3-6 seconds
2. **Subprocess Spawn:** ~200ms per tool call
3. **Sequential Execution:** Tools execute one-by-one (conservative mode)
4. **Document Indexing:** Blocks on first query if index missing

**Mitigation Strategies:**
1. Use faster LLM models (phi4 vs gemini)
2. Implement connection pooling for MCP servers
3. Enable exploratory+parallel mode for multi-tool tasks
4. Pre-index documents before agent startup

---

## 11. ERROR HANDLING & RECOVERY

### 11.1 Error Categories

**Perception Errors:**
- JSON parsing failure → Selects all servers
- LLM timeout → Retry with same prompt
- Invalid server selection → Fallback to all servers

**Planning Errors:**
- No solve() function → Consumes lifeline, retry
- Syntax errors in plan → Consumes lifeline, retry
- LLM refusal → Returns error message

**Execution Errors:**
- Tool not found → Returns [sandbox error]
- Tool call failure → Consumes lifeline, retry
- Timeout → Consumes lifeline, retry
- Max calls exceeded → Returns [sandbox error]

**Memory Errors:**
- Disk write failure → Logs warning, continues
- Corrupted session file → Starts fresh session
- Missing directory → Creates automatically

**MCP Server Errors:**
- Server crash → Automatic restart (stateless design)
- Tool timeout → Propagates to sandbox
- Connection refused → Retries with backoff

---

### 11.2 Recovery Mechanisms

**Lifeline System:**
- Each step has 3 retry attempts
- Consumes lifeline on:
  - Invalid plan
  - Execution error
  - Tool failure
- After exhausting lifelines → Advances to next step

**Memory Fallback:**
- Enabled via `memory_fallback_enabled: true`
- On replanning, uses recently successful tools
- Increases success probability

**Step Continuation:**
- Max 3 steps per query
- Each step independent
- Final step returns best effort result

**Graceful Degradation:**
- If all steps fail → Returns informative error
- If partial success → Returns intermediate result
- If server unavailable → Suggests alternative tools

---

## 12. SECURITY CONSIDERATIONS

### 12.1 Sandbox Security

**Constraints:**
- No direct file I/O (only via tools)
- No network access (only via tools)
- No subprocess spawning
- Limited imports (json, re only)
- No access to os, sys, subprocess modules

**Risks:**
- LLM might generate code to bypass constraints
- Tool calls could be abused (e.g., excessive searches)

**Mitigations:**
- Call count limiting (max 5 per plan)
- Tool execution timeout
- Whitelist safe built-ins
- Isolated module namespace

---

### 12.2 Data Privacy

**Sensitive Data Exposure:**
- User queries logged to memory (plaintext JSON)
- Tool results stored in memory
- Documents indexed (including personal data)

**Recommendations:**
- Encrypt memory files at rest
- Implement access controls on memory directory
- Sanitize sensitive data before indexing
- Use private Ollama instance (no data leaves machine)

---

### 12.3 API Key Management

**Current Approach:**
- Gemini API key in environment variable
- No encryption
- Visible to agent process

**Best Practices:**
- Use secret management service (e.g., HashiCorp Vault)
- Rotate keys regularly
- Implement key usage monitoring
- Restrict API key permissions

---

## 13. FUTURE ENHANCEMENTS

### 13.1 Planned Features

**Multi-Agent Collaboration:**
- Multiple agent instances working together
- Task decomposition and delegation
- Result aggregation

**Streaming Responses:**
- Real-time tool execution updates
- Progressive result display
- Improved UX for long-running tasks

**Enhanced Memory:**
- Vector search over historical sessions
- Concept graphs for knowledge representation
- Long-term learning across sessions

**Tool Composition:**
- Automatic chaining of related tools
- Learned tool sequences
- Custom tool creation via composition

**Web UI:**
- Browser-based interface
- Visual workflow editor
- Session history browser

---

### 13.2 Research Directions

**Reinforcement Learning:**
- Learn optimal tool selection
- Optimize planning strategies
- Reduce trial-and-error

**Hierarchical Planning:**
- Multi-level task decomposition
- Abstract reasoning
- Goal-oriented behavior

**Self-Improvement:**
- Analyze failed executions
- Propose architecture changes
- Automated prompt optimization

---

## 14. CONCLUSION

Cortex-R represents a sophisticated implementation of cognitive architecture principles in an AI agent framework. Its key strengths are:

1. **Modularity:** Clear separation of concerns enables easy extension
2. **Resilience:** Stateless servers and retry mechanisms ensure reliability
3. **Adaptability:** Strategic planning and memory fallback enable learning
4. **Multimodality:** Vision-LLM integration enables rich document understanding
5. **Safety:** Sandboxed execution prevents uncontrolled code execution

The architecture successfully balances complexity and usability, providing a robust foundation for complex multi-step reasoning tasks.

---

## APPENDIX A: FILE STRUCTURE

```
S9/
├── agent.py                    # Entry point
├── models.py                   # Pydantic schemas
├── pyproject.toml              # Dependencies
├── uv.lock                     # Lock file
│
├── config/
│   ├── profiles.yaml           # Agent configuration
│   └── models.json             # LLM definitions
│
├── core/
│   ├── context.py              # State management
│   ├── loop.py                 # Execution engine
│   ├── session.py              # MCP dispatcher
│   └── strategy.py             # Planning strategies
│
├── modules/
│   ├── perception.py           # Intent analysis
│   ├── decision.py             # Plan generation
│   ├── action.py               # Sandboxed execution
│   ├── memory.py               # Persistence
│   ├── model_manager.py        # LLM abstraction
│   └── tools.py                # Utilities
│
├── prompts/
│   ├── perception_prompt.txt
│   ├── decision_prompt_conservative.txt
│   ├── decision_prompt_exploratory_parallel.txt
│   └── decision_prompt_exploratory_sequential.txt
│
├── mcp_server_1.py             # Math server
├── mcp_server_2.py             # Documents server
├── mcp_server_3.py             # Web search server
│
├── memory/
│   └── {YYYY}/{MM}/{DD}/
│       └── session-*.json
│
├── faiss_index/
│   ├── index.bin               # Vector index
│   ├── metadata.json           # Chunk data
│   └── doc_index_cache.json    # File hashes
│
└── documents/
    ├── *.pdf                   # Source PDFs
    ├── *.md                    # Markdown docs
    └── images/                 # Extracted images
```

---

## APPENDIX B: DEPENDENCIES

**Core:**
- asyncio: Async execution
- pydantic: Data validation
- yaml: Config parsing
- pathlib: Path manipulation

**MCP:**
- mcp[cli]: Model Context Protocol SDK

**LLM:**
- google-genai: Gemini API
- requests: Ollama HTTP API

**RAG:**
- faiss-cpu: Vector search
- llama-index: Document processing
- llama-index-embeddings-google-genai: Embeddings

**Document Processing:**
- markitdown[all]: Universal converter
- pymupdf4llm: PDF extraction
- trafilatura[all]: Web scraping
- beautifulsoup4: HTML parsing

**Image Processing:**
- pillow: Image manipulation

**UI:**
- rich: Terminal formatting
- tqdm: Progress bars

**Utilities:**
- httpx: HTTP client
- dotenv: Environment variables

---

## APPENDIX C: GLOSSARY

**Agent:** Autonomous system that perceives, decides, and acts

**Cognitive Loop:** Perception → Decision → Action cycle

**Conservative Mode:** Planning strategy with single tool call

**Exploratory Mode:** Planning strategy with multiple tool options

**FAISS:** Facebook AI Similarity Search (vector database)

**Lifeline:** Retry attempt after execution failure

**MCP:** Model Context Protocol (tool server standard)

**Memory Fallback:** Using previously successful tools on replanning

**Perception:** Intent analysis and server selection phase

**RAG:** Retrieval-Augmented Generation

**Sandbox:** Isolated execution environment

**Semantic Chunking:** LLM-based topic-aware text splitting

**Session:** Conversation context spanning multiple queries

**Strategy:** Planning approach (conservative or exploratory)

**Tool:** Atomic capability provided by MCP server

---

**END OF REPORT**
