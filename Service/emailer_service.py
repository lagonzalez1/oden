import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import os
import logging

from Core.unit_of_work import AbstractUnitOfWork

logger = logging.getLogger(__name__)


class EmailerService:
    def __init__(self, uow: Optional[AbstractUnitOfWork] = None):
        self.uow = uow
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", 587))
        self.smtp_username = os.getenv("SMTP_USERNAME")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.from_email = os.getenv("FROM_EMAIL", self.smtp_username)

    async def send_email(self, email: str, subject: str, body: str, html: bool = False):
        """
        Send an email to the specified recipient.

        Args:
            email: Recipient email address
            subject: Email subject line
            body: Email body content
            html: If True, send as HTML email; otherwise plain text
        """
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_email
            msg["To"] = email
            msg["Subject"] = subject

            if html:
                msg.attach(MIMEText(body, "html"))
            else:
                msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)

            logger.info(f"[EmailerService] Sent email to {email}: {subject}")

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"[EmailerService] SMTP auth failed: {e}")
            raise Exception(f"SMTP authentication failed: {str(e)}") from e

        except smtplib.SMTPException as e:
            logger.error(f"[EmailerService] SMTP error: {e}")
            raise Exception(f"SMTP error occurred: {str(e)}") from e

        except Exception as e:
            logger.error(f"[EmailerService] Failed to send email: {e}")
            raise Exception(f"Failed to send email: {str(e)}") from e
