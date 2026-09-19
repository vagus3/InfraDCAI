from __future__ import annotations

import smtplib
from email.message import EmailMessage

import httpx

from incidentops.config import settings
from incidentops.models import Incident


async def send_notification(incident: Incident, message: str) -> str:
    if settings.notify_webhook_url:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                settings.notify_webhook_url,
                json={"incident": incident.model_dump(mode="json"), "message": message},
            )
            response.raise_for_status()
        return "webhook"

    if settings.smtp_host and settings.smtp_from and settings.smtp_to:
        email = EmailMessage()
        email["Subject"] = f"[{incident.status.value}] {incident.id} {incident.title}"
        email["From"] = settings.smtp_from
        email["To"] = settings.smtp_to
        email.set_content(message)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(email)
        return "smtp"

    return "preview"
