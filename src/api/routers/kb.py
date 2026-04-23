"""
[MKT-04] Router KB — endpoints para gerenciar knowledge base.

Endpoints:
  POST /api/kb/crawl        { url, max_pages, max_depth }
  POST /api/kb/upload-pdf   multipart file=...
  POST /api/kb/ingest-text  { titulo, texto, categoria }
  GET  /api/kb              lista itens
  DELETE /api/kb/{id}       soft-delete
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, HttpUrl

from src.core.config import logger
from src.core.tenant import require_tenant
from src.middleware.rate_limit import rate_limit
from src.services.kb_ingestion import crawl_site, ingest_pdf, ingest_text
from src.services.rag_service import listar_conhecimento, deletar_conhecimento


router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])


class CrawlRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=500)
    max_pages: int = Field(30, ge=1, le=100)
    max_depth: int = Field(2, ge=1, le=3)


class IngestTextRequest(BaseModel):
    titulo: str = Field(..., min_length=3, max_length=200)
    texto: str = Field(..., min_length=20, max_length=200_000)
    categoria: str = Field("manual", max_length=50)


@router.post(
    "/crawl",
    dependencies=[Depends(rate_limit(key="kb_crawl", max_calls=5, window=3600))],
)
async def api_crawl(body: CrawlRequest, tenant: dict = Depends(require_tenant)):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    stats = await crawl_site(
        empresa_id=empresa_id,
        start_url=body.url,
        max_pages=body.max_pages,
        max_depth=body.max_depth,
    )
    logger.info(f"[kb.crawl] empresa={empresa_id} url={body.url} -> {stats}")
    return stats


@router.post(
    "/upload-pdf",
    dependencies=[Depends(rate_limit(key="kb_upload", max_calls=20, window=3600))],
)
async def api_upload_pdf(
    file: UploadFile = File(...),
    tenant: dict = Depends(require_tenant),
):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")

    # Limite de tamanho
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:  # 20MB
        raise HTTPException(status_code=413, detail="PDF maior que 20MB")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Apenas arquivos .pdf")

    stats = await ingest_pdf(
        empresa_id=empresa_id,
        pdf_bytes=data,
        titulo=file.filename,
    )
    logger.info(f"[kb.upload_pdf] empresa={empresa_id} file={file.filename} -> {stats}")
    return stats


@router.post("/ingest-text")
async def api_ingest_text(body: IngestTextRequest, tenant: dict = Depends(require_tenant)):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    stats = await ingest_text(
        empresa_id=empresa_id,
        titulo=body.titulo,
        texto=body.texto,
        categoria=body.categoria,
    )
    return stats


@router.get("")
async def api_listar(
    categoria: Optional[str] = None,
    tenant: dict = Depends(require_tenant),
):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    items = await listar_conhecimento(empresa_id, categoria=categoria)
    return {"items": items, "total": len(items)}


@router.delete("/{kb_id}")
async def api_deletar(kb_id: int, tenant: dict = Depends(require_tenant)):
    empresa_id = tenant["empresa_id"]
    if not empresa_id:
        raise HTTPException(status_code=400, detail="tenant sem empresa_id")
    ok = await deletar_conhecimento(empresa_id, kb_id)
    if not ok:
        raise HTTPException(status_code=404, detail="item nao encontrado ou erro")
    return {"deleted": True, "id": kb_id}
