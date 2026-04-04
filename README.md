# JMAP Email Tools for LLMs

A Python library that exposes email operations as LLM-callable tools with OpenAI-compatible function definitions. Built on [jmapc](https://github.com/smkent/jmapc) for JMAP protocol handling.

Works with any JMAP email server (Fastmail, etc.).

**Requires Python 3.10+**

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your JMAP credentials
```

### Fastmail Setup

1. Go to **Settings > Privacy & Security > Integrations > API tokens**
2. Create a new token with **Mail** access (read-write for full functionality, or read-only for search/read only)
3. Add to `.env`:
   ```
   JMAP_HOST=api.fastmail.com
   JMAP_API_TOKEN=fmu1-your-token-here
   ```

> **Read-only tokens:** If your token only has read access, the library automatically detects this and enters read-only mode. Search, read, list, and thread operations work normally. Send, reply, forward, move, delete, flag, and vacation tools return an error.

## Usage

### Interactive Chat

```bash
python chat.py
```

Uses Ollama (`gemma4` by default) for a conversational email assistant. Auto-connects to JMAP on startup and supports all tools via natural language.

### CLI

```bash
# Print all tool definitions (OpenAI function-calling format)
python main.py --tools

# Run interactive demo
python main.py --demo

# Call a specific tool
python main.py --call list_mailboxes
python main.py --call search_emails '{"query": "invoice", "limit": 5}'
python main.py --call get_email '{"email_id": "abc123"}'
python main.py --call send_email '{"to": [{"email": "alice@example.com"}], "subject": "Hi", "body": "Hello!"}'
```

### Python

```python
from jmap_tools import configure, call_tool, get_tool_definitions

# Connect to your JMAP server
configure()  # uses JMAP_HOST and JMAP_API_TOKEN from .env

# Get OpenAI-compatible tool definitions for your LLM
tools = get_tool_definitions()

# Call tools directly
result = call_tool("search_emails", {"query": "meeting notes", "limit": 10})
result = call_tool("get_email", {"email_id": "abc123", "format": "text"})
result = call_tool("send_email", {
    "to": [{"name": "Alice", "email": "alice@example.com"}],
    "subject": "Hello",
    "body": "Hi Alice!"
})
```

### LLM Integration

Pass `get_tool_definitions()` to any LLM that supports OpenAI-style function calling, then dispatch responses with `call_tool()`:

```python
import json
from jmap_tools import configure, call_tool, get_tool_definitions

configure()
tools = get_tool_definitions()

# In your LLM loop:
# 1. Send tools to the model
# 2. When the model returns a tool call:
tool_name = "search_emails"              # from model response
arguments = {"query": "tax documents"}   # from model response
result = call_tool(tool_name, arguments)
# 3. Send result back to the model
```

## Available Tools

| Tool | Description |
|------|-------------|
| `configure` | Connect to JMAP server (required first) |
| `list_mailboxes` | List all folders with email/unread counts |
| `search_emails` | Full-text and filtered search (from, to, subject, date range, etc.) |
| `get_email` | Get full email content in text or HTML |
| `send_email` | Compose and send a new email |
| `reply_to_email` | Reply or reply-all with auto-filled headers |
| `forward_email` | Forward with quoted original message |
| `move_email` | Move email to a different folder |
| `delete_email` | Move to trash or permanently delete |
| `mark_read` | Mark as read/unread |
| `mark_flagged` | Flag/unflag (star/unstar) |
| `get_thread` | Get all emails in a conversation |
| `list_identities` | List available sender identities |
| `get_vacation_response` | Get auto-reply settings |
| `set_vacation_response` | Configure out-of-office reply |

Every tool returns `{"success": true, ...data}` or `{"success": false, "error": "..."}`.

## Architecture

```
jmap_client.py  → JMAPMailClient (wraps jmapc with caching + simplified returns)
jmap_tools.py   → @jmap_tool decorator, 15 tool functions, OpenAI-compatible registry, read-only detection
chat.py         → Interactive terminal chat via Ollama
main.py         → CLI: --tools, --demo, --call
docs/           → JMAP protocol reference (RFC 8621)
```

## License

[CC BY-NC 4.0](LICENSE) — free to use and share for non-commercial purposes with attribution.
