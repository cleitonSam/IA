import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from src.core.config import logger, ACCESS_TOKEN_EXPIRE_MINUTES
from src.core.security import verify_password, get_password_hash, create_access_token, get_current_user_token
from src.services.db_queries import buscar_usuario_por_email, criar_usuario
from src.services.email_service import enviar_convite

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------- schemas ----------

class CriarEmpresaRequest(BaseModel):
    nome: str
    nome_fantasia: Optional[str] = None
    cnpj: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None
    website: Optional[str] = None
    plano: Optional[str] = None

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
    from src.core.database import _database
    if not _database.db_pool:
        return None
    return await _database.db_pool.fetchrow("SELECT * FROM empresas WHERE id = $1", empresa_id)

async def _criar_empresa(body: "CriarEmpresaRequest") -> int:
    from src.core.database import _database
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
    from src.core.database import _database
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
    from src.core.database import _database
    if not _database.db_pool:
        return None
    return await _database.db_pool.fetchrow(
        "SELECT * FROM convites WHERE token = $1 AND usado = false AND expires_at > NOW()",
        token
    )

async def _marcar_convite_usado(token: str):
    from src.core.database import _database
    await _database.db_pool.execute(
        "UPDATE convites SET usado = true WHERE token = $1",
        token
    )


# ---------- endpoints ----------

@router.post("/login")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await buscar_usuario_por_email(form_data.username)
    if not user or not verify_password(form_data.password, user['senha_hash']):
        logger.warning(f"⚠️ Login falhou: {form_data.username}")
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
    from src.core.database import _database
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

    if not enviado:
        raise HTTPException(status_code=500, detail="Falha ao enviar e-mail. Verifique as configurações SMTP.")

    logger.info(f"📨 Convite enviado para {body.email} (empresa_id={empresa_id})")
    return {"message": f"Convite enviado para {body.email}"}


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
