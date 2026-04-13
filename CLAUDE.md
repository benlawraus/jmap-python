# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

JMAP email tools library that exposes email operations as LLM-callable functions with OpenAI-compatible tool definitions. Built on the `jmapc` library for JMAP protocol handling. Designed for Fastmail but works with any JMAP server.

## Commands

```bash
pip install .                             # Install dependencies
python main.py --tools                   # Print all tool definitions as JSON
python main.py --demo                    # Run interactive demo (requires .env)
python main.py --call <tool> '<json>'    # Call a specific tool from CLI
```

Requires `.env` file (copy from `.env.example`) with `JMAP_HOST` and `JMAP_API_TOKEN`.

## Architecture

Two-layer design:

- **`jmap_client.py`** — `JMAPMailClient` class wrapping `jmapc`. Handles mailbox/identity caching, batched JMAP requests with result references (`Ref`), and converts jmapc model objects into plain dicts. VacationResponse uses `CustomMethod` since jmapc doesn't have built-in support.

- **`jmap_tools.py`** — 15 tool functions decorated with `@jmap_tool`, which registers each in `TOOL_REGISTRY` with an OpenAI function-calling schema. A global `_client` instance is initialized by `configure()` and accessed via `_require_client()` (read ops) or `_require_write()` (write ops). Every tool catches exceptions and returns `{"success": bool, ...}`. `call_tool(name, args)` dispatches by name. Supports read-only API tokens: if identity fetch fails during `configure()`, sets `_read_only = True` and write tools return an error instead of making API calls.

- **`chat.py`** — Interactive terminal chat using Ollama (default model: `gemma4`). Auto-configures JMAP on startup, detects read-only mode, and injects connection status into the conversation context.

- **`main.py`** — CLI entry point with `--tools`, `--demo`, and `--call` modes.

The `docs/` directory contains JMAP protocol reference material (RFC 8621 excerpts) covering all supported operations.

## Key Patterns

- jmapc batches multiple method calls in one HTTP request using `client.request([Method1(), Method2(ids=Ref("/ids"))])` — result references chain outputs between methods
- Email send is a two-step batch: `EmailSet(create=...)` + `EmailSubmissionSet(create=..., email_id="#creationId")` with back-references
- `EmailSet(update={id: {"keywords/$seen": True}})` uses JMAP patch syntax for keyword/mailbox mutations
- Mailbox and identity data is lazily cached on first access in `JMAPMailClient`
- Read-only token detection: `configure()` tries `get_identities()` — if it fails (403), sets `_read_only = True`. Write tools use `_require_write()` which checks this flag
