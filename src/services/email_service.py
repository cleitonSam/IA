import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from src.core.config import logger
import os

SMTP_HOST = os.getenv("SMTP_ADDRESS", "smtp.hostinger.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USERNAME", "")
SMTP_PASS = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("MAILER_SENDER_EMAIL", "Antigravity IA <ti@fluxodigitaltech.com.br>")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


async def enviar_convite(email_destino: str, nome_empresa: str, token: str):
    link = f"{FRONTEND_URL}/register?token={token}"

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #0f172a; color: #e2e8f0; padding: 40px; border-radius: 16px;">
        <h1 style="color: #06b6d4; margin-bottom: 8px;">Antigravity IA</h1>
        <p style="color: #94a3b8; margin-bottom: 32px;">Dashboard de Gestão Revolucionária</p>

        <h2 style="color: #f1f5f9;">Você foi convidado!</h2>
        <p>Você recebeu um convite para acessar o dashboard da empresa <strong style="color: #06b6d4;">{nome_empresa}</strong>.</p>

        <p>Clique no botão abaixo para criar sua conta e começar a usar o sistema:</p>

        <a href="{link}" style="display: inline-block; background: #06b6d4; color: white; padding: 14px 28px; border-radius: 10px; text-decoration: none; font-weight: bold; margin: 24px 0;">
            Criar minha conta →
        </a>

        <p style="color: #64748b; font-size: 13px;">Este link expira em 48 horas. Se você não esperava este convite, ignore este e-mail.</p>

        <p style="color: #64748b; font-size: 12px; margin-top: 32px; border-top: 1px solid #1e293b; padding-top: 16px;">
            Link direto: {link}
        </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Convite para {nome_empresa} — Antigravity IA"
    msg["From"] = SMTP_FROM
    msg["To"] = email_destino
    msg.attach(MIMEText(html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASS,
            start_tls=True,
        )
        logger.info(f"✅ Convite enviado para {email_destino} (empresa: {nome_empresa})")
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao enviar convite para {email_destino}: {e}")
        return False
