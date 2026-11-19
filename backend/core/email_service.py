"""
SYSFIX Reusable Email Transport Service
Handles secure SMTP transmission, authentication, connection testing,
offline queueing, bounded retries, and audit history.
Implements the complete 10-step SMTP lifecycle with stage-by-stage tracking,
explicit STARTTLS SSL context validation, and actionable diagnostics.
Strictly enforces 'Cryptic' terminology and protects secret credentials.
"""

import os
import ssl
import smtplib
import socket
import logging
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Dict, Any, List, Optional, Tuple

from backend.database import (
    get_email_settings,
    record_email_delivery,
    enqueue_email,
    get_pending_email_queue,
    update_email_queue_status
)
from backend.core.credential_store import get_smtp_password, retrieve_smtp_credentials
from backend.core.cryptic import sanitize_report_text

logger = logging.getLogger("SYSFIX.EmailService")

DEFAULT_RECIPIENT = "karthikeyansa369@gmail.com"


def sanitize_smtp_password(password: Optional[str], host: str = "smtp.gmail.com", username: str = "") -> str:
    """
    Sanitize retrieved or user-entered SMTP passwords.
    For Gmail App Passwords, Google displays 16 characters in 4 space-separated groups
    (e.g. 'abcd efgh ijkl mnop'). Strip internal whitespace if 16-character code is detected.
    """
    if not password:
        return ""
    pwd = str(password).strip()
    is_gmail = "gmail.com" in (username or "").lower() or "smtp.gmail.com" in (host or "").lower()
    if is_gmail:
        collapsed = pwd.replace(" ", "").replace("\t", "").replace("\r", "").replace("\n", "")
        if len(collapsed) == 16 and collapsed.isalnum():
            return collapsed
    return pwd


