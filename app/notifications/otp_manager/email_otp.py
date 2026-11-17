import asyncio
import html
import smtplib
from email.message import EmailMessage

from fastapi import HTTPException, status

from app.config import settings


def _from_address() -> str:
    return settings.otp_smtp_from.strip() or settings.otp_smtp_username.strip()


def smtp_configured() -> bool:
    return bool(settings.otp_smtp_host.strip() and _from_address())


def _test_html(recipient: str) -> str:
    safe = html.escape(recipient)
    return f"""\
<!DOCTYPE html>
<html lang="es">
  <body style="margin:0;padding:0;background:#fdfbf2;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fdfbf2;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:440px;background:#ffffff;border:1px solid #e7e1c8;border-radius:20px;overflow:hidden;">
            <tr>
              <td style="background:#59802c;padding:22px 28px 18px;">
                <p style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:22px;line-height:1.2;color:#fdfbf2;">Pa' La Jaba</p>
                <p style="margin:6px 0 0;font-family:Georgia,'Times New Roman',serif;font-size:13px;line-height:1.4;color:#f5c71a;">Prueba de correo</p>
              </td>
            </tr>
            <tr>
              <td style="height:6px;background:#f5c71a;font-size:0;line-height:0;">&nbsp;</td>
            </tr>
            <tr>
              <td style="padding:28px;">
                <p style="margin:0 0 12px;font-family:Georgia,'Times New Roman',serif;font-size:16px;line-height:1.5;color:#59802c;">El envío SMTP funciona.</p>
                <p style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:14px;line-height:1.5;color:#7b4c38;">Este mensaje de prueba llegó a {safe}.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def _deliver(recipient: str, subject: str, text: str, html_body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _from_address()
    message["To"] = recipient
    message.set_content(text)
    message.add_alternative(html_body, subtype="html")

    host = settings.otp_smtp_host.strip()
    port = settings.otp_smtp_port
    username = settings.otp_smtp_username.strip()
    password = settings.otp_smtp_password
    if settings.otp_smtp_use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if settings.otp_smtp_starttls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


async def send_test_email(email: str) -> None:
    recipient = str(email or "").strip()
    if "@" not in recipient or recipient.startswith("@") or recipient.endswith("@"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Escribe un correo válido.",
        )
    if not smtp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El correo SMTP no está configurado.",
        )
    try:
        await asyncio.to_thread(
            _deliver,
            recipient,
            "Prueba de correo de Pa' La Jaba",
            f"El envío SMTP funciona. Este mensaje de prueba llegó a {recipient}.\n",
            _test_html(recipient),
        )
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pudimos enviar el correo de prueba.",
        ) from exc
