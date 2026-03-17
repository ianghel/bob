"""IMAP/SMTP email client for generic email accounts (WorkMail, etc.)."""

import asyncio
import email
import email.utils
import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from imaplib import IMAP4_SSL
from typing import Optional

logger = logging.getLogger(__name__)


def _imap_connect(host: str, port: int, username: str, password: str) -> IMAP4_SSL:
    """Connect and authenticate to an IMAP server."""
    ctx = ssl.create_default_context()
    conn = IMAP4_SSL(host, port, ssl_context=ctx)
    conn.login(username, password)
    return conn


def _parse_email_message(msg: email.message.Message, msg_id: str) -> dict:
    """Parse a raw email.message.Message into a clean dict."""
    # Decode subject
    subject_raw = msg.get("Subject", "")
    if subject_raw:
        decoded_parts = email.header.decode_header(subject_raw)
        subject = ""
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                subject += part.decode(charset or "utf-8", errors="replace")
            else:
                subject += part
    else:
        subject = ""

    # Sender
    sender = msg.get("From", "unknown")

    # To
    to = msg.get("To", "")

    # Date
    date_str = msg.get("Date", "")
    received_at = None
    if date_str:
        try:
            parsed = email.utils.parsedate_to_datetime(date_str)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            received_at = parsed.isoformat()
        except Exception:
            pass

    # Body (plain text only)
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and "attachment" not in (part.get("Content-Disposition") or ""):
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")

    # Attachments
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            disp = part.get("Content-Disposition")
            if disp and "attachment" in disp:
                fname = part.get_filename() or "unnamed"
                attachments.append({
                    "name": fname,
                    "type": part.get_content_type(),
                    "size": len(part.get_payload(decode=True) or b""),
                })

    return {
        "message_id": msg_id,
        "sender": sender,
        "to": to,
        "subject": subject,
        "body": body[:2000],
        "attachments": attachments,
        "received_at": received_at,
    }


async def fetch_imap_emails(
    host: str,
    port: int,
    username: str,
    password: str,
    folder: str = "INBOX",
    max_results: int = 20,
    unseen_only: bool = True,
) -> list[dict]:
    """Fetch emails from an IMAP server.

    Runs blocking IMAP calls in a thread executor.
    """

    def _fetch():
        conn = _imap_connect(host, port, username, password)
        try:
            conn.select(folder, readonly=True)
            criteria = "UNSEEN" if unseen_only else "ALL"
            _, data = conn.search(None, criteria)
            msg_ids = data[0].split()

            # Get latest N
            msg_ids = msg_ids[-max_results:] if len(msg_ids) > max_results else msg_ids

            results = []
            for mid in reversed(msg_ids):  # newest first
                _, msg_data = conn.fetch(mid, "(RFC822)")
                if msg_data and msg_data[0] and isinstance(msg_data[0], tuple):
                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)
                    # Use Message-ID header or IMAP UID as ID
                    email_id = msg.get("Message-ID", f"imap-{mid.decode()}")
                    results.append(_parse_email_message(msg, email_id))
            return results
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    return await asyncio.to_thread(_fetch)


async def fetch_imap_sent(
    host: str,
    port: int,
    username: str,
    password: str,
    max_results: int = 20,
) -> list[dict]:
    """Fetch sent emails from IMAP. Tries common sent folder names."""

    def _fetch():
        conn = _imap_connect(host, port, username, password)
        try:
            # Try common sent folder names
            sent_folders = ["Sent", "INBOX.Sent", "Sent Items", "Sent Messages", "[Gmail]/Sent Mail"]
            selected = None
            for folder in sent_folders:
                try:
                    status, _ = conn.select(f'"{folder}"', readonly=True)
                    if status == "OK":
                        selected = folder
                        break
                except Exception:
                    continue

            if not selected:
                return []

            _, data = conn.search(None, "ALL")
            msg_ids = data[0].split()
            msg_ids = msg_ids[-max_results:] if len(msg_ids) > max_results else msg_ids

            results = []
            for mid in reversed(msg_ids):
                _, msg_data = conn.fetch(mid, "(RFC822)")
                if msg_data and msg_data[0] and isinstance(msg_data[0], tuple):
                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)
                    email_id = msg.get("Message-ID", f"imap-sent-{mid.decode()}")
                    results.append(_parse_email_message(msg, email_id))
            return results
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

    return await asyncio.to_thread(_fetch)


async def send_smtp_email(
    host: str,
    port: int,
    username: str,
    password: str,
    from_addr: str,
    to: str,
    subject: str,
    body: str,
) -> None:
    """Send an email via SMTP (SSL)."""

    def _send():
        msg = MIMEMultipart()
        msg["From"] = from_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        ctx = ssl.create_default_context()
        # Try SSL first (port 465), fallback to STARTTLS (port 587)
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx) as server:
                server.login(username, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as server:
                server.starttls(context=ctx)
                server.login(username, password)
                server.send_message(msg)

    await asyncio.to_thread(_send)
    logger.info("SMTP email sent from %s to %s: %s", from_addr, to, subject)


async def test_imap_connection(
    host: str,
    port: int,
    username: str,
    password: str,
) -> bool:
    """Test IMAP connection. Returns True if successful."""

    def _test():
        conn = _imap_connect(host, port, username, password)
        conn.select("INBOX", readonly=True)
        conn.close()
        conn.logout()
        return True

    try:
        return await asyncio.to_thread(_test)
    except Exception as e:
        logger.error("IMAP connection test failed: %s", e)
        raise