def diagnose_smtp_environment(host: str = "smtp.gmail.com", port: int = 587, timeout: int = 10) -> Dict[str, Any]:
    """
    Diagnose Windows environmental conditions for outbound SMTP traffic:
    1. DNS resolution for smtp.gmail.com
    2. Outbound TCP reachability on target port (587)
    3. System date/time clock accuracy (prevents TLS certificate validity window errors)
    4. TLS handshake and certificate validation with system root CA store
    5. SMTP greeting & server capabilities check
    Distinguishes application credential issues from environmental/firewall blocks.
    Never exposes credentials or tokens.
    """
    results: Dict[str, Any] = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "host": host,
        "port": port,
        "dns": {"ok": False, "addresses": [], "error": ""},
        "tcp": {"ok": False, "error": ""},
        "clock": {"ok": False, "local_time": "", "year": 0, "error": ""},
        "tls": {"ok": False, "error": "", "auth_mechanisms": []},
        "healthy": False,
        "diagnostic_summary": ""
    }

    # 1. DNS Resolution
    try:
        resolved = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        addrs = list(set([r[4][0] for r in resolved]))
        results["dns"]["ok"] = True
        results["dns"]["addresses"] = addrs
    except Exception as e:
        results["dns"]["error"] = f"DNS resolution failed for '{host}': {str(e)}"
        results["diagnostic_summary"] = f"Unable to resolve {host}. Check DNS configuration, VPN, or internet connection."
        return results

    # 2. Outbound TCP Socket
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        results["tcp"]["ok"] = True
        sock.close()
    except Exception as e:
        results["tcp"]["error"] = f"TCP connection to {host}:{port} failed: {str(e)}"
        results["diagnostic_summary"] = f"Outbound port {port} is blocked or unreachable. Check Windows Firewall or antivirus network protection."
        return results

    # 3. System Date & Time Check
    now = datetime.now()
    results["clock"]["local_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
    results["clock"]["year"] = now.year
    if now.year < 2024:
        results["clock"]["error"] = f"System clock year ({now.year}) is out of date. TLS certificate validation will fail."
        results["diagnostic_summary"] = "System clock is incorrect. Synchronize Windows system clock."
        return results
    else:
        results["clock"]["ok"] = True

    # 4. TLS & SMTP Greeting
    server = None
    try:
        context = ssl.create_default_context()
        server = smtplib.SMTP(host, port, timeout=timeout)
        server.ehlo()
        if server.has_extn("STARTTLS"):
            server.starttls(context=context)
            server.ehlo()
            results["tls"]["ok"] = True
            auth_caps = server.esmtp_features.get("auth", "")
            results["tls"]["auth_mechanisms"] = auth_caps.split() if isinstance(auth_caps, str) else []
        else:
            results["tls"]["error"] = f"Server {host}:{port} does not advertise STARTTLS support."
    except Exception as e:
        results["tls"]["error"] = f"TLS handshake failed: {str(e)}"
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass

    if results["dns"]["ok"] and results["tcp"]["ok"] and results["clock"]["ok"] and results["tls"]["ok"]:
        results["healthy"] = True
        results["diagnostic_summary"] = f"Network path to {host}:{port} is fully operational with valid TLS negotiation."
    else:
        err = results["tls"]["error"] or results["tcp"]["error"] or results["dns"]["error"]
        results["diagnostic_summary"] = f"Environmental verification failed: {err}"

    return results


def create_authenticated_smtp_session(
    host: str,
    port: int,
    use_tls: bool,
    use_ssl: bool,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: int = 20
) -> Tuple[Optional[smtplib.SMTP], str, str]:
    """
    Executes the standard 10-step SMTP lifecycle with stage-by-stage tracking:
    1. Create valid default SSL context via ssl.create_default_context()
    2. Open smtplib.SMTP(host, port, timeout=20) (or SMTP_SSL if explicitly configured for port 465)
    3. Read and validate SMTP greeting
    4. Send EHLO
    5. Verify STARTTLS is supported
    6. Execute STARTTLS with the SSL context
    7. Send EHLO again after TLS negotiation
    8. Authenticate using configured username and retrieved Google App Password
    
    Returns: (server_instance, failed_stage, error_message)
    On success: (server, "", "")
    On failure: (None, failed_stage, actionable_error_message)
    Never exposes passwords, tokens, or sensitive message contents.
    """
    clean_user = (username or "").strip()
    clean_pwd = sanitize_smtp_password(password, host=host, username=clean_user)

    current_stage = "DNS resolution"
    server: Optional[smtplib.SMTP] = None

    try:
        # Step 1: DNS pre-check
        current_stage = "DNS resolution"
        try:
            socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror as dns_err:
            return None, current_stage, f"SMTP error at [DNS resolution]: Could not resolve SMTP server hostname '{host}'. Verify internet connection and DNS settings."

        # Step 2: Open SMTP connection
        # Port 587 uses smtplib.SMTP with STARTTLS (never SMTP_SSL on port 587)
        current_stage = "TCP connection"
        context = ssl.create_default_context()

        if use_ssl and port != 587:
            server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)

        # Step 3: Validate greeting banner
        current_stage = "SMTP greeting"
        # smtplib.SMTP connects in __init__; sock must be open
        if not getattr(server, "sock", None):
            return None, current_stage, f"SMTP error at [SMTP greeting]: Socket closed by server before greeting received ({host}:{port})."

        # Step 4: First EHLO before TLS
        current_stage = "EHLO/HELO before TLS"
        ehlo_res = server.ehlo()
        code = ehlo_res[0] if (isinstance(ehlo_res, tuple) and len(ehlo_res) > 0) else 250
        if isinstance(code, int) and code not in (250, 200):
            return None, current_stage, f"SMTP error at [EHLO/HELO before TLS]: Server rejected initial EHLO with code {code}."

        # Step 5 & 6: Verify and execute STARTTLS
        if use_tls and not (use_ssl and port != 587):
            current_stage = "STARTTLS capability check"
            has_starttls = server.has_extn("STARTTLS")
            if not has_starttls:
                return None, current_stage, f"SMTP error at [STARTTLS capability check]: Server {host}:{port} does not support STARTTLS."

            current_stage = "STARTTLS negotiation"
            tls_res = server.starttls(context=context)
            tls_code = tls_res[0] if (isinstance(tls_res, tuple) and len(tls_res) > 0) else 220
            if isinstance(tls_code, int) and tls_code not in (220, 250):
                return None, current_stage, f"SMTP error at [STARTTLS negotiation]: STARTTLS handshake rejected with status {tls_code}."

            # Step 7: Send EHLO again after TLS negotiation
            current_stage = "EHLO/HELO after TLS"
            post_res = server.ehlo()
            post_code = post_res[0] if (isinstance(post_res, tuple) and len(post_res) > 0) else 250
            if isinstance(post_code, int) and post_code not in (250, 200):
                return None, current_stage, f"SMTP error at [EHLO/HELO after TLS]: Post-TLS EHLO rejected with status {post_code}."

        # Step 8: Authenticate
        if clean_user and clean_pwd:
            current_stage = "SMTP authentication"
            try:
                server.login(clean_user, clean_pwd)
            except smtplib.SMTPAuthenticationError as auth_err:
                err_text = auth_err.smtp_error.decode("utf-8", errors="ignore") if isinstance(auth_err.smtp_error, bytes) else str(auth_err)
                return None, current_stage, (
                    f"SMTP error at [SMTP authentication]: Authentication failed ({err_text}). "
                    f"For Gmail (smtp.gmail.com), ensure 2-Step Verification is active and configure a valid 16-character Google App Password in Settings."
                )
            except smtplib.SMTPServerDisconnected:
                # Gmail abruptly terminates the TCP socket upon bad credentials in AUTH PLAIN
                return None, current_stage, (
                    f"SMTP error at [SMTP authentication]: Authentication failed: Connection closed by server during login. "
                    f"For Gmail (smtp.gmail.com), this indicates rejected credentials or an invalid Google App Password. "
                    f"Verify your Gmail address and 16-character Google App Password without spaces."
                )

        return server, "", ""

    except (socket.timeout, TimeoutError):
        if server:
            try:
                server.quit()
            except Exception:
                pass
        return None, current_stage, f"SMTP error at [{current_stage}]: Connection to {host}:{port} timed out after {timeout} seconds."

    except ConnectionRefusedError:
        if server:
            try:
                server.quit()
            except Exception:
                pass
        return None, current_stage, f"SMTP error at [{current_stage}]: Connection refused by {host}:{port}. Verify server address and port."

    except ssl.SSLError as ssl_err:
        if server:
            try:
                server.quit()
            except Exception:
                pass
        return None, current_stage, f"SMTP error at [{current_stage}]: SSL/TLS validation failed: {str(ssl_err)}. Verify Windows system date/time and root certificates."

    except smtplib.SMTPServerDisconnected as disc_err:
        if server:
            try:
                server.quit()
            except Exception:
                pass
        if current_stage == "SMTP authentication":
            remedy = "For Gmail, this indicates invalid credentials or an invalid Google App Password."
        else:
            remedy = "Verify network firewall, proxy, or antivirus email scanning."
        return None, current_stage, f"SMTP error at [{current_stage}]: Connection unexpectedly closed by server ({host}:{port}). {remedy}"

    except smtplib.SMTPConnectError as conn_err:
        if server:
            try:
                server.quit()
            except Exception:
                pass
        return None, current_stage, f"SMTP error at [{current_stage}]: Connection failed: {str(conn_err)}"

    except smtplib.SMTPException as smtp_err:
        if server:
            try:
                server.quit()
            except Exception:
                pass
        return None, current_stage, f"SMTP error at [{current_stage}]: {str(smtp_err)}"

    except Exception as e:
        if server:
            try:
                server.quit()
            except Exception:
                pass
        logger.error(f"Unexpected error in SMTP session at stage [{current_stage}]: {e}")
        return None, current_stage, f"SMTP error at [{current_stage}]: {str(e)}"


