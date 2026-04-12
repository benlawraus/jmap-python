"""LLM-callable JMAP email tools with OpenAI-compatible function definitions."""

from __future__ import annotations

import functools
import os
from datetime import datetime, timezone
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()

from jmap_client import JMAPMailClient

# ── Global state ───────────────────────────────────────────────────────

_client: JMAPMailClient | None = None
_read_only: bool = False

TOOL_REGISTRY: list[dict] = []


# ── Decorator ──────────────────────────────────────────────────────────

def jmap_tool(name: str, description: str, parameters: dict) -> Callable:
    """Register a function as an LLM-callable tool with OpenAI-compatible schema."""

    def decorator(func: Callable) -> Callable:
        TOOL_REGISTRY.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        })

        @functools.wraps(func)
        def wrapper(**kwargs: Any) -> dict:
            try:
                return func(**kwargs)
            except Exception as e:
                return {"success": False, "error": str(e)}

        wrapper.tool_name = name  # type: ignore
        return wrapper

    return decorator


def get_tool_definitions() -> list[dict]:
    """Return OpenAI-compatible tool definitions for all registered tools."""
    return TOOL_REGISTRY


def _require_client() -> JMAPMailClient:
    if _client is None:
        raise RuntimeError("JMAP client not configured. Call configure() first.")
    return _client


def _require_write() -> JMAPMailClient:
    client = _require_client()
    if _read_only:
        raise RuntimeError("This operation requires a read-write API token.")
    return client


# ── Tool: configure ────────────────────────────────────────────────────

@jmap_tool(
    name="configure",
    description="Initialize connection to a JMAP email server. Must be called before any other tool. Uses JMAP_HOST and JMAP_API_TOKEN env vars as defaults.",
    parameters={
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "description": "JMAP server hostname (e.g. 'jmap.fastmail.com'). Falls back to JMAP_HOST env var.",
            },
            "api_token": {
                "type": "string",
                "description": "API token for authentication. Falls back to JMAP_API_TOKEN env var.",
            },
        },
        "required": [],
    },
)
def configure(host: str | None = None, api_token: str | None = None) -> dict:
    global _client, _read_only
    host = host or os.environ.get("JMAP_HOST")
    api_token = api_token or os.environ.get("JMAP_API_TOKEN")
    if not host or not api_token:
        return {"success": False, "error": "host and api_token are required (or set JMAP_HOST and JMAP_API_TOKEN env vars)"}
    _client = JMAPMailClient(host=host, api_token=api_token)
    try:
        identities = _client.get_identities()
        _read_only = False
    except Exception:
        identities = []
        _read_only = True
    return {
        "success": True,
        "account_id": _client.client.account_id,
        "identities": identities,
        "read_only": _read_only,
    }


# ── Tool: list_mailboxes ──────────────────────────────────────────────

@jmap_tool(
    name="list_mailboxes",
    description="List all mailboxes (folders) in the email account. Returns each mailbox's ID, name, role, email counts, and unread counts. Use the returned mailbox IDs with other tools like search_emails or move_email.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def list_mailboxes() -> dict:
    client = _require_client()
    client.refresh_mailboxes()
    return {"success": True, "mailboxes": client.get_mailboxes()}


# ── Tool: search_emails ───────────────────────────────────────────────

@jmap_tool(
    name="search_emails",
    description="Search for emails matching filters. Use 'query' for full-text search across all fields, or combine specific filters. Returns email summaries with IDs for use with get_email or other tools.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Full-text search across from, to, cc, bcc, subject, and body"},
            "from_addr": {"type": "string", "description": "Filter by sender address or name"},
            "to_addr": {"type": "string", "description": "Filter by recipient address or name"},
            "cc_addr": {"type": "string", "description": "Filter by CC address or name"},
            "bcc_addr": {"type": "string", "description": "Filter by BCC address or name"},
            "subject": {"type": "string", "description": "Filter by subject line content"},
            "body": {"type": "string", "description": "Filter by body text content"},
            "in_mailbox": {"type": "string", "description": "Mailbox ID to search within (use list_mailboxes to get IDs)"},
            "has_keyword": {"type": "string", "description": "Email must have this keyword (e.g. '$flagged', '$seen', '$draft')"},
            "not_keyword": {"type": "string", "description": "Email must NOT have this keyword"},
            "has_attachment": {"type": "boolean", "description": "Filter by whether email has attachments"},
            "before": {"type": "string", "description": "Emails received before this UTC datetime (ISO 8601, e.g. '2024-01-15T00:00:00Z')"},
            "after": {"type": "string", "description": "Emails received on or after this UTC datetime (ISO 8601)"},
            "limit": {"type": "integer", "description": "Maximum number of results to return (default: 20, max: 100)", "default": 20},
            "sort_order": {"type": "string", "enum": ["asc", "desc"], "description": "Sort by received date: 'asc' (oldest first) or 'desc' (newest first, default)", "default": "desc"},
        },
        "required": [],
    },
)
def search_emails(
    query: str | None = None,
    from_addr: str | None = None,
    to_addr: str | None = None,
    cc_addr: str | None = None,
    bcc_addr: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    in_mailbox: str | None = None,
    has_keyword: str | None = None,
    not_keyword: str | None = None,
    has_attachment: bool | None = None,
    before: str | None = None,
    after: str | None = None,
    limit: int = 20,
    position: int = 0,
    sort_order: str = "desc",
) -> dict:
    client = _require_client()
    before_dt = datetime.fromisoformat(before) if before else None
    after_dt = datetime.fromisoformat(after) if after else None
    limit = min(limit, 100)

    result = client.search_emails(
        query=query, from_addr=from_addr, to_addr=to_addr,
        cc_addr=cc_addr, bcc_addr=bcc_addr, subject=subject, body=body,
        in_mailbox=in_mailbox, has_keyword=has_keyword, not_keyword=not_keyword,
        has_attachment=has_attachment, before=before_dt, after=after_dt,
        limit=limit, position=position, sort_order=sort_order,
    )
    return {"success": True, **result}


