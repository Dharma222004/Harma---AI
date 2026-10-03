# Harma — Personal AI Agent

> **Your action-oriented personal AI. Not a chatbot — an agent.**

Harma understands what you want, selects the right tools, executes actions on your computer and services, verifies the results, and responds naturally.

---

## Phase 1 — What Works Now

- ✅ LLM connection (OpenAI / Gemini / Claude / any OpenAI-compatible API)
- ✅ Core agent loop (multi-step reasoning + tool calling)
- ✅ Tool registry (modular, auto-discovered)
- ✅ `get_current_time` tool
- ✅ `open_application` tool (Windows/Mac/Linux)
- ✅ `close_application` tool
- ✅ Permission system (SAFE / SENSITIVE / HIGH_RISK)
- ✅ Short-term memory (conversation + task state)
- ✅ Beautiful terminal interface
- ✅ Multi-provider LLM adapter architecture

---

## Quick Start

### 1. Install dependencies

```bash
pip install openai pyyaml
```

### 2. Set your API key

Copy `.env.example` to `.env` and fill in your key:

```bash
copy .env.example .env
```

Edit `.env`:
```env
HARMA_API_KEY=sk-your-openai-key-here
```

### 3. Configure Harma (optional)

Edit `config.yaml` to choose your provider and model:

```yaml
llm:
  provider: openai        # or: gemini | claude
  model: gpt-4o-mini
```

### 4. Run Harma

```bash
python main.py
```

Or with a provider override:
```bash
python main.py --provider gemini
python main.py --provider claude
```

---

## Supported LLM Providers

| Provider | config value | SDK to install | Description |
|----------|-------------|----------------|-------------|
| **NVIDIA (Default Primary)** | `nvidia` | `pip install openai` | Hosted LLM via NVIDIA NIM (e.g. `nemotron-3-super-120b-a12b`) |
| Google Gemini | `gemini` | `pip install google-generativeai` | Gemini 2.5 Flash / Pro with multi-key rotation |
| Groq | `groq` | `pip install openai` | Fast Llama 3 / Mixtral with multi-key rotation |
| OpenAI | `openai` | `pip install openai` | GPT-4o / GPT-4o-mini |
| Anthropic Claude | `claude` | `pip install anthropic` | Claude 3.5 Sonnet |
| Ollama (local) | `openai` + `base_url` | Ollama app | Local open-weights execution |

---

## NVIDIA NIM Setup (Primary Provider)

### 1. Environment Configuration

Add the following to your `.env` file:

```env
# Primary Provider
HARMA_LLM_PROVIDER=nvidia

# NVIDIA NIM Hosted API Credentials
NVIDIA_API_KEY=your_nvidia_api_key_here
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=nemotron-3-super-120b-a12b

# Operational Settings
NVIDIA_TIMEOUT=120
NVIDIA_TEMPERATURE=0.2

# Strict Fallback Policy (Default: false)
# When false, errors are raised directly without consuming Gemini/Groq credits.
HARMA_LLM_FALLBACK_ENABLED=false
```

### 2. Provider Health Check & Diagnostics

Check your NVIDIA LLM connectivity at startup or via the CLI:

```bash
python main.py
```

The CLI displays:
```text
Harma LLM
Provider : NVIDIA
Model    : nemotron-3-super-120b-a12b
Status   : Connected
```

You can also inspect health and diagnostics programmatically or via REST API:
- `GET /api/health` — returns overall subsystem health and active LLM status.
- `GET /api/llm/diagnostics` — verifies authentication, connectivity, model generation, and tool-calling capabilities.

### 3. Switching Providers

You can switch between providers at any time **without modifying any application code**:

**Switch to Google Gemini:**
```env
HARMA_LLM_PROVIDER=gemini
HARMA_API_KEY=your_gemini_api_key
HARMA_MODEL=gemini-2.5-flash
```

**Switch to Groq:**
```env
HARMA_LLM_PROVIDER=groq
GROQ_API_KEY_1=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-20b
```

Or via CLI flag override:
```bash
python main.py --provider gemini
python main.py --provider groq
python main.py --provider nvidia
```

---

## Example Conversations

