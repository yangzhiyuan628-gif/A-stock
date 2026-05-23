# -*- coding: utf-8 -*-
"""
邮件提醒工具：SMTP 发送交易信号提醒。
"""

from __future__ import annotations

import smtplib
import ssl
from email.mime.text import MIMEText
from email.header import Header


def send_email_alert(
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    sender: str,
    receiver: str,
    subject: str,
    body: str,
    use_ssl: bool = True,
) -> tuple[bool, str]:
    if not smtp_host or not smtp_port or not username or not password or not sender or not receiver:
        return False, "SMTP 配置不完整。"

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = Header(sender, "utf-8")
    msg["To"] = Header(receiver, "utf-8")
    msg["Subject"] = Header(subject, "utf-8")

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, int(smtp_port), context=context, timeout=12) as server:
                server.login(username, password)
                server.sendmail(sender, [x.strip() for x in receiver.split(",") if x.strip()], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, int(smtp_port), timeout=12) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(username, password)
                server.sendmail(sender, [x.strip() for x in receiver.split(",") if x.strip()], msg.as_string())
        return True, "邮件发送成功。"
    except Exception as exc:
        return False, f"邮件发送失败：{type(exc).__name__}: {exc}"