def test_smtp_connection(
    host: Optional[str] = None,
    port: Optional[int] = None,
    use_tls: Optional[bool] = None,
    use_ssl: Optional[bool] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    override_settings: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str]:
    """
    Test connectivity, STARTTLS negotiation, and authentication with the SMTP server.
    Does not send any email messages.
    Supports dictionary input, keyword arguments, or fallback to saved database settings and DPAPI vault.
    """
    if isinstance(host, dict) and override_settings is None:
        override_settings = host
        host = None

    settings = get_email_settings()
    creds = retrieve_smtp_credentials()

    target_host = host
    target_port = port
    target_tls = use_tls
    target_ssl = use_ssl
    target_user = username
    target_pwd = password

    if override_settings and isinstance(override_settings, dict):
        if "smtp_host" in override_settings or "host" in override_settings:
            target_host = override_settings.get("smtp_host") or override_settings.get("host")
        if "smtp_port" in override_settings or "port" in override_settings:
            target_port = override_settings.get("smtp_port") or override_settings.get("port")
        if "smtp_use_tls" in override_settings:
            target_tls = bool(override_settings["smtp_use_tls"])
        elif "use_tls" in override_settings:
            target_tls = bool(override_settings["use_tls"])
        if "smtp_use_ssl" in override_settings:
            target_ssl = bool(override_settings["smtp_use_ssl"])
        elif "use_ssl" in override_settings:
            target_ssl = bool(override_settings["use_ssl"])
        if "smtp_username" in override_settings or "username" in override_settings:
            target_user = override_settings.get("smtp_username") or override_settings.get("username")
        if "smtp_password" in override_settings or "password" in override_settings:
            raw_pwd = override_settings.get("smtp_password") or override_settings.get("password")
            if raw_pwd and raw_pwd != "••••••••" and not str(raw_pwd).startswith("••••"):
                target_pwd = str(raw_pwd)

    final_host = (target_host or settings.get("smtp_host") or "smtp.gmail.com").strip()
    try:
        final_port = int(target_port if target_port is not None else settings.get("smtp_port", 587))
    except (ValueError, TypeError):
        final_port = 587

    final_tls = target_tls if target_tls is not None else bool(settings.get("smtp_use_tls", True))
    final_ssl = target_ssl if target_ssl is not None else bool(settings.get("smtp_use_ssl", False))
    final_user = (target_user if target_user is not None else (settings.get("smtp_username") or creds.get("username") or "")).strip()
    final_pwd = target_pwd if target_pwd is not None else (creds.get("password") or get_smtp_password())
    if final_pwd:
        final_pwd = str(final_pwd).strip()

    if not final_host:
        return False, "SMTP server hostname is required."
    if not final_port or final_port <= 0:
        return False, "Valid SMTP port number is required."

    if final_user and not final_pwd:
        return False, "Authentication username was provided, but no password is saved in the secure vault or environment variables."

    # Execute full 8-step lifecycle up to authentication
    server, stage, err_msg = create_authenticated_smtp_session(
        host=final_host,
        port=final_port,
        use_tls=final_tls,
        use_ssl=final_ssl,
        username=final_user,
        password=final_pwd,
        timeout=20
    )

    if server:
        # Step 10: Clean quit
        try:
            server.quit()
        except Exception:
            pass
        return True, f"Successfully connected, negotiated STARTTLS, and authenticated with {final_host}:{final_port}."
    else:
        return False, err_msg


