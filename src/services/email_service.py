import asyncio
import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from src.core.config import logger
import os

SMTP_HOST     = os.getenv("SMTP_ADDRESS", "smtp.hostinger.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USERNAME", "")
SMTP_PASS     = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM     = os.getenv("MAILER_SENDER_EMAIL", "")
FRONTEND_URL  = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Identidade da plataforma — configurável por env var
PLATFORM_NAME     = os.getenv("PLATFORM_NAME", "Motor IA")
PLATFORM_LOGO_URL = os.getenv("PLATFORM_LOGO_URL", "")
SUPPORT_EMAIL     = os.getenv("SUPPORT_EMAIL", SMTP_FROM or "")


def _smtp_from_display() -> str:
    """Retorna o endereço From formatado com nome da plataforma."""
    if SMTP_FROM:
        return f"{PLATFORM_NAME} <{SMTP_FROM}>"
    return PLATFORM_NAME


def _base_html_wrapper(content: str) -> str:
    """Template base responsivo para todos os emails."""
    logo_html = ""
    if PLATFORM_LOGO_URL:
        logo_html = f'<img src="{PLATFORM_LOGO_URL}" alt="{PLATFORM_NAME}" style="height:40px;margin-bottom:8px;" />'

    support_line = ""
    if SUPPORT_EMAIL:
        support_line = f' &middot; Dúvidas? <a href="mailto:{SUPPORT_EMAIL}" style="color:#06b6d4;">{SUPPORT_EMAIL}</a>'

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{PLATFORM_NAME}</title>
</head>
<body style="margin:0;padding:0;background:#0f172a;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table width="100%" style="max-width:600px;background:#1e293b;border-radius:16px;overflow:hidden;">
          <tr>
            <td style="background:#0f172a;padding:32px 40px 24px;border-bottom:1px solid #334155;">
              {logo_html}
              <h1 style="margin:0;color:#06b6d4;font-size:22px;font-weight:700;">{PLATFORM_NAME}</h1>
              <p style="margin:4px 0 0;color:#64748b;font-size:13px;">Sistema de Gestão com IA</p>
            </td>
          </tr>
          <tr>
            <td style="padding:32px 40px;">
              {content}
            </td>
          </tr>
          <tr>
            <td style="background:#0f172a;padding:20px 40px;border-top:1px solid #334155;">
              <p style="margin:0;color:#475569;font-size:12px;text-align:center;">
                {PLATFORM_NAME}{support_line}
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


async def _send_email(msg: MIMEMultipart, log_tag: str, retries: int = 3) -> bool:
    """
    Envia um email com retry automático (até 3 tentativas, backoff exponencial).
    Retorna True em sucesso, False se todas as tentativas falharem.
    """
    for attempt in range(1, retries + 1):
        try:
            await aiosmtplib.send(
                msg,
                hostname=SMTP_HOST,
                port=SMTP_PORT,
                username=SMTP_USER,
                password=SMTP_PASS,
                start_tls=True,
                timeout=30,
            )
            logger.info(f"✅ Email enviado ({log_tag}) — tentativa {attempt}")
            return True
        except aiosmtplib.SMTPAuthenticationError as e:
            logger.error(f"❌ Email: credenciais SMTP inválidas ({log_tag}): {e}")
            return False  # Não adianta retry em erros de autenticação
        except Exception as e:
            logger.warning(f"⚠️ Email tentativa {attempt}/{retries} ({log_tag}): {type(e).__name__}: {e}")
            if attempt < retries:
                await asyncio.sleep(2 ** attempt)  # backoff: 2s, 4s
    logger.error(f"❌ Email falhou após {retries} tentativas ({log_tag})")
    return False


