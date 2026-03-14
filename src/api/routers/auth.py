from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from src.core.config import logger, ACCESS_TOKEN_EXPIRE_MINUTES
from src.core.security import verify_password, create_access_token, get_current_user_token
from src.services.db_queries import buscar_usuario_por_email

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Endpoint de login que valida e-mail e senha e retorna um token JWT.
    """
    user = await buscar_usuario_por_email(form_data.username) # OAuth2 usa 'username' para o login field
    if not user or not verify_password(form_data.password, user['senha_hash']):
        logger.warning(f"⚠️ Tentativa de login falhou para email: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user['email'], "perfil": user['perfil'], "empresa_id": user['empresa_id']},
        expires_delta=access_token_expires
    )
    
    logger.info(f"✅ Usuário {user['email']} logado com sucesso.")
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me")
async def read_users_me(token_payload: dict = Depends(get_current_user_token)):
    """
    Retorna os dados básicos do usuário conectado.
    """
    # Como já validamos o token no Depends, apenas buscamos os dados frescos no DB se necessário
    # ou retornamos o que está no payload para performance.
    user = await buscar_usuario_por_email(token_payload.get("sub"))
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    return {
        "id": user['id'],
        "nome": user['nome'],
        "email": user['email'],
        "perfil": user['perfil'],
        "empresa_id": user['empresa_id']
    }