# ── Internal helper (not an LLM tool) ─────────────────────────────────

def query_email_ids(
    in_mailbox: str | None = None,
    after: str | None = None,
    limit: int = 50,
    position: int = 0,
    sort_order: str = "asc",
) -> dict:
    """Email/query only — returns IDs, no Email/get. Lightest possible JMAP call."""
    client = _require_client()
    after_dt = datetime.fromisoformat(after) if after else None
    limit = min(limit, 100)
    result = client.query_ids(
        in_mailbox=in_mailbox, after=after_dt,
        limit=limit, position=position, sort_order=sort_order,
    )
    return {"success": True, **result}


# ── Tool: get_email ───────────────────────────────────────────────────

@jmap_tool(
    name="get_email",
    description="Get the full content of an email by its ID. Returns headers, body text, attachments list, and metadata. Use 'text' format for plain text or 'html' for HTML content.",
    parameters={
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "The email ID (from search_emails or get_thread results)"},
            "format": {"type": "string", "enum": ["text", "html"], "description": "Body format: 'text' for plain text, 'html' for HTML (default: 'text')", "default": "text"},
        },
        "required": ["email_id"],
    },
)
def get_email(email_id: str, format: str = "text") -> dict:
    client = _require_client()
    result = client.get_email(email_id, format=format)
    return {"success": True, **result}


# ── Tool: get_emails_metadata ─────────────────────────────────────────

@jmap_tool(
    name="get_emails_metadata",
    description="Fetch a chosen subset of properties for many emails in one batched JMAP request. Defaults to id, threadId, keywords, preview — useful for backfill jobs that only need flags or thread linkage.",
    parameters={
        "type": "object",
        "properties": {
            "ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of JMAP email ids to fetch.",
            },
            "properties": {
                "type": "array",
                "items": {"type": "string"},
                "description": "JMAP property names to fetch (e.g. ['id','threadId','keywords','preview']). Omit for the default set.",
            },
        },
        "required": ["ids"],
    },
)
def get_emails_metadata(ids: list[str], properties: list[str] | None = None) -> dict:
    client = _require_client()
    emails = client.get_emails_metadata(ids, properties)
    return {"success": True, "emails": emails}


# ── Tool: download_attachment ─────────────────────────────────────────

@jmap_tool(
    name="download_attachment",
    description="Download an email attachment to a local file. Requires the email_id and blob_id from the attachments list returned by get_email. Returns the saved file path.",
    parameters={
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "ID of the email containing the attachment"},
            "blob_id": {"type": "string", "description": "Blob ID of the attachment (from get_email attachments list)"},
            "file_name": {"type": "string", "description": "Destination file name/path (optional, defaults to original attachment name)"},
        },
        "required": ["email_id", "blob_id"],
    },
)
def download_attachment(
    email_id: str, blob_id: str, file_name: str | None = None,
    output_dir: str | None = None,
) -> dict:
    client = _require_client()
    result = client.download_attachment(email_id, blob_id, file_name=file_name,
                                        output_dir=output_dir)
    return {"success": True, **result}


# ── Tool: upload_attachment ──────────────────────────────────────────

@jmap_tool(
    name="upload_attachment",
    description="Upload a local file as a blob for use as an email attachment. Returns a blob_id, type, and size. Pass the blob_id to send_email's attachments parameter to attach the file.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to the local file to upload"},
        },
        "required": ["file_path"],
    },
)
def upload_attachment(file_path: str) -> dict:
    client = _require_write()
    result = client.upload_blob(file_path)
    return {"success": True, **result}


