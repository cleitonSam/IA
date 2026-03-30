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
PLATFORM_NAME     = os.getenv("PLATFORM_NAME", "Fluxo Digital Tech")
PLATFORM_LOGO_URL = os.getenv("PLATFORM_LOGO_URL", "")
SUPPORT_EMAIL     = os.getenv("SUPPORT_EMAIL", SMTP_FROM or "")


def _smtp_from_display() -> str:
    """Retorna o endereço From formatado com nome da plataforma."""
    if SMTP_FROM:
        return f"{PLATFORM_NAME} <{SMTP_FROM}>"
    return PLATFORM_NAME


# ── Ícone hexagonal SVG inline ──────────────────────────────────────────────
_HEX_ICON = """
<svg width="32" height="32" viewBox="0 0 32 32" fill="none"
     xmlns="http://www.w3.org/2000/svg" style="display:inline-block;vertical-align:middle;margin-right:10px;">
  <polygon points="16,2 28,9 28,23 16,30 4,23 4,9"
           fill="none" stroke="#06b6d4" stroke-width="1.5"/>
  <polygon points="16,7 24,11.5 24,20.5 16,25 8,20.5 8,11.5"
           fill="#06b6d4" opacity="0.15"/>
  <text x="16" y="21" text-anchor="middle"
        font-family="Arial,sans-serif" font-size="11" font-weight="700"
        fill="#06b6d4">FD</text>
</svg>"""


def _base_html_wrapper(content: str, extra_footer: str = "") -> str:
    """Template base Command Center — dark, moderno, identidade Fluxo Digital Tech."""

    support_html = ""
    if SUPPORT_EMAIL:
        support_html = (
            f' &middot; <a href="mailto:{SUPPORT_EMAIL}" '
            f'style="color:#06b6d4;text-decoration:none;">{SUPPORT_EMAIL}</a>'
        )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>{PLATFORM_NAME}</title>
