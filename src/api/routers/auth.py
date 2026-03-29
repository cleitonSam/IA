import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from src.core.config import logger, ACCESS_TOKEN_EXPIRE_MINUTES
from src.core.security import verify_password, get_password_hash, create_access_token, get_current_user_token
from src.core.redis_client import redis_client
from src.services.db_queries import buscar_usuario_por_email, criar_usuario
from src.services.email_service import enviar_convite

router = APIRouter(prefix="/auth", tags=["auth"])

# Rate limit para login: máx 5 tentativas por IP por minuto
_LOGIN_RATE_LIMIT = 5
_LOGIN_RATE_WINDOW = 60  # segundos


# ---------- schemas ----------

class CriarEmpresaRequest(BaseModel):
    nome: str
    nome_fantasia: Optional[str] = None
    cnpj: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    website: Optional[str] = None
    plano: Optional[str] = None


class AtualizarEmpresaRequest(BaseModel):
    nome: Optional[str] = None
    nome_fantasia: Optional[str] = None
    cnpj: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    website: Optional[str] = None
    plano: Optional[str] = None
    status: Optional[str] = None

class ConviteRequest(BaseModel):
    email: str
    empresa_id: int

class RegisterRequest(BaseModel):
    token: str
    nome: str
    email: str
    senha: str


# ---------- helpers ----------

async def _buscar_empresa(empresa_id: int):
    import src.core.database as _database
    if not _database.db_pool:
        return None
    return await _database.db_pool.fetchrow("SELECT * FROM empresas WHERE id = $1", empresa_id)

async def _criar_empresa(body: "CriarEmpresaRequest") -> int:
    import src.core.database as _database
    import uuid as _uuid
    row = await _database.db_pool.fetchrow(
        """
        INSERT INTO empresas (uuid, nome, nome_fantasia, cnpj, email, telefone, website, plano, status, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'active', NOW())
        RETURNING id
        """,
        str(_uuid.uuid4()), body.nome, body.nome_fantasia, body.cnpj,
        body.email, body.telefone, body.website, body.plano
    )
    return row["id"]

async def _criar_convite(empresa_id: int, email: str) -> str:
    import src.core.database as _database
    token = secrets.token_hex(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=48)
    await _database.db_pool.execute(
        """
        INSERT INTO convites (empresa_id, email, token, expires_at)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (token) DO NOTHING
        """,
        empresa_id, email, token, expires
    )
    return token

async def _buscar_convite(token: str):
    import src.core.database as _database
    if not _database.db_pool:
        return None
    return await _database.db_pool.fetchrow(
        "SELECT * FROM convites WHERE token = $1 AND usado = false AND expires_at > NOW()",
        token
    )

async def _marcar_convite_usado(token: str):
    import src.core.database as _database
    await _database.db_pool.execute(
        "UPDATE convites SET usado = true WHERE token = $1",
        token
    )


# ---------- endpoints ----------