# ── Tool: send_email ──────────────────────────────────────────────────

@jmap_tool(
    name="send_email",
    description="Compose and send a new email. Creates a draft and submits it for delivery in one operation. The email is sent from the default identity unless identity_id is specified.",
    parameters={
        "type": "object",
        "properties": {
            "to": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Recipient display name"},
                        "email": {"type": "string", "description": "Recipient email address"},
                    },
                    "required": ["email"],
                },
                "description": "List of recipients",
            },
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Email body content (plain text or HTML depending on is_html)"},
            "cc": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "required": ["email"],
                },
                "description": "CC recipients",
            },
            "bcc": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "required": ["email"],
                },
                "description": "BCC recipients",
            },
            "identity_id": {"type": "string", "description": "Identity to send from (use list_identities to see options; defaults to first identity)"},
            "is_html": {"type": "boolean", "description": "Set to true if body contains HTML (default: false)", "default": False},
            "attachments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "blob_id": {"type": "string", "description": "Blob ID from upload_attachment"},
                        "type": {"type": "string", "description": "MIME type (e.g. 'application/pdf'). Defaults to 'application/octet-stream'"},
                        "name": {"type": "string", "description": "File name for the attachment"},
                    },
                    "required": ["blob_id"],
                },
                "description": "Attachments to include. Upload files first with upload_attachment to get blob_ids.",
            },
        },
        "required": ["to", "subject", "body"],
    },
)
def send_email(
    to: list[dict[str, str]],
    subject: str,
    body: str,
    cc: list[dict[str, str]] | None = None,
    bcc: list[dict[str, str]] | None = None,
    identity_id: str | None = None,
    is_html: bool = False,
    attachments: list[dict[str, str]] | None = None,
) -> dict:
    client = _require_write()
    result = client.send_email(
        to=to, subject=subject, body=body,
        cc=cc, bcc=bcc, identity_id=identity_id, is_html=is_html,
        attachments=attachments,
    )
    return {"success": True, **result}


# ── Tool: reply_to_email ──────────────────────────────────────────────

@jmap_tool(
    name="reply_to_email",
    description="Reply to an existing email. Automatically sets To, Cc, subject (with Re: prefix), In-Reply-To, and References headers based on the original email. Use reply_all=true to reply to all recipients.",
    parameters={
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "ID of the email to reply to"},
            "body": {"type": "string", "description": "Reply body content"},
            "reply_all": {"type": "boolean", "description": "Reply to all recipients, not just sender (default: true)", "default": True},
            "is_html": {"type": "boolean", "description": "Set to true if body contains HTML (default: false)", "default": False},
        },
        "required": ["email_id", "body"],
    },
)
def reply_to_email(
    email_id: str,
    body: str,
    reply_all: bool = True,
    is_html: bool = False,
) -> dict:
    client = _require_write()
    result = client.reply_to_email(email_id, body, reply_all=reply_all, is_html=is_html)
    return {"success": True, **result}


# ── Tool: forward_email ───────────────────────────────────────────────

@jmap_tool(
    name="forward_email",
    description="Forward an existing email to new recipients. Includes the original message below your optional message, with a forwarded message header showing the original sender, date, and subject.",
    parameters={
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "ID of the email to forward"},
            "to": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "required": ["email"],
                },
                "description": "Recipients to forward to",
            },
            "body": {"type": "string", "description": "Optional message to include above the forwarded content"},
            "is_html": {"type": "boolean", "description": "Set to true if body contains HTML (default: false)", "default": False},
        },
        "required": ["email_id", "to"],
    },
)
def forward_email(
    email_id: str,
    to: list[dict[str, str]],
    body: str | None = None,
    is_html: bool = False,
) -> dict:
    client = _require_write()
    result = client.forward_email(email_id, to, body=body, is_html=is_html)
    return {"success": True, **result}


# ── Tool: move_email ──────────────────────────────────────────────────

@jmap_tool(
    name="move_email",
    description="Move an email to a different mailbox (folder). Use list_mailboxes to get available mailbox IDs.",
    parameters={
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "ID of the email to move"},
            "to_mailbox_id": {"type": "string", "description": "Destination mailbox ID (from list_mailboxes)"},
        },
        "required": ["email_id", "to_mailbox_id"],
    },
)
def move_email(email_id: str, to_mailbox_id: str) -> dict:
    client = _require_write()
    client.move_email(email_id, to_mailbox_id)
    return {"success": True}


# ── Tool: delete_email ────────────────────────────────────────────────