async def enviar_convite(email_destino: str, nome_empresa: str, token: str) -> bool:
    """
    Envia email de convite para acesso ao dashboard.
    - Branding dinâmico via PLATFORM_NAME / PLATFORM_LOGO_URL
    - Retry automático até 3 tentativas com backoff exponencial
    - Link expira em 48 horas
    """
    link = f"{FRONTEND_URL}/register?token={token}"

    content = f"""
      <h2 style="color:#f1f5f9;margin:0 0 8px;">Você foi convidado! 🎉</h2>
      <p style="color:#94a3b8;margin:0 0 24px;font-size:15px;">
        Você recebeu um convite para acessar o painel da empresa
        <strong style="color:#06b6d4;">{nome_empresa}</strong>.
      </p>
      <p style="color:#cbd5e1;margin:0 0 28px;font-size:15px;">
        Clique no botão abaixo para criar sua conta:
      </p>
      <div style="text-align:center;margin:0 0 32px;">
        <a href="{link}"
           style="display:inline-block;background:linear-gradient(135deg,#06b6d4,#3b82f6);
                  color:white;padding:14px 36px;border-radius:10px;
                  text-decoration:none;font-weight:700;font-size:16px;">
          Criar minha conta →
        </a>
      </div>
      <p style="color:#475569;font-size:13px;margin:0 0 8px;">
        ⏱️ Este link expira em <strong>48 horas</strong>.
      </p>
      <p style="color:#475569;font-size:13px;margin:0 0 16px;">
        Se você não esperava este convite, ignore este e-mail com segurança.
      </p>
      <div style="padding-top:16px;border-top:1px solid #334155;">
        <p style="color:#334155;font-size:11px;margin:0;">
          Link direto: <a href="{link}" style="color:#475569;word-break:break-all;">{link}</a>
        </p>
      </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Convite para {nome_empresa} — {PLATFORM_NAME}"
    msg["From"]    = _smtp_from_display()
    msg["To"]      = email_destino
    msg.attach(MIMEText(_base_html_wrapper(content), "html"))

    return await _send_email(msg, f"convite:{email_destino}")


async def enviar_boas_vindas(email_destino: str, nome_usuario: str, nome_empresa: str) -> bool:
    """
    Envia email de boas-vindas após o usuário completar o registro.
    Novo! Chamado pelo endpoint de registro após criação da conta.
    """
    dashboard_url = f"{FRONTEND_URL}/dashboard"
    primeiro_nome = nome_usuario.split()[0] if nome_usuario else "usuário"

    content = f"""
      <h2 style="color:#f1f5f9;margin:0 0 8px;">Bem-vindo, {primeiro_nome}! 🚀</h2>
      <p style="color:#94a3b8;margin:0 0 24px;font-size:15px;">
        Sua conta na empresa <strong style="color:#06b6d4;">{nome_empresa}</strong>
        foi criada com sucesso. O {PLATFORM_NAME} está pronto para transformar seu atendimento.
      </p>
      <div style="background:#0f172a;border-radius:12px;padding:20px;margin:0 0 28px;">
        <p style="color:#94a3b8;font-size:13px;margin:0 0 12px;">
          🎯 <strong style="color:#e2e8f0;">Próximos passos:</strong>
        </p>
        <ol style="color:#94a3b8;font-size:14px;margin:0;padding-left:20px;line-height:1.8;">
          <li>Configure a personalidade da sua IA</li>
          <li>Adicione as unidades da empresa</li>
          <li>Configure os planos e preços</li>
          <li>Conecte ao Chatwoot e ative a IA</li>
        </ol>
      </div>
      <div style="text-align:center;">
        <a href="{dashboard_url}"
           style="display:inline-block;background:linear-gradient(135deg,#06b6d4,#3b82f6);
                  color:white;padding:14px 36px;border-radius:10px;
                  text-decoration:none;font-weight:700;font-size:16px;">
          Acessar o Dashboard →
        </a>
      </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Bem-vindo ao {PLATFORM_NAME}, {primeiro_nome}!"
    msg["From"]    = _smtp_from_display()
    msg["To"]      = email_destino
    msg.attach(MIMEText(_base_html_wrapper(content), "html"))

    return await _send_email(msg, f"boas_vindas:{email_destino}")