def send_email_message(
    subject: str,
    body_html: str,
    body_text: Optional[str] = None,
    recipient: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    alert_type: str = "GENERAL",
    allow_queue: bool = True
) -> Tuple[bool, str]:
    """
    Send an email message via configured SMTP parameters.
    Implements full 10-step lifecycle:
    1-8. Validated connection, STARTTLS with SSL context, and authentication.
    9. Message transmission and inspection of server response.
    10. Clean quit.
    Bounded retries for transient errors; immediate fail without duplicate attempts for permanent auth/config errors.
    Attachments list format: [{'filename': '...', 'content': '...', 'mime_type': 'text/html'}]
    """
    settings = get_email_settings()
    creds = retrieve_smtp_credentials()
    target_recipient = (recipient or settings.get("recipient_email") or DEFAULT_RECIPIENT).strip()
    username = (settings.get("smtp_username") or creds.get("username") or "").strip()
    sender_email = (settings.get("smtp_sender") or username or DEFAULT_RECIPIENT).strip()
    host = (settings.get("smtp_host") or "smtp.gmail.com").strip()
    try:
        port = int(settings.get("smtp_port", 587))
    except (ValueError, TypeError):
        port = 587
    use_tls = bool(settings.get("smtp_use_tls", True))
    use_ssl = bool(settings.get("smtp_use_ssl", False))
    password = creds.get("password") or get_smtp_password()
    if password:
        password = str(password).strip()

    if not sender_email:
        err = "Sender email address is not configured. Please configure email settings in SYSFIX."
        record_email_delivery(alert_type, target_recipient, subject, "FAILED", err)
        return False, err

    if not password:
        err = "SMTP authentication credentials are not saved in the secure vault or environment variables. Please configure a Google App Password in Settings."
        record_email_delivery(alert_type, target_recipient, subject, "FAILED", err)
        return False, err

    # Strictly sanitize user-facing report content with Cryptic terminology
    sanitized_html = sanitize_report_text(body_html)
    sanitized_subject = sanitize_report_text(subject)

    # Build Multipart Email
    msg = MIMEMultipart("mixed")
    msg["From"] = sender_email
    msg["To"] = target_recipient
    msg["Subject"] = sanitized_subject

    # Alternative HTML/Text body
    alt_part = MIMEMultipart("alternative")
    if body_text:
        alt_part.attach(MIMEText(sanitize_report_text(body_text), "plain", "utf-8"))
    alt_part.attach(MIMEText(sanitized_html, "html", "utf-8"))
    msg.attach(alt_part)

    # Attachments
    if attachments:
        for att in attachments:
            fname = att.get("filename", "report.txt")
            content = att.get("content", "")
            if isinstance(content, str):
                content = sanitize_report_text(content)
                payload_bytes = content.encode("utf-8")
            else:
                payload_bytes = content

            part = MIMEBase("application", "octet-stream")
            part.set_payload(payload_bytes)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
            msg.attach(part)

    # Transmission with Bounded Retries
    max_retries = 3
    retry_delays = [2, 5, 8]
    last_error = ""

    for attempt in range(max_retries):
        server = None
        try:
            # Steps 1 to 8: Unified session initialization
            server, failed_stage, err_msg = create_authenticated_smtp_session(
                host=host,
                port=port,
                use_tls=use_tls,
                use_ssl=use_ssl,
                username=username,
                password=password,
                timeout=20
            )

            if not server:
                last_error = err_msg
                # If authentication failed or DNS is permanently missing, do NOT retry
                if failed_stage in ("SMTP authentication", "DNS resolution"):
                    logger.warning(f"Delivery aborted on {failed_stage}: {err_msg}")
                    break
                else:
                    logger.warning(f"Delivery attempt {attempt + 1}/{max_retries} failed at [{failed_stage}]: {err_msg}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delays[attempt])
                    continue

            # Step 9: Send the message and inspect server response
            current_stage = "Message transmission"
            try:
                refused = server.sendmail(sender_email, [target_recipient], msg.as_string())
                if isinstance(refused, dict) and len(refused) > 0:
                    last_error = f"SMTP error at [RCPT TO]: Server refused recipients: {refused}"
                    break
            except smtplib.SMTPRecipientsRefused as rec_err:
                last_error = f"SMTP error at [RCPT TO]: Recipient rejected by server: {str(rec_err)}"
                break
            except smtplib.SMTPSenderRefused as send_err:
                last_error = f"SMTP error at [MAIL FROM]: Sender rejected by server: {str(send_err)}"
                break
            except smtplib.SMTPDataError as data_err:
                last_error = f"SMTP error at [DATA transmission]: Message body rejected by server: {str(data_err)}"
                break
            except smtplib.SMTPServerDisconnected:
                last_error = f"SMTP error at [Message transmission]: Connection closed by server while transmitting message body ({host}:{port})."
                if attempt < max_retries - 1:
                    time.sleep(retry_delays[attempt])
                    continue
                break

            # Step 10: Clean quit
            try:
                server.quit()
            except Exception:
                pass

            # Mark SENT only after SMTP server accepts the message
            logger.info(f"Successfully dispatched '{sanitized_subject}' to {target_recipient}")
            record_email_delivery(alert_type, target_recipient, sanitized_subject, "SENT", "", attempt)
            return True, f"Email delivered successfully to {target_recipient}."

        except Exception as e:
            last_error = f"SMTP error at [Transmission]: {str(e)}"
            logger.warning(f"Delivery attempt {attempt + 1}/{max_retries} failed: {last_error}")
            if attempt < max_retries - 1:
                time.sleep(retry_delays[attempt])
        finally:
            if server:
                try:
                    server.quit()
                except Exception:
                    pass

    # Record delivery failure in SQLite audit history
    record_email_delivery(alert_type, target_recipient, sanitized_subject, "FAILED", last_error, max_retries)
    if allow_queue:
        import json
        att_meta = []
        if attachments:
            for a in attachments:
                att_meta.append({"filename": a.get("filename"), "content": a.get("content")})
        enqueue_email(alert_type, target_recipient, sanitized_subject, sanitized_html, body_text or "", json.dumps(att_meta))
        logger.info(f"Queued email for offline retry: '{sanitized_subject}'")

    return False, f"Failed to deliver email: {last_error}"


def process_offline_email_queue() -> int:
    """Process pending queued emails and attempt redelivery."""
    pending = get_pending_email_queue(limit=5)
    if not pending:
        return 0

    delivered_count = 0
    for item in pending:
        q_id = item["id"]
        import json
        attachments = []
        try:
            if item.get("attachments_json"):
                attachments = json.loads(item["attachments_json"])
        except Exception:
            pass

        success, msg = send_email_message(
            subject=item["subject"],
            body_html=item["body_html"],
            body_text=item.get("body_text"),
            recipient=item["recipient"],
            attachments=attachments,
            alert_type=item.get("alert_type", "QUEUED_RETRY"),
            allow_queue=False
        )
        if success:
            update_email_queue_status(q_id, "DELIVERED")
            delivered_count += 1
            logger.info(f"Queued email #{q_id} delivered successfully.")
        else:
            update_email_queue_status(q_id, "PENDING", last_error=msg, retry_increment=True)
            logger.warning(f"Queued email #{q_id} retry attempt failed: {msg}")

    return delivered_count


# Backward-compatible alias
process_email_queue = process_offline_email_queue


def send_test_email(recipient: Optional[str] = None) -> Tuple[bool, str]:
    """
    Send an immediate test email to verify credentials and SMTP deliverability.
    Uses the shared SMTP transport and verifies the full 10-step lifecycle.
    """
    settings = get_email_settings()
    target = (recipient or settings.get("recipient_email") or DEFAULT_RECIPIENT).strip()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = f"SYSFIX Test Email — {now_str}"
    body_html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0F172A; color: #F8FAFC; padding: 24px; border-radius: 8px;">
      <h2 style="color: #7C83FF; margin-top: 0;">SYSFIX SMTP Test Notification</h2>
      <p style="font-size: 14px; color: #CBD5E1;">This test email confirms that your outgoing SMTP transport configuration and Windows DPAPI credential vault are working properly.</p>
      <div style="background: #1E293B; padding: 14px; border-radius: 6px; margin: 16px 0; border: 1px solid #334155; font-size: 13px;">
        <div><strong>Timestamp:</strong> {now_str}</div>
        <div><strong>Recipient:</strong> {target}</div>
        <div><strong>Security:</strong> Windows DPAPI Vault Protected</div>
        <div><strong>Status:</strong> Verified Active</div>
      </div>
      <p style="font-size: 12px; color: #94A3B8;">SYSFIX — Complete Windows System Diagnostics &amp; Health Monitoring Application</p>
    </div>
    """
    return send_email_message(
        subject=subject,
        body_html=body_html,
        recipient=target,
        alert_type="TEST_EMAIL",
        allow_queue=False
    )


def retry_queued_email(queue_id: int) -> Tuple[bool, str]:
    """
    Attempt immediate redelivery of a specific offline queued email item.
    """
    from backend.database import get_connection
    import json
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM email_queue WHERE id = ?", (queue_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return False, f"Queued email #{queue_id} not found."

    item = dict(row)
    attachments = []
    try:
        if item.get("attachments_json"):
            attachments = json.loads(item["attachments_json"])
    except Exception:
        pass

    success, msg = send_email_message(
        subject=item["subject"],
        body_html=item["body_html"],
        body_text=item.get("body_text"),
        recipient=item["recipient"],
        attachments=attachments,
        alert_type=item.get("alert_type", "QUEUED_RETRY"),
        allow_queue=False
    )

    if success:
        update_email_queue_status(queue_id, "DELIVERED")
        return True, "Queued message delivered successfully."
    else:
        update_email_queue_status(queue_id, "PENDING", last_error=msg, retry_increment=True)
        return False, f"Retry attempt failed: {msg}"
