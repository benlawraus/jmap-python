#!/usr/bin/env python3
"""Interactive terminal chat with email tools powered by Ollama."""

import json
import sys

import ollama

from jmap_tools import call_tool, configure, get_tool_definitions

MODEL = "gemma4"

SYSTEM_PROMPT = """You are an email assistant with access to tools for managing email via JMAP.

Workflow:
1. Call `configure` first to connect (no arguments needed, env vars are set).
2. Use `list_mailboxes` to discover folder IDs before searching within a specific folder.
3. Use `search_emails` to find emails, then `get_email` with the returned ID for full content.
4. For sending, replying, or forwarding, use the appropriate tool.

Always show the user a clear summary of results. When listing emails, show sender, subject, and date.
Keep responses concise."""


def run_chat():
    tools = get_tool_definitions()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Auto-configure JMAP on startup
    print("Connecting to JMAP server...")
    result = configure()
    if not result.get("success"):
        print(f"Failed to connect: {result.get('error')}")
        sys.exit(1)
    read_only = result.get("read_only", False)
    print(f"Connected. Account: {result['account_id']}")
    if read_only:
        print("  Mode: read-only (send/reply/forward/move/delete/flag unavailable)")
    else:
        for ident in result.get("identities", []):
            print(f"  Identity: {ident['name']} <{ident['email']}>")
    print()

    # Inject configure result into conversation so the model knows it's done
    messages.append({"role": "user", "content": "connect to my email"})
    status = f"Connected to your email account ({result['account_id']})."
    if read_only:
        status += " Note: running in read-only mode. You can search and read emails, list mailboxes, and view threads, but cannot send, reply, forward, move, delete, flag, or modify emails."
    status += " How can I help?"
    messages.append({"role": "assistant", "content": status})

    print("Email assistant ready. Type 'quit' to exit.\n")

    while True:
        try:
            user_input = input("\033[1mYou:\033[0m ")
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if user_input.strip().lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        if not user_input.strip():
            continue

        messages.append({"role": "user", "content": user_input})

        # Conversation loop: keep going until model gives a final text response
        while True:
            response = ollama.chat(
                model=MODEL,
                messages=messages,
                tools=tools,
            )

            msg = response.message

            # If no tool calls, print the text response and break
            if not msg.tool_calls:
                text = msg.content or ""
                messages.append({"role": "assistant", "content": text})
                print(f"\n\033[1mAssistant:\033[0m {text}\n")
                break

            # Process tool calls
            messages.append(msg)

            for tc in msg.tool_calls:
                name = tc.function.name
                args = tc.function.arguments or {}

                print(f"  \033[2m[calling {name}({json.dumps(args, separators=(',', ':'))})]\033[0m")
                result = call_tool(name, args)

                result_str = json.dumps(result, default=str)
                messages.append({"role": "tool", "name": name, "content": result_str})


def main():
    run_chat()


if __name__ == "__main__":
    main()