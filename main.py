#!/usr/bin/env python3
"""Demo: JMAP email tools for LLM integration.

Usage:
    # Print all tool definitions (OpenAI function-calling format):
    python main.py --tools

    # Interactive demo (requires JMAP_HOST and JMAP_API_TOKEN env vars):
    JMAP_HOST=jmap.fastmail.com JMAP_API_TOKEN=your_token python main.py --demo

    # Call a specific tool:
    JMAP_HOST=jmap.fastmail.com JMAP_API_TOKEN=your_token \
        python main.py --call list_mailboxes

    # Call a tool with JSON arguments:
    JMAP_HOST=jmap.fastmail.com JMAP_API_TOKEN=your_token \
        python main.py --call search_emails '{"query": "invoice", "limit": 5}'
"""

import json
import sys

from jmap_tools import call_tool, configure, get_tool_definitions


def print_tools():
    """Print all tool definitions in OpenAI function-calling format."""
    definitions = get_tool_definitions()
    print(json.dumps(definitions, indent=2))


def run_demo():
    """Run an interactive demo showing the tool workflow."""
    print("=== JMAP Email Tools Demo ===\n")

    # Step 1: Configure
    print("1. Configuring JMAP client...")
    result = configure()
    if not result.get("success"):
        print(f"   Error: {result.get('error')}")
        sys.exit(1)
    print(f"   Connected. Account: {result['account_id']}")
    for ident in result.get("identities", []):
        print(f"   Identity: {ident['name']} <{ident['email']}>")

    # Step 2: List mailboxes
    print("\n2. Listing mailboxes...")
    result = call_tool("list_mailboxes", {})
    if result.get("success"):
        for mb in result["mailboxes"]:
            role = f" ({mb['role']})" if mb.get("role") else ""
            print(f"   {mb['name']}{role}: {mb['total_emails']} emails, {mb['unread_emails']} unread")

    # Step 3: Search recent emails
    print("\n3. Searching recent emails...")
    result = call_tool("search_emails", {"limit": 5})
    if result.get("success"):
        print(f"   Found {result.get('total', '?')} total emails. Showing first {len(result['emails'])}:")
        for email in result["emails"]:
            from_str = email["from"][0]["email"] if email["from"] else "unknown"
            read = "" if email["is_read"] else " [UNREAD]"
            print(f"   - {email['subject']} (from {from_str}){read}")
            print(f"     ID: {email['id']}")

    # Step 4: Get vacation response
    print("\n4. Checking vacation response...")
    result = call_tool("get_vacation_response", {})
    if result.get("success"):
        status = "enabled" if result.get("is_enabled") else "disabled"
        print(f"   Vacation response: {status}")

    print("\n=== Demo complete ===")


def call_tool_cli(tool_name: str, args_json: str | None = None):
    """Call a tool from the CLI."""
    args = json.loads(args_json) if args_json else {}

    # Auto-configure if needed and not calling configure
    if tool_name != "configure":
        config_result = configure()
        if not config_result.get("success"):
            print(json.dumps(config_result, indent=2))
            sys.exit(1)

    result = call_tool(tool_name, args)
    print(json.dumps(result, indent=2, default=str))


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print(__doc__)
        sys.exit(0)

    if sys.argv[1] == "--tools":
        print_tools()
    elif sys.argv[1] == "--demo":
        run_demo()
    elif sys.argv[1] == "--call":
        if len(sys.argv) < 3:
            print("Usage: python main.py --call <tool_name> [json_args]")
            sys.exit(1)
        tool_name = sys.argv[2]
        args_json = sys.argv[3] if len(sys.argv) > 3 else None
        call_tool_cli(tool_name, args_json)
    else:
        print(f"Unknown option: {sys.argv[1]}")
        print("Use --tools, --demo, or --call")
        sys.exit(1)


if __name__ == "__main__":
    main()