</head>
<body style="margin:0;padding:0;background:#070d1a;font-family:'Segoe UI',Arial,sans-serif;">

  <!-- Wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#070d1a;min-height:100vh;">
    <tr>
      <td align="center" style="padding:40px 16px;">

        <!-- Card principal -->
        <table width="100%" cellpadding="0" cellspacing="0"
               style="max-width:580px;">

          <!-- Barra de acento ciano (topo) -->
          <tr>
            <td style="background:linear-gradient(90deg,#06b6d4,#3b82f6);
                        height:3px;border-radius:12px 12px 0 0;font-size:0;line-height:0;">
              &nbsp;
            </td>
          </tr>

          <!-- Cabeçalho -->
          <tr>
            <td style="background:#0a0f1e;padding:28px 40px 22px;
                        border-left:1px solid #1e293b;border-right:1px solid #1e293b;">
              <table cellpadding="0" cellspacing="0">
                <tr>
                  <td style="vertical-align:middle;">
                    {_HEX_ICON}
                  </td>
                  <td style="vertical-align:middle;">
                    <span style="color:#f1f5f9;font-size:20px;font-weight:700;
                                  letter-spacing:-0.3px;">{PLATFORM_NAME}</span>
                  </td>
                </tr>
              </table>
              <p style="margin:6px 0 0;color:#475569;font-size:12px;
                          letter-spacing:0.5px;text-transform:uppercase;">
                Sistema de Gestão com IA
              </p>
            </td>
          </tr>

          <!-- Corpo -->
          <tr>
            <td style="background:#0f172a;padding:36px 40px;
                        border-left:1px solid #1e293b;border-right:1px solid #1e293b;">
              {content}
            </td>
          </tr>

          <!-- Rodapé -->
          <tr>
            <td style="background:#0a0f1e;padding:20px 40px;
                        border-left:1px solid #1e293b;border-right:1px solid #1e293b;
                        border-bottom:1px solid #1e293b;
                        border-radius:0 0 12px 12px;">
              {extra_footer}
              <p style="margin:0;color:#334155;font-size:11px;text-align:center;">
                {PLATFORM_NAME}{support_html}
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
    Envia email de convite — design Command Center.
    - Branding Fluxo Digital Tech (hexagonal icon + gradiente ciano/azul)
    - Strip de destaques: IA 24/7, Insights, Multi-unidade
    - Retry automático até 3 tentativas com backoff exponencial
    - Link expira em 48 horas
    """
    link = f"{FRONTEND_URL}/register?token={token}"

    # ── Corpo do convite ──────────────────────────────────────────────────────
    content = f"""
      <!-- Título -->
      <h2 style="color:#f1f5f9;margin:0 0 6px;font-size:24px;font-weight:700;">
        Você foi convidado! 🎉
      </h2>
      <p style="color:#64748b;margin:0 0 20px;font-size:14px;">
        Você recebeu um convite para acessar o painel da empresa
        <strong style="color:#06b6d4;">{nome_empresa}</strong>.
      </p>

      <!-- Linha separadora -->
      <div style="height:1px;background:linear-gradient(90deg,#06b6d4 0%,transparent 100%);
                   margin:0 0 24px;"></div>

      <!-- Chamada para ação -->
      <p style="color:#cbd5e1;margin:0 0 24px;font-size:15px;">
        Clique no botão abaixo para criar sua conta:
      </p>

      <!-- Botão CTA -->
      <div style="text-align:center;margin:0 0 28px;">
        <a href="{link}"
           style="display:inline-block;
                  background:linear-gradient(135deg,#06b6d4 0%,#3b82f6 100%);
                  color:#ffffff;padding:15px 44px;border-radius:10px;
                  text-decoration:none;font-weight:700;font-size:16px;
                  letter-spacing:0.3px;
                  box-shadow:0 4px 20px rgba(6,182,212,0.35);">
          Criar minha conta &rarr;
        </a>
      </div>

      <!-- Expiração -->
      <p style="color:#475569;font-size:13px;margin:0 0 6px;text-align:center;">
        ⏱️ Este link expira em <strong style="color:#94a3b8;">48 horas</strong>.
      </p>
      <p style="color:#334155;font-size:12px;margin:0 0 28px;text-align:center;">
        Se você não esperava este convite, ignore este e-mail com segurança.
      </p>

      <!-- Strip de destaques -->
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#070d1a;border-radius:10px;overflow:hidden;
                     border:1px solid #1e293b;">
        <tr>

          <!-- Destaque 1 -->
          <td width="33%" style="padding:18px 12px;text-align:center;
                                   border-right:1px solid #1e293b;">
            <div style="font-size:22px;margin-bottom:6px;">⚡</div>
            <div style="color:#06b6d4;font-size:12px;font-weight:700;
                         letter-spacing:0.5px;margin-bottom:4px;">IA 24/7</div>
            <div style="color:#475569;font-size:11px;line-height:1.4;">
              Atendimento<br/>automatizado
            </div>
          </td>

          <!-- Destaque 2 -->
          <td width="33%" style="padding:18px 12px;text-align:center;
                                   border-right:1px solid #1e293b;">
            <div style="font-size:22px;margin-bottom:6px;">📊</div>
            <div style="color:#06b6d4;font-size:12px;font-weight:700;
                         letter-spacing:0.5px;margin-bottom:4px;">Insights</div>
            <div style="color:#475569;font-size:11px;line-height:1.4;">
              Métricas em<br/>tempo real
            </div>
          </td>

          <!-- Destaque 3 -->
          <td width="33%" style="padding:18px 12px;text-align:center;">
            <div style="font-size:22px;margin-bottom:6px;">🏢</div>
            <div style="color:#06b6d4;font-size:12px;font-weight:700;
                         letter-spacing:0.5px;margin-bottom:4px;">Multi-unidade</div>
            <div style="color:#475569;font-size:11px;line-height:1.4;">
              Gerencie todas<br/>as unidades
            </div>
          </td>

        </tr>
      </table>
    """

    # Link direto no rodapé (fallback)
    extra_footer = f"""
      <p style="color:#1e293b;font-size:10px;text-align:center;margin:0 0 10px;
                  word-break:break-all;">
        Link direto:
        <a href="{link}" style="color:#334155;text-decoration:none;">{link}</a>
      </p>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Convite para {nome_empresa} — {PLATFORM_NAME}"
    msg["From"]    = _smtp_from_display()
    msg["To"]      = email_destino
    msg.attach(MIMEText(_base_html_wrapper(content, extra_footer), "html"))

    return await _send_email(msg, f"convite:{email_destino}")


async def enviar_boas_vindas(email_destino: str, nome_usuario: str, nome_empresa: str) -> bool:
    """
    Envia email de boas-vindas após o usuário completar o registro.
    Mesmo design Command Center do convite.
    """
    dashboard_url = f"{FRONTEND_URL}/dashboard"
    primeiro_nome = nome_usuario.split()[0] if nome_usuario else "usuário"

    content = f"""
      <!-- Título -->
      <h2 style="color:#f1f5f9;margin:0 0 6px;font-size:24px;font-weight:700;">
        Bem-vindo, {primeiro_nome}! 🚀
      </h2>
      <p style="color:#64748b;margin:0 0 20px;font-size:14px;">
        Sua conta na empresa
        <strong style="color:#06b6d4;">{nome_empresa}</strong>
        foi criada com sucesso.
      </p>

      <!-- Linha separadora -->
      <div style="height:1px;background:linear-gradient(90deg,#06b6d4 0%,transparent 100%);
                   margin:0 0 24px;"></div>

      <!-- Próximos passos -->
      <div style="background:#070d1a;border-radius:10px;padding:20px 24px;
                   margin:0 0 28px;border:1px solid #1e293b;">
        <p style="color:#94a3b8;font-size:13px;margin:0 0 12px;font-weight:700;">
          🎯 Próximos passos:
        </p>
        <table cellpadding="0" cellspacing="0" width="100%">
          <tr>
            <td style="padding:5px 0;">
              <span style="color:#06b6d4;font-weight:700;margin-right:8px;">01</span>
              <span style="color:#94a3b8;font-size:13px;">Configure a personalidade da sua IA</span>
            </td>
          </tr>
          <tr>
            <td style="padding:5px 0;">
              <span style="color:#06b6d4;font-weight:700;margin-right:8px;">02</span>
              <span style="color:#94a3b8;font-size:13px;">Adicione as unidades da empresa</span>
            </td>
          </tr>
          <tr>
            <td style="padding:5px 0;">
              <span style="color:#06b6d4;font-weight:700;margin-right:8px;">03</span>
              <span style="color:#94a3b8;font-size:13px;">Configure os planos e preços</span>
            </td>
          </tr>
          <tr>
            <td style="padding:5px 0;">
              <span style="color:#06b6d4;font-weight:700;margin-right:8px;">04</span>
              <span style="color:#94a3b8;font-size:13px;">Conecte ao Chatwoot e ative a IA</span>
            </td>
          </tr>
        </table>
      </div>

      <!-- Botão CTA -->
      <div style="text-align:center;">
        <a href="{dashboard_url}"
           style="display:inline-block;
                  background:linear-gradient(135deg,#06b6d4 0%,#3b82f6 100%);
                  color:#ffffff;padding:15px 44px;border-radius:10px;
                  text-decoration:none;font-weight:700;font-size:16px;
                  letter-spacing:0.3px;
                  box-shadow:0 4px 20px rgba(6,182,212,0.35);">
          Acessar o Dashboard &rarr;
        </a>
      </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Bem-vindo ao {PLATFORM_NAME}, {primeiro_nome}!"
    msg["From"]    = _smtp_from_display()
    msg["To"]      = email_destino
    msg.attach(MIMEText(_base_html_wrapper(content), "html"))

    return await _send_email(msg, f"boas_vindas:{email_destino}")
