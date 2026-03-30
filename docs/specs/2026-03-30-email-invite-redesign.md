# Email Invite Redesign — "Command Center"
**Data:** 2026-03-30
**Arquivo:** `src/services/email_service.py`

## Objetivo
Redesenhar o email de convite para refletir a identidade visual da plataforma Fluxo Digital Tech: dark, moderno, tech. Também se aplica ao email de boas-vindas.

## Design Aprovado: Command Center

### Seção 1 — Cabeçalho
- Barra de acento ciano (#06b6d4) de 3px no topo absoluto
- Fundo #0a0f1e (mais escuro que o corpo)
- Ícone geométrico hexagonal (SVG inline) em ciano + nome "Fluxo Digital Tech" em branco negrito
- Tagline "Sistema de Gestão com IA" em cinza

### Seção 2 — Corpo do convite
- Título "Você foi convidado! 🎉" em branco, fonte grande
- Subtítulo com nome da empresa em ciano
- Botão CTA centralizado: gradiente ciano→azul, "Criar minha conta →"
- Aviso de expiração 48h em cinza discreto

### Seção 3 — Strip de destaques (3 colunas)
- Fundo #0f172a, sem bordas, divisores verticais sutis
- ⚡ IA 24/7 — Atendimento automatizado
- 📊 Insights — Métricas em tempo real
- 🏢 Multi-unidade — Gerencie todas as unidades

### Seção 4 — Rodapé
- "Fluxo Digital Tech" + link de suporte centralizado
- Link direto do token em cinza discreto

## Variáveis de Ambiente Necessárias (backend EasyPanel)
```
PLATFORM_NAME=Fluxo Digital Tech
FRONTEND_URL=https://desk-ia-dev-front.5y4hfw.easypanel.host
SUPPORT_EMAIL=ti@fluxodigitaltech.com.br
```