@jmap_tool(
    name="delete_email",
    description="Delete an email. By default moves it to Trash. Set permanent=true to permanently destroy it (cannot be undone).",
    parameters={
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "ID of the email to delete"},
            "permanent": {"type": "boolean", "description": "Permanently destroy the email instead of moving to Trash (default: false)", "default": False},
        },
        "required": ["email_id"],
    },
)
def delete_email(email_id: str, permanent: bool = False) -> dict:
    client = _require_write()
    client.delete_email(email_id, permanent=permanent)
    return {"success": True}


# ── Tool: mark_read ───────────────────────────────────────────────────

@jmap_tool(
    name="mark_read",
    description="Mark an email as read or unread.",
    parameters={
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "ID of the email"},
            "is_read": {"type": "boolean", "description": "True to mark as read, false to mark as unread (default: true)", "default": True},
        },
        "required": ["email_id"],
    },
)
def mark_read(email_id: str, is_read: bool = True) -> dict:
    client = _require_write()
    client.mark_read(email_id, is_read=is_read)
    return {"success": True}


# ── Tool: mark_flagged ────────────────────────────────────────────────

@jmap_tool(
    name="mark_flagged",
    description="Flag or unflag an email (star/unstar).",
    parameters={
        "type": "object",
        "properties": {
            "email_id": {"type": "string", "description": "ID of the email"},
            "is_flagged": {"type": "boolean", "description": "True to flag, false to unflag (default: true)", "default": True},
        },
        "required": ["email_id"],
    },
)
def mark_flagged(email_id: str, is_flagged: bool = True) -> dict:
    client = _require_write()
    client.mark_flagged(email_id, is_flagged=is_flagged)
    return {"success": True}


# ── Tool: get_thread ──────────────────────────────────────────────────

@jmap_tool(
    name="get_thread",
    description="Get all emails in a conversation thread. Returns emails in chronological order with summaries. Use the thread_id from search_emails or get_email results.",
    parameters={
        "type": "object",
        "properties": {
            "thread_id": {"type": "string", "description": "Thread ID to retrieve"},
        },
        "required": ["thread_id"],
    },
)
def get_thread(thread_id: str) -> dict:
    client = _require_client()
    result = client.get_thread(thread_id)
    return {"success": True, **result}


# ── Tool: list_identities ─────────────────────────────────────────────

@jmap_tool(
    name="list_identities",
    description="List all sender identities available for sending email. Each identity has a name, email address, and optional signature. Use identity IDs with send_email to choose which address to send from.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def list_identities() -> dict:
    client = _require_client()
    return {"success": True, "identities": client.get_identities()}


# ── Tool: get_vacation_response ────────────────────────────────────────

@jmap_tool(
    name="get_vacation_response",
    description="Get the current vacation/out-of-office auto-reply settings.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def get_vacation_response() -> dict:
    client = _require_client()
    result = client.get_vacation_response()
    return {"success": True, **result}


# ── Tool: set_vacation_response ────────────────────────────────────────

@jmap_tool(
    name="set_vacation_response",
    description="Configure the vacation/out-of-office auto-reply. Set is_enabled=true to activate, false to deactivate. Optionally set subject, body text, and date range.",
    parameters={
        "type": "object",
        "properties": {
            "is_enabled": {"type": "boolean", "description": "Enable or disable the vacation response"},
            "subject": {"type": "string", "description": "Auto-reply subject line (optional, server picks default if omitted)"},
            "text_body": {"type": "string", "description": "Plain text auto-reply body"},
            "html_body": {"type": "string", "description": "HTML auto-reply body (optional, generated from text_body if omitted)"},
            "from_date": {"type": "string", "description": "Start date for auto-reply (ISO 8601 UTC datetime, null for immediately)"},
            "to_date": {"type": "string", "description": "End date for auto-reply (ISO 8601 UTC datetime, null for indefinitely)"},
        },
        "required": ["is_enabled"],
    },
)
def set_vacation_response(
    is_enabled: bool,
    subject: str | None = None,
    text_body: str | None = None,
    html_body: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    client = _require_write()
    result = client.set_vacation_response(
        is_enabled=is_enabled, subject=subject,
        text_body=text_body, html_body=html_body,
        from_date=from_date, to_date=to_date,
    )
    return {"success": True, **result}


# ── Dispatch helper ────────────────────────────────────────────────────

_TOOL_MAP: dict[str, Callable] = {}


def _build_tool_map() -> None:
    if _TOOL_MAP:
        return
    for name, obj in globals().items():
        if callable(obj) and hasattr(obj, "tool_name"):
            _TOOL_MAP[obj.tool_name] = obj


def call_tool(name: str, arguments: dict[str, Any]) -> dict:
    """Dispatch a tool call by name. For use in LLM tool-calling loops."""
    _build_tool_map()
    func = _TOOL_MAP.get(name)
    if not func:
        return {"success": False, "error": f"Unknown tool: {name}"}
    return func(**arguments)
