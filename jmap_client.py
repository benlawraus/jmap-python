"""High-level JMAP email client wrapping jmapc with caching and simplified returns."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import mimetypes
from pathlib import Path

from jmapc import (
    Address,
    Client,
    Comparator,
    Email,
    EmailAddress,
    EmailBodyPart,
    EmailBodyValue,
    EmailHeader,
    EmailQueryFilterCondition,
    EmailSubmission,
    Envelope,
    Ref,
)
from jmapc.methods import (
    CustomMethod,
    CustomResponse,
    EmailGet,
    EmailGetResponse,
    EmailQuery,
    EmailQueryResponse,
    EmailSet,
    EmailSetResponse,
    EmailSubmissionSet,
    EmailSubmissionSetResponse,
    IdentityGet,
    IdentityGetResponse,
    MailboxGet,
    MailboxGetResponse,
    MailboxQuery,
    MailboxQueryResponse,
    SearchSnippetGet,
    SearchSnippetGetResponse,
    ThreadGet,
    ThreadGetResponse,
)
from jmapc import MailboxQueryFilterCondition


class JMAPError(Exception):
    pass


class JMAPMailClient:
    def __init__(self, host: str, api_token: str):
        self.client = Client.create_with_api_token(host=host, api_token=api_token)
        self._mailboxes: list[dict] | None = None
        self._mailbox_by_role: dict[str, dict] | None = None
        self._mailbox_by_name: dict[str, dict] | None = None
        self._identities: list[dict] | None = None

    # ── Mailbox cache ──────────────────────────────────────────────────

    def _ensure_mailboxes(self) -> None:
        if self._mailboxes is not None:
            return
        results = self.client.request(MailboxGet(ids=None))
        if not isinstance(results, MailboxGetResponse):
            raise JMAPError(f"Failed to fetch mailboxes: {results}")
        self._mailboxes = []
        self._mailbox_by_role = {}
        self._mailbox_by_name = {}
        for mb in results.data:
            d = {
                "id": mb.id,
                "name": mb.name,
                "role": mb.role,
                "parent_id": mb.parent_id,
                "total_emails": mb.total_emails,
                "unread_emails": mb.unread_emails,
                "total_threads": mb.total_threads,
                "unread_threads": mb.unread_threads,
                "sort_order": mb.sort_order,
            }
            self._mailboxes.append(d)
            if mb.role:
                self._mailbox_by_role[mb.role] = d
            if mb.name:
                self._mailbox_by_name[mb.name.lower()] = d

    def get_mailboxes(self) -> list[dict]:
        self._ensure_mailboxes()
        return self._mailboxes  # type: ignore

    def get_mailbox_id_by_role(self, role: str) -> str | None:
        self._ensure_mailboxes()
        mb = self._mailbox_by_role.get(role)  # type: ignore
        return mb["id"] if mb else None

    def refresh_mailboxes(self) -> None:
        self._mailboxes = None
        self._mailbox_by_role = None
        self._mailbox_by_name = None
        self._ensure_mailboxes()

    # ── Identity cache ─────────────────────────────────────────────────

    def _ensure_identities(self) -> None:
        if self._identities is not None:
            return
        result = self.client.request(IdentityGet())
        if not isinstance(result, IdentityGetResponse):
            raise JMAPError(f"Failed to fetch identities: {result}")
        self._identities = []
        for ident in result.data:
            self._identities.append({
                "id": ident.id,
                "name": ident.name,
                "email": ident.email,
                "reply_to": ident.reply_to,
                "text_signature": ident.text_signature,
                "html_signature": ident.html_signature,
                "may_delete": ident.may_delete,
            })

    def get_identities(self) -> list[dict]:
        self._ensure_identities()
        return self._identities  # type: ignore

    def get_default_identity(self) -> dict:
        self._ensure_identities()
        if not self._identities:
            raise JMAPError("No identities found on the server")
        return self._identities[0]

    # ── Email operations ───────────────────────────────────────────────

    def search_emails(
        self,
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
        before: datetime | None = None,
        after: datetime | None = None,
        limit: int = 20,
        sort_order: str = "desc",
    ) -> dict:
        filter_args: dict[str, Any] = {}
        if query:
            filter_args["text"] = query
        if from_addr:
            filter_args["mail_from"] = from_addr
        if to_addr:
            filter_args["to"] = to_addr
        if cc_addr:
            filter_args["cc"] = cc_addr
        if bcc_addr:
            filter_args["bcc"] = bcc_addr
        if subject:
            filter_args["header"] = ["Subject", subject]
        if body:
            filter_args["body"] = body
        if in_mailbox:
            filter_args["in_mailbox"] = in_mailbox
        if has_keyword:
            filter_args["has_keyword"] = has_keyword
        if not_keyword:
            filter_args["not_keyword"] = not_keyword
        if has_attachment is not None:
            filter_args["has_attachment"] = has_attachment
        if before:
            filter_args["before"] = before
        if after:
            filter_args["after"] = after

        filt = EmailQueryFilterCondition(**filter_args) if filter_args else None

        results = self.client.request([
            EmailQuery(
                filter=filt,
                sort=[Comparator(property="receivedAt", is_ascending=(sort_order == "asc"))],
                limit=limit,
                collapse_threads=True,
            ),
            EmailGet(
                ids=Ref("/ids"),
                properties=[
                    "id", "threadId", "from", "to", "subject", "receivedAt",
                    "preview", "keywords", "hasAttachment", "mailboxIds",
                ],
            ),
        ])

        query_resp = results[0].response
        email_resp = results[1].response

        if not isinstance(query_resp, EmailQueryResponse):
            raise JMAPError(f"Email query failed: {query_resp}")
        if not isinstance(email_resp, EmailGetResponse):
            raise JMAPError(f"Email get failed: {email_resp}")

        emails = []
        for e in email_resp.data:
            emails.append(self._email_summary(e))

        return {
            "total": query_resp.total,
            "emails": emails,
        }

    def get_email(self, email_id: str, format: str = "text") -> dict:
        fetch_text = format == "text"
        fetch_html = format == "html"

        result = self.client.request(
            EmailGet(
                ids=[email_id],
                properties=[
                    "id", "threadId", "messageId", "inReplyTo", "references",
                    "from", "to", "cc", "bcc", "replyTo", "subject",
                    "receivedAt", "sentAt", "keywords", "mailboxIds",
                    "hasAttachment", "preview", "textBody", "htmlBody",
                    "attachments", "bodyValues",
                ],
                fetch_text_body_values=fetch_text,
                fetch_html_body_values=fetch_html,
                max_body_value_bytes=None,
            )
        )
        if not isinstance(result, EmailGetResponse):
            raise JMAPError(f"Email get failed: {result}")
        if not result.data:
            raise JMAPError(f"Email {email_id} not found")

        e = result.data[0]
        body_text = ""
        body_parts = e.text_body if fetch_text else e.html_body
        if body_parts and e.body_values:
            for part in body_parts:
                if part.part_id and part.part_id in e.body_values:
                    body_text += e.body_values[part.part_id].value or ""

        attachments = []
        if e.attachments:
            for att in e.attachments:
                attachments.append({
                    "name": att.name,
                    "type": att.type,
                    "size": att.size,
                    "blob_id": att.blob_id,
                })

        return {
            "id": e.id,
            "thread_id": e.thread_id,
            "message_id": e.message_id,
            "in_reply_to": e.in_reply_to,
            "references": e.references,
            "from": self._addresses(e.mail_from),
            "to": self._addresses(e.to),
            "cc": self._addresses(e.cc),
            "bcc": self._addresses(e.bcc),
            "reply_to": self._addresses(e.reply_to),
            "subject": e.subject,
            "received_at": e.received_at.isoformat() if e.received_at else None,
            "sent_at": e.sent_at.isoformat() if e.sent_at else None,
            "body": body_text,
            "attachments": attachments,
            "keywords": list(e.keywords.keys()) if e.keywords else [],
            "mailbox_ids": list(e.mailbox_ids.keys()) if e.mailbox_ids else [],
            "has_attachment": e.has_attachment,
            "preview": e.preview,
        }

    def get_thread(self, thread_id: str) -> dict:
        results = self.client.request([
            ThreadGet(ids=[thread_id]),
            EmailGet(
                ids=Ref("/emailIds"),
                properties=[
                    "id", "threadId", "from", "to", "subject", "receivedAt",
                    "preview", "keywords", "hasAttachment",
                ],
            ),
        ])

        thread_resp = results[0].response
        email_resp = results[1].response

        if not isinstance(thread_resp, ThreadGetResponse):
            raise JMAPError(f"Thread get failed: {thread_resp}")
        if not isinstance(email_resp, EmailGetResponse):
            raise JMAPError(f"Email get failed: {email_resp}")

        if not thread_resp.data:
            raise JMAPError(f"Thread {thread_id} not found")

        emails = [self._email_summary(e) for e in email_resp.data]

        return {
            "thread_id": thread_id,
            "emails": emails,
        }

    # ── Blob operations ────────────────────────────────────────────────

    def download_attachment(
        self, email_id: str, blob_id: str, file_name: str | None = None,
        output_dir: str | None = None,
    ) -> dict:
        result = self.client.request(
            EmailGet(
                ids=[email_id],
                properties=["attachments"],
            )
        )
        if not isinstance(result, EmailGetResponse):
            raise JMAPError(f"Email get failed: {result}")
        if not result.data:
            raise JMAPError(f"Email {email_id} not found")

        email = result.data[0]
        attachment = None
        if email.attachments:
            for att in email.attachments:
                if att.blob_id == blob_id:
                    attachment = att
                    break
        if not attachment:
            raise JMAPError(f"Attachment with blob_id {blob_id} not found on email {email_id}")

        base_name = file_name or attachment.name or blob_id
        # Ensure the file has an appropriate extension for its MIME type
        base_path = Path(base_name)
        if not base_path.suffix and attachment.type:
            ext = mimetypes.guess_extension(attachment.type) or ""
            base_name = base_name + ext

        attachments_dir = Path(output_dir) if output_dir else Path("attachments")
        attachments_dir.mkdir(parents=True, exist_ok=True)
        dest = attachments_dir / base_name

        self.client.download_attachment(attachment, dest)
        return {
            "path": str(dest.resolve()),
            "name": attachment.name,
            "type": attachment.type,
            "size": attachment.size,
        }

    def upload_blob(self, file_path: str) -> dict:
        path = Path(file_path)
        if not path.exists():
            raise JMAPError(f"File not found: {file_path}")
        blob = self.client.upload_blob(path)
        return {
            "blob_id": blob.id,
            "type": blob.type,
            "size": blob.size,
        }

    # ── Email mutations ────────────────────────────────────────────────

    def mark_read(self, email_id: str, is_read: bool = True) -> None:
        patch = {"keywords/$seen": True} if is_read else {"keywords/$seen": None}
        result = self.client.request(
            EmailSet(update={email_id: patch})
        )
        if not isinstance(result, EmailSetResponse):
            raise JMAPError(f"Mark read failed: {result}")
        if result.not_updated:
            raise JMAPError(f"Mark read failed: {result.not_updated}")

    def mark_flagged(self, email_id: str, is_flagged: bool = True) -> None:
        patch = {"keywords/$flagged": True} if is_flagged else {"keywords/$flagged": None}
        result = self.client.request(
            EmailSet(update={email_id: patch})
        )
        if not isinstance(result, EmailSetResponse):
            raise JMAPError(f"Mark flagged failed: {result}")
        if result.not_updated:
            raise JMAPError(f"Mark flagged failed: {result.not_updated}")

    def move_email(self, email_id: str, to_mailbox_id: str) -> None:
        result = self.client.request(
            EmailSet(update={email_id: {"mailboxIds": {to_mailbox_id: True}}})
        )
        if not isinstance(result, EmailSetResponse):
            raise JMAPError(f"Move failed: {result}")
        if result.not_updated:
            raise JMAPError(f"Move failed: {result.not_updated}")

    def delete_email(self, email_id: str, permanent: bool = False) -> None:
        if permanent:
            result = self.client.request(
                EmailSet(destroy=[email_id])
            )
            if not isinstance(result, EmailSetResponse):
                raise JMAPError(f"Delete failed: {result}")
            if result.not_destroyed:
                raise JMAPError(f"Delete failed: {result.not_destroyed}")
        else:
            trash_id = self.get_mailbox_id_by_role("trash")
            if not trash_id:
                raise JMAPError("Trash mailbox not found")
            self.move_email(email_id, trash_id)

    def send_email(
        self,
        to: list[dict[str, str]],
        subject: str,
        body: str,
        cc: list[dict[str, str]] | None = None,
        bcc: list[dict[str, str]] | None = None,
        in_reply_to: list[str] | None = None,
        references: list[str] | None = None,
        identity_id: str | None = None,
        is_html: bool = False,
        extra_headers: list[dict[str, str]] | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> dict:
        if not identity_id:
            ident = self.get_default_identity()
            identity_id = ident["id"]
            sender_name = ident["name"]
            sender_email = ident["email"]
        else:
            self._ensure_identities()
            ident = next(
                (i for i in self._identities if i["id"] == identity_id),  # type: ignore
                None,
            )
            if not ident:
                raise JMAPError(f"Identity {identity_id} not found")
            sender_name = ident["name"]
            sender_email = ident["email"]

        drafts_id = self.get_mailbox_id_by_role("drafts")
        if not drafts_id:
            raise JMAPError("Drafts mailbox not found")
        sent_id = self.get_mailbox_id_by_role("sent")

        to_addrs = [EmailAddress(name=a.get("name"), email=a["email"]) for a in to]
        cc_addrs = [EmailAddress(name=a.get("name"), email=a["email"]) for a in cc] if cc else None
        bcc_addrs = [EmailAddress(name=a.get("name"), email=a["email"]) for a in bcc] if bcc else None

        all_recipients = list(to)
        if cc:
            all_recipients.extend(cc)
        if bcc:
            all_recipients.extend(bcc)

        body_type = "text/html" if is_html else "text/plain"

        email_kwargs: dict[str, Any] = {
            "mail_from": [EmailAddress(name=sender_name, email=sender_email)],
            "to": to_addrs,
            "cc": cc_addrs,
            "bcc": bcc_addrs,
            "subject": subject,
            "keywords": {"$seen": True, "$draft": True},
            "mailbox_ids": {drafts_id: True},
            "body_values": {"body": EmailBodyValue(value=body)},
            "in_reply_to": in_reply_to,
            "references": references,
            "headers": [EmailHeader(name=h["name"], value=h["value"]) for h in extra_headers] if extra_headers else None,
        }

        if attachments:
            # With attachments, must use body_structure (multipart/mixed)
            text_part = EmailBodyPart(part_id="body", type=body_type)
            att_parts = [
                EmailBodyPart(
                    blob_id=att["blob_id"],
                    type=att.get("type", "application/octet-stream"),
                    name=att.get("name"),
                    disposition="attachment",
                )
                for att in attachments
            ]
            email_kwargs["body_structure"] = EmailBodyPart(
                type="multipart/mixed",
                sub_parts=[text_part] + att_parts,
            )
        else:
            if is_html:
                email_kwargs["html_body"] = [EmailBodyPart(part_id="body", type=body_type)]
            else:
                email_kwargs["text_body"] = [EmailBodyPart(part_id="body", type=body_type)]

        email_obj = Email(**email_kwargs)

        on_success_update: dict[str, Any] = {
            "#emailToSend": {
                f"mailboxIds/{drafts_id}": None,
                "keywords/$draft": None,
            }
        }
        if sent_id:
            on_success_update["#emailToSend"][f"mailboxIds/{sent_id}"] = True

        results = self.client.request([
            EmailSet(create={"draft": email_obj}),
            EmailSubmissionSet(
                on_success_update_email=on_success_update,
                create={
                    "emailToSend": EmailSubmission(
                        email_id="#draft",
                        identity_id=identity_id,
                        envelope=Envelope(
                            mail_from=Address(email=sender_email),
                            rcpt_to=[Address(email=a["email"]) for a in all_recipients],
                        ),
                    )
                },
            ),
        ])

        email_set_resp = results[0].response
        sub_resp = results[1].response

        if not isinstance(email_set_resp, EmailSetResponse):
            raise JMAPError(f"Email creation failed: {email_set_resp}")
        if email_set_resp.not_created:
            raise JMAPError(f"Email creation failed: {email_set_resp.not_created}")

        if not isinstance(sub_resp, EmailSubmissionSetResponse):
            raise JMAPError(f"Email submission failed: {sub_resp}")
        if sub_resp.not_created:
            raise JMAPError(f"Email submission failed: {sub_resp.not_created}")

        created_email = email_set_resp.created.get("draft") if email_set_resp.created else None
        created_sub = sub_resp.created.get("emailToSend") if sub_resp.created else None

        return {
            "email_id": created_email.id if created_email else None,
            "submission_id": created_sub.id if created_sub else None,
            "sent_at": str(created_sub.send_at) if created_sub and created_sub.send_at else None,
        }

    def reply_to_email(
        self,
        email_id: str,
        body: str,
        reply_all: bool = True,
        is_html: bool = False,
    ) -> dict:
        original = self.get_email(email_id, format="text")

        ident = self.get_default_identity()
        my_email = ident["email"].lower()

        to_addrs = original.get("reply_to") or original.get("from") or []

        cc_addrs: list[dict[str, str]] = []
        if reply_all:
            for addr_list in [original.get("to", []), original.get("cc", [])]:
                for addr in addr_list:
                    if addr["email"].lower() != my_email:
                        cc_addrs.append(addr)

        subject = original.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        in_reply_to = original.get("message_id")
        refs = list(original.get("references") or [])
        if original.get("message_id"):
            refs.extend(original["message_id"])

        return self.send_email(
            to=to_addrs,
            subject=subject,
            body=body,
            cc=cc_addrs or None,
            in_reply_to=in_reply_to,
            references=refs or None,
            is_html=is_html,
        )

    def forward_email(
        self,
        email_id: str,
        to: list[dict[str, str]],
        body: str | None = None,
        is_html: bool = False,
    ) -> dict:
        original = self.get_email(email_id, format="html" if is_html else "text")

        subject = original.get("subject", "")
        if not subject.lower().startswith("fwd:"):
            subject = f"Fwd: {subject}"

        from_str = ", ".join(
            f"{a.get('name', '')} <{a['email']}>" for a in (original.get("from") or [])
        )
        date_str = original.get("sent_at") or original.get("received_at") or ""

        original_body = original.get("body", "")
        if is_html:
            quoted = (
                f"<br><br>---------- Forwarded message ----------<br>"
                f"From: {from_str}<br>Date: {date_str}<br>"
                f"Subject: {original.get('subject', '')}<br><br>"
                f"{original_body}"
            )
            full_body = (body or "") + quoted
        else:
            quoted = (
                f"\n\n---------- Forwarded message ----------\n"
                f"From: {from_str}\nDate: {date_str}\n"
                f"Subject: {original.get('subject', '')}\n\n"
                f"{original_body}"
            )
            full_body = (body or "") + quoted

        refs = list(original.get("references") or [])
        if original.get("message_id"):
            refs.extend(original["message_id"])

        return self.send_email(
            to=to,
            subject=subject,
            body=full_body,
            references=refs or None,
            is_html=is_html,
        )

    # ── Vacation response (via CustomMethod) ───────────────────────────

    def get_vacation_response(self) -> dict:
        method = CustomMethod(data={"accountId": self.client.account_id, "ids": ["singleton"]})
        method.jmap_method = "VacationResponse/get"
        method.using = {"urn:ietf:params:jmap:vacationresponse"}

        result = self.client.request(method)
        if isinstance(result, CustomResponse):
            data_list = result.data.get("list", []) if result.data else []
            if data_list:
                vr = data_list[0]
                return {
                    "is_enabled": vr.get("isEnabled", False),
                    "subject": vr.get("subject"),
                    "text_body": vr.get("textBody"),
                    "html_body": vr.get("htmlBody"),
                    "from_date": vr.get("fromDate"),
                    "to_date": vr.get("toDate"),
                }
        return {
            "is_enabled": False,
            "subject": None,
            "text_body": None,
            "html_body": None,
            "from_date": None,
            "to_date": None,
        }

    def set_vacation_response(
        self,
        is_enabled: bool,
        subject: str | None = None,
        text_body: str | None = None,
        html_body: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict:
        update: dict[str, Any] = {"isEnabled": is_enabled}
        if subject is not None:
            update["subject"] = subject
        if text_body is not None:
            update["textBody"] = text_body
        if html_body is not None:
            update["htmlBody"] = html_body
        if from_date is not None:
            update["fromDate"] = from_date
        if to_date is not None:
            update["toDate"] = to_date

        method = CustomMethod(data={
            "accountId": self.client.account_id,
            "update": {"singleton": update},
        })
        method.jmap_method = "VacationResponse/set"
        method.using = {"urn:ietf:params:jmap:vacationresponse"}

        result = self.client.request(method)
        return self.get_vacation_response()

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _addresses(addrs: list[EmailAddress] | None) -> list[dict[str, str]]:
        if not addrs:
            return []
        return [{"name": a.name or "", "email": a.email or ""} for a in addrs]

    @staticmethod
    def _email_summary(e: Email) -> dict:
        keywords = list(e.keywords.keys()) if e.keywords else []
        return {
            "id": e.id,
            "thread_id": e.thread_id,
            "from": [{"name": a.name or "", "email": a.email or ""} for a in (e.mail_from or [])],
            "to": [{"name": a.name or "", "email": a.email or ""} for a in (e.to or [])],
            "subject": e.subject,
            "date": e.received_at.isoformat() if e.received_at else None,
            "preview": e.preview,
            "is_read": "$seen" in keywords,
            "is_flagged": "$flagged" in keywords,
            "has_attachment": e.has_attachment,
            "mailbox_ids": list(e.mailbox_ids.keys()) if e.mailbox_ids else [],
        }