```
You  › Harma, what time is it?
Harma  It's 1:21 PM, Friday 2nd October 2026.

You  › Open Chrome.
Harma  Done. I opened Chrome.

You  › What can you do?
Harma  Right now I can:
  • Tell you the current time and date
  • Open and close applications on your computer
  More capabilities are coming in Phase 2.
```

---

## Terminal Commands

| Command | Description |
|---------|-------------|
| `!status` | Show agent status and memory |
| `!tools` | List all registered tools |
| `!reset` | Clear conversation memory |
| `!help` | Show help |
| `quit` / `exit` | Exit Harma |

---

## Architecture

```
harma/
│
├── core/
│   ├── agent.py          ← Core agent loop (LLM ↔ tools)
│   ├── context.py        ← Wires everything together
│   ├── executor.py       ← Tool execution + permission enforcement
│   └── prompt.py         ← Harma's system prompt / identity
│
├── llm/
│   ├── provider.py       ← Abstract LLM interface
│   ├── factory.py        ← Provider factory (get_provider)
│   └── adapters/
│       ├── openai_adapter.py
│       ├── gemini_adapter.py
│       └── claude_adapter.py
│
├── tools/
│   ├── base.py           ← BaseTool + PermissionLevel + ToolResult
│   ├── registry.py       ← Central tool registry
│   ├── system/
│   │   └── time_tools.py ← get_current_time, get_system_info
│   └── computer/
│       └── app_tools.py  ← open_application, close_application
│
├── memory/
│   └── short_term.py     ← Conversation + task state
│
├── security/
│   └── permissions.py    ← 3-tier permission system
│
├── ui/
│   └── cli.py            ← Terminal interface
│
└── config/
    ├── settings.py       ← Config loader (env → .env → yaml → defaults)
    └── logging_config.py ← Structured logging
```

---

## Adding a New Tool

1. Create a file in the appropriate `harma/tools/<category>/` directory
2. Subclass `BaseTool`
3. Set `name`, `description`, `permission_level`, `parameters`
4. Implement `async def execute(**kwargs) -> ToolResult`

That's it. The registry auto-discovers it on next start.

```python
from harma.tools.base import BaseTool, PermissionLevel, ToolResult

class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something useful."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "The input."}
        },
        "required": ["input"],
    }

    async def execute(self, input: str, **kwargs) -> ToolResult:
        result = do_something(input)
        return ToolResult(success=True, output=result)
```

---

## Development Phases

| Phase | Status | Description |
|-------|--------|-------------|
| **1 — Core** | ✅ Complete | LLM + agent loop + tool registry + terminal UI |
| **2 — Computer Control** | 🔜 Next | Screenshot, mouse, keyboard, screen reading |
| **3 — Browser** | 🔜 Planned | Chrome control, web search, data extraction |
| **4 — Voice** | 🔜 Planned | Wake word, STT, TTS |
| **5 — App Automation** | 🔜 Planned | WhatsApp, Gmail, Calendar, Spotify |
| **6 — Memory** | 🔜 Planned | Persistent preferences, task history |
| **7 — Advanced Autonomy** | 🔜 Planned | Scheduled tasks, proactive notifications |

---

## Configuration Reference

### `config.yaml`

```yaml
llm:
  provider: openai          # LLM provider
  model: gpt-4o-mini        # Model name
  base_url:                 # Optional: OpenAI-compatible endpoint
  temperature: 0.2          # Response creativity (0.0–1.0)
  max_tokens: 4096          # Max response length
  timeout: 60               # Request timeout (seconds)
  stream: true              # Enable streaming responses

agent:
  name: Harma               # Agent name
  max_iterations: 15        # Max tool-call steps per task
  max_retries: 3            # Retries on errors

permissions:
  auto_confirm_safe: true           # SAFE actions run automatically
  auto_confirm_sensitive: false     # SENSITIVE actions ask you first

memory:
  short_term_max_messages: 40
```

### Environment Variables (`.env`)

```env
HARMA_API_KEY=sk-...            # Your API key
HARMA_LLM_PROVIDER=openai       # Override provider
HARMA_MODEL=gpt-4o              # Override model
HARMA_BASE_URL=...              # Override API endpoint
```
