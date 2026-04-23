"""Fixtures compartilhadas dos testes."""
import os
import pytest

# Defaults para os testes nao quebrarem por falta de env
os.environ.setdefault("DATABASE_URL", "postgres://postgres:test@localhost:5432/ia_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-jwt-secret-chave-de-teste-com-mais-de-32-chars-aqui-ok",
)


@pytest.fixture
def sample_token_payload_admin():
    return {
        "sub": "admin@empresa1.com",
        "perfil": "admin",
        "empresa_id": 1,
        "exp": 9999999999,
    }


@pytest.fixture
def sample_token_payload_master():
    return {
        "sub": "master@fluxo.com",
        "perfil": "admin_master",
        "empresa_id": None,
        "exp": 9999999999,
    }
