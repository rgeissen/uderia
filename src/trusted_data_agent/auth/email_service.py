"""
Email service for sending verification emails.

Supports SendGrid, SMTP, and AWS SES. Extends easily for additional providers.
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

logger = logging.getLogger("quart.app")


class EmailProvider(ABC):
    """Abstract base class for email providers."""

    @abstractmethod
    async def send(self, to_email: str, subject: str, html_body: str) -> bool:
        """
        Send an email.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_body: Email body in HTML format

        Returns:
            True if sent successfully, False otherwise
        """
        pass


class SMTPEmailProvider(EmailProvider):
    """SMTP email provider (supports Gmail, Outlook, custom SMTP servers)."""

    def __init__(self):
        self.smtp_host = os.getenv('SMTP_HOST')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_username = os.getenv('SMTP_USERNAME')
        self.smtp_password = os.getenv('SMTP_PASSWORD')
        self.from_email = os.getenv('SMTP_FROM_EMAIL', self.smtp_username)

        if not all([self.smtp_host, self.smtp_username, self.smtp_password]):
            raise ValueError("SMTP_HOST, SMTP_USERNAME, and SMTP_PASSWORD are required")

    async def send(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send email via SMTP."""
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = to_email

            # Attach HTML body
            msg.attach(MIMEText(html_body, 'html'))

            # Send email
            logger.info(f"Attempting to send email via SMTP to {to_email} using {self.smtp_host}:{self.smtp_port} as {self.smtp_username}")
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                logger.debug("Connected to SMTP server")
                server.starttls()
                logger.debug("TLS enabled")
                server.login(self.smtp_username, self.smtp_password)
                logger.debug("Authentication successful")
                server.send_message(msg)
                logger.debug("Message sent")

            logger.info(f"✓ Email sent via SMTP to {to_email}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"✗ SMTP Authentication failed for {self.smtp_username} on {self.smtp_host}:{self.smtp_port}: {e}")
            return False
        except Exception as e:
            logger.error(f"✗ Error sending email via SMTP: {e}", exc_info=True)
            return False


class SendGridEmailProvider(EmailProvider):
    """SendGrid email provider."""

    def __init__(self):
        self.api_key = os.getenv('SENDGRID_API_KEY')
        self.from_email = os.getenv('SENDGRID_FROM_EMAIL')

        if not all([self.api_key, self.from_email]):
            raise ValueError("SENDGRID_API_KEY and SENDGRID_FROM_EMAIL are required")

    async def send(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send email via SendGrid."""
        try:
            import httpx

            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }

            payload = {
                'personalizations': [{'to': [{'email': to_email}]}],
                'from': {'email': self.from_email},
                'subject': subject,
                'content': [{'type': 'text/html', 'value': html_body}]
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    'https://api.sendgrid.com/v3/mail/send',
                    json=payload,
                    headers=headers,
                    timeout=10.0
                )

                if response.status_code in [200, 202]:
                    logger.info(f"Email sent via SendGrid to {to_email}")
                    return True
                else:
                    logger.error(f"SendGrid error: {response.status_code} - {response.text}")
                    return False

        except Exception as e:
            logger.error(f"Error sending email via SendGrid: {e}", exc_info=True)
            return False


class AWSSesSESEmailProvider(EmailProvider):
    """AWS SES (Simple Email Service) provider."""

    def __init__(self):
        self.region = os.getenv('AWS_SES_REGION', 'us-east-1')
        self.from_email = os.getenv('AWS_SES_FROM_EMAIL')

        if not self.from_email:
            raise ValueError("AWS_SES_FROM_EMAIL is required for AWS SES")

    async def send(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send email via AWS SES."""
        try:
            import boto3

            client = boto3.client('ses', region_name=self.region)

            response = client.send_email(
                Source=self.from_email,
                Destination={'ToAddresses': [to_email]},
                Message={
                    'Subject': {'Data': subject},
                    'Body': {'Html': {'Data': html_body}}
                }
            )

            logger.info(f"Email sent via AWS SES to {to_email}, MessageId: {response['MessageId']}")
            return True

        except Exception as e:
            logger.error(f"Error sending email via AWS SES: {e}", exc_info=True)
            return False


class EmailService:
    """Unified email service that delegates to configured provider."""

    _provider: Optional[EmailProvider] = None

    @classmethod
    def get_provider(cls) -> Optional[EmailProvider]:
        """Get or initialize the configured email provider."""
        if cls._provider is not None:
            return cls._provider

        provider_name = os.getenv('EMAIL_PROVIDER', '').lower()

        try:
            if provider_name == 'sendgrid':
                cls._provider = SendGridEmailProvider()
            elif provider_name == 'smtp':
                cls._provider = SMTPEmailProvider()
            elif provider_name == 'aws_ses':
                cls._provider = AWSSesSESEmailProvider()
            else:
                logger.warning(f"Email provider '{provider_name}' not configured or not recognized")
                return None

            return cls._provider

        except ValueError as e:
            logger.error(f"Error initializing email provider: {e}")
            return None

    @staticmethod
    async def send_verification_email(
        to_email: str,
        verification_token: str,
        verification_link: str,
        user_name: str
    ) -> bool:
        """
        Send email verification email.

        Args:
            to_email: Recipient email address
            verification_token: Verification token (for fallback verification)
            verification_link: Full verification link (with token)
            user_name: User's name for personalization

        Returns:
            True if sent successfully, False otherwise
        """
        provider = EmailService.get_provider()
        if not provider:
            logger.warning("Email provider not configured, verification email not sent")
            return False

        subject = "Verify Your Email Address"
        
        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
                    .content {{ padding: 20px 0; }}
                    .button {{ display: inline-block; background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                    .footer {{ font-size: 12px; color: #666; margin-top: 20px; border-top: 1px solid #eee; padding-top: 10px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>Welcome, {user_name}!</h2>
                    </div>
                    <div class="content">
                        <p>Thank you for registering. To complete your signup, please verify your email address by clicking the button below:</p>
                        <a href="{verification_link}" class="button">Verify Email Address</a>
                        <p>Or copy and paste this link in your browser:</p>
                        <p><code>{verification_link}</code></p>
                        <p>This link expires in 24 hours.</p>
                    </div>
                    <div class="footer">
                        <p>If you didn't create this account, you can safely ignore this email.</p>
                        <p>&copy; 2026 Trusted Data Agent. All rights reserved.</p>
                    </div>
                </div>
            </body>
        </html>
        """

        return await provider.send(to_email, subject, html_body)

    @staticmethod
    async def send_email(
        to_email: str,
        subject: str,
        html_body: str
    ) -> bool:
        """
        Send a custom email.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_body: Email body in HTML format

        Returns:
            True if sent successfully, False otherwise
        """
        provider = EmailService.get_provider()
        if not provider:
            logger.warning("Email provider not configured, email not sent")
            return False

        return await provider.send(to_email, subject, html_body)

    @staticmethod
    async def send_password_reset_email(
        to_email: str,
        reset_link: str,
        user_name: str
    ) -> bool:
        """
        Send password reset email.

        Args:
            to_email: Recipient email address
            reset_link: Full password reset link (with token)
            user_name: User's name for personalization

        Returns:
            True if sent successfully, False otherwise
        """
        provider = EmailService.get_provider()
        if not provider:
            logger.warning("Email provider not configured, password reset email not sent")
            return False

        subject = "Reset Your Password"

        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
                    .content {{ padding: 20px 0; }}
                    .button {{ display: inline-block; background-color: #F15F22; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                    .footer {{ font-size: 12px; color: #666; margin-top: 20px; border-top: 1px solid #eee; padding-top: 10px; }}
                    .warning {{ background-color: #fff3cd; border: 1px solid #ffc107; padding: 10px; border-radius: 5px; margin: 15px 0; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>Password Reset Request</h2>
                    </div>
                    <div class="content">
                        <p>Hello {user_name},</p>
                        <p>We received a request to reset your password. Click the button below to create a new password:</p>
                        <a href="{reset_link}" class="button">Reset Password</a>
                        <p>Or copy and paste this link in your browser:</p>
                        <p><code>{reset_link}</code></p>
                        <div class="warning">
                            <strong>Important:</strong> This link expires in 1 hour for security reasons.
                        </div>
                    </div>
                    <div class="footer">
                        <p>If you didn't request a password reset, you can safely ignore this email. Your password will not be changed.</p>
                        <p>&copy; 2026 Uderia Platform. All rights reserved.</p>
                    </div>
                </div>
            </body>
        </html>
        """

        return await provider.send(to_email, subject, html_body)