@router.post("/login")
async def login_for_access_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    # Rate limiting por IP
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"login_rate:{client_ip}"
    try:
        attempts = await redis_client.incr(rate_key)
        if attempts == 1:
            await redis_client.expire(rate_key, _LOGIN_RATE_WINDOW)
        if attempts > _LOGIN_RATE_LIMIT:
            logger.warning(f"🚫 Rate limit login excedido para IP {client_ip}")
            raise HTTPException(
                status_code=429,
                detail=f"Muitas tentativas de login. Aguarde {_LOGIN_RATE_WINDOW}s.",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # Se Redis falhar, permite login normalmente

    email_login = (form_data.username or "").strip().lower()
    senha_login = form_data.password or ""

    user = await buscar_usuario_por_email(email_login)
    if not user or not verify_password(senha_login, user['senha_hash']):
        logger.warning(f"⚠️ Login falhou: {email_login}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"sub": user['email'], "perfil": user['perfil'], "empresa_id": user['empresa_id']},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    logger.info(f"✅ Login: {user['email']}")
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me")
async def read_users_me(token_payload: dict = Depends(get_current_user_token)):
    user = await buscar_usuario_por_email(token_payload.get("sub"))
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return {
        "id": user['id'],
        "nome": user['nome'],
        "email": user['email'],
        "perfil": user['perfil'],
        "empresa_id": user['empresa_id'],
    }


@router.get("/empresas")
async def listar_empresas(token_payload: dict = Depends(get_current_user_token)):
    """Lista todas as empresas. Apenas admin_master."""
    if token_payload.get("perfil") != "admin_master":
        raise HTTPException(status_code=403, detail="Apenas admin_master pode listar empresas")
    import src.core.database as _database
    rows = await _database.db_pool.fetch(
        "SELECT id, uuid, nome, nome_fantasia, cnpj, email, telefone, website, plano, status, created_at FROM empresas ORDER BY id"
    )
    return [dict(r) for r in rows]


@router.post("/create-empresa", status_code=201)
async def create_empresa(
    body: CriarEmpresaRequest,
    token_payload: dict = Depends(get_current_user_token),
):
    """Cria uma nova empresa. Apenas admin_master pode usar."""
    if token_payload.get("perfil") != "admin_master":
        raise HTTPException(status_code=403, detail="Apenas admin_master pode criar empresas")
    empresa_id = await _criar_empresa(body)
    logger.info(f"✅ Empresa '{body.nome}' criada (id={empresa_id})")
    return {"empresa_id": empresa_id, "nome": body.nome}


@router.put("/empresas/{empresa_id}")
async def atualizar_empresa(
    empresa_id: int,
    body: AtualizarEmpresaRequest,
    token_payload: dict = Depends(get_current_user_token),
):
    """Atualiza dados de uma empresa. Apenas admin_master."""
    if token_payload.get("perfil") != "admin_master":
        raise HTTPException(status_code=403, detail="Apenas admin_master pode editar empresas")

    _CAMPOS_PERMITIDOS = {"nome", "nome_fantasia", "cnpj", "email", "telefone", "website", "plano", "status"}
    fields = {k: v for k, v in body.dict().items() if v is not None and k in _CAMPOS_PERMITIDOS}
    if not fields:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    import src.core.database as _database
    set_clause = ", ".join(f"{k} = ${i+1}" for i, k in enumerate(fields))
    values = list(fields.values()) + [empresa_id]
    await _database.db_pool.execute(
        f"UPDATE empresas SET {set_clause} WHERE id = ${len(values)}",
        *values
    )
    logger.info(f"✏️ Empresa id={empresa_id} atualizada")
    return {"message": "Empresa atualizada com sucesso"}


@router.delete("/empresas/{empresa_id}")
async def excluir_empresa(
    empresa_id: int,
    token_payload: dict = Depends(get_current_user_token),
):
    """Exclui uma empresa. Apenas admin_master."""
    if token_payload.get("perfil") != "admin_master":
        raise HTTPException(status_code=403, detail="Apenas admin_master pode excluir empresas")

    import src.core.database as _database
    row = await _database.db_pool.fetchrow("SELECT nome FROM empresas WHERE id = $1", empresa_id)
    if not row:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    try:
        await _database.db_pool.execute("DELETE FROM empresas WHERE id = $1", empresa_id)
        logger.info(f"🗑️ Empresa '{row['nome']}' (id={empresa_id}) excluída")
        return {"message": "Empresa excluída com sucesso"}
    except Exception:
        raise HTTPException(status_code=400, detail="Não é possível excluir esta empresa pois ela possui dados vinculados.")


@router.post("/invite", status_code=201)
async def send_invite(
    body: ConviteRequest,
    token_payload: dict = Depends(get_current_user_token),
):
    """Envia convite por e-mail para uma empresa existente. Apenas admin_master."""
    if token_payload.get("perfil") != "admin_master":
        raise HTTPException(status_code=403, detail="Apenas admin_master pode enviar convites")

    empresa = await _buscar_empresa(body.empresa_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa não encontrada. Crie a empresa antes de enviar o convite.")

    empresa_id = body.empresa_id

    token = await _criar_convite(empresa_id, body.email)
    enviado = await enviar_convite(body.email, empresa["nome"], token)

    import os
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    link = f"{frontend_url}/register?token={token}"

    logger.info(f"📨 Convite criado para {body.email} (empresa_id={empresa_id}, email_enviado={enviado}) link={link}")
    return {
        "message": f"Convite criado para {body.email}",
        "email_enviado": enviado,
        "link": link,
    }


@router.get("/invite/{token}")
async def check_invite(token: str):
    """Verifica se um token de convite é válido e retorna a empresa associada."""
    convite = await _buscar_convite(token)
    if not convite:
        raise HTTPException(status_code=404, detail="Convite inválido ou expirado")

    empresa = await _buscar_empresa(convite["empresa_id"])
    return {
        "email": convite["email"],
        "empresa_id": convite["empresa_id"],
        "empresa_nome": empresa["nome"] if empresa else "",
    }


@router.post("/register", status_code=201)
async def register(body: RegisterRequest):
    """Cadastra novo usuário via token de convite."""
    convite = await _buscar_convite(body.token)
    if not convite:
        raise HTTPException(status_code=400, detail="Convite inválido ou expirado")

    # Verifica e-mail: deve bater com o do convite
    if convite["email"].lower() != body.email.lower():
        raise HTTPException(status_code=400, detail="E-mail não corresponde ao convite")

    # Verifica se já existe usuário com esse e-mail
    existente = await buscar_usuario_por_email(body.email)
    if existente:
        raise HTTPException(status_code=409, detail="E-mail já cadastrado")

    senha_hash = get_password_hash(body.senha)
    ok = await criar_usuario(
        nome=body.nome,
        email=body.email,
        senha_hash=senha_hash,
        empresa_id=convite["empresa_id"],
        perfil="admin",
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Erro ao criar usuário")

    await _marcar_convite_usado(body.token)

    logger.info(f"✅ Usuário registrado: {body.email} (empresa_id={convite['empresa_id']})")
    return {"message": "Conta criada com sucesso. Faça login."}


@router.get("/usuarios")
async def listar_usuarios(
    empresa_id: Optional[int] = None,
    token_payload: dict = Depends(get_current_user_token),
):
    """Lista usuários. admin_master vê todos (ou filtra por empresa_id); outros veem só da sua empresa."""
    perfil = token_payload.get("perfil")
    if perfil != "admin_master":
        raise HTTPException(status_code=403, detail="Apenas admin_master pode listar usuários")

    import src.core.database as _database
    if empresa_id:
        rows = await _database.db_pool.fetch(
            """
            SELECT u.id, u.nome, u.email, u.perfil, u.ativo, u.empresa_id, e.nome as empresa_nome
            FROM usuarios u JOIN empresas e ON e.id = u.empresa_id
            WHERE u.empresa_id = $1 ORDER BY u.nome
            """, empresa_id
        )
    else:
        rows = await _database.db_pool.fetch(
            """
            SELECT u.id, u.nome, u.email, u.perfil, u.ativo, u.empresa_id, e.nome as empresa_nome
            FROM usuarios u JOIN empresas e ON e.id = u.empresa_id
            ORDER BY e.nome, u.nome
            """
        )
    return [dict(r) for r in rows]


@router.patch("/usuarios/{usuario_id}")
async def toggle_usuario(
    usuario_id: int,
    token_payload: dict = Depends(get_current_user_token),
):
    """Ativa ou desativa um usuário. Apenas admin_master."""
    if token_payload.get("perfil") != "admin_master":
        raise HTTPException(status_code=403, detail="Apenas admin_master pode alterar usuários")

    import src.core.database as _database
    row = await _database.db_pool.fetchrow("SELECT id, nome, ativo FROM usuarios WHERE id = $1", usuario_id)
    if not row:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    novo_status = not row["ativo"]
    await _database.db_pool.execute("UPDATE usuarios SET ativo = $1 WHERE id = $2", novo_status, usuario_id)
    acao = "ativado" if novo_status else "desativado"
    logger.info(f"👤 Usuário '{row['nome']}' (id={usuario_id}) {acao}")
    return {"ativo": novo_status, "message": f"Usuário {acao} com sucesso"}


@router.delete("/usuarios/{usuario_id}")
async def excluir_usuario(
    usuario_id: int,
    token_payload: dict = Depends(get_current_user_token),
):
    """Exclui um usuário. Apenas admin_master."""
    if token_payload.get("perfil") != "admin_master":
        raise HTTPException(status_code=403, detail="Apenas admin_master pode excluir usuários")

    import src.core.database as _database
    row = await _database.db_pool.fetchrow("SELECT nome FROM usuarios WHERE id = $1", usuario_id)
    if not row:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    await _database.db_pool.execute("DELETE FROM usuarios WHERE id = $1", usuario_id)
    logger.info(f"🗑️ Usuário '{row['nome']}' (id={usuario_id}) excluído")
    return {"message": "Usuário excluído com sucesso"}
