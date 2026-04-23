"""
[MKT-04] Auto-ingestao de knowledge base — crawl de site + upload de PDF.

Complementa o `rag_service.py` existente (que ja faz indexar_documento, chunk_text,
embeddings e cosine similarity). Este modulo adiciona:

  1. crawl_site(empresa_id, url, max_pages) — baixa paginas HTML, extrai texto limpo
     e indexa como knowledge base.
  2. ingest_pdf(empresa_id, pdf_bytes, titulo) — extrai texto de PDF e indexa.
  3. ingest_text(empresa_id, titulo, texto) — wrapper simples.

Dependencias opcionais:
  - httpx (ja presente)
  - BeautifulSoup4 + lxml (para parsing HTML)
  - pypdf (para PDF)

Uso via router (ver src/api/routers/kb.py):
    POST /api/kb/crawl   { url, max_pages }
    POST /api/kb/upload-pdf  (multipart)
    POST /api/kb/ingest-text { titulo, texto }

Uso programatico:
    from src.services.kb_ingestion import crawl_site, ingest_pdf
    stats = await crawl_site(empresa_id=1, url="https://minhaacademia.com", max_pages=30)
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import httpx

from src.core.config import logger
from src.services.rag_service import indexar_documento


HTML_TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")

MAX_PAGE_BYTES = 2_000_000     # 2 MB por pagina
DEFAULT_TIMEOUT = 10.0


# ============================================================
# HTML extraction (fallback sem BeautifulSoup)
# ============================================================

def _strip_html(html: str) -> str:
    """Remove tags HTML preservando texto. Fallback se BS4 nao estiver instalado."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
    except ImportError:
        # Fallback regex
        text = SCRIPT_STYLE_RE.sub(" ", html)
        text = HTML_TAG_RE.sub(" ", text)

    text = WHITESPACE_RE.sub(" ", text).strip()
    return text


def _extract_links(html: str, base_url: str) -> List[str]:
    """Extrai URLs absolutas do HTML, filtrando para o mesmo dominio."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        parsed_base = urlparse(base_url)
        links: List[str] = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                continue
            abs_url = urljoin(base_url, href)
            parsed = urlparse(abs_url)
            if parsed.netloc == parsed_base.netloc and parsed.scheme in ("http", "https"):
                # Remove query/fragment para deduplicar
                clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                links.append(clean)
        return list(dict.fromkeys(links))  # dedupe preservando ordem
    except ImportError:
        # Fallback regex basico
        hrefs = re.findall(r'href="([^"]+)"', html)
        parsed_base = urlparse(base_url)
        out: List[str] = []
        for h in hrefs:
            if h.startswith("#") or h.startswith("mailto:"):
                continue
            abs_url = urljoin(base_url, h)
            if urlparse(abs_url).netloc == parsed_base.netloc:
                out.append(abs_url.split("#")[0].split("?")[0])
        return list(dict.fromkeys(out))


# ============================================================
# Crawl
# ============================================================

async def crawl_site(
    empresa_id: int,
    start_url: str,
    max_pages: int = 30,
    max_depth: int = 2,
    categoria: str = "site",
) -> Dict:
    """
    Faz crawl BFS a partir de start_url, limitado ao mesmo dominio.
    Indexa cada pagina na knowledge base.
    """
    parsed = urlparse(start_url)
    if parsed.scheme not in ("http", "https"):
        return {"error": "url_invalida", "indexed": 0, "pages": 0}

    visited: Set[str] = set()
    queue: List = [(start_url, 0)]
    indexed_chunks = 0
    pages_ok = 0
    pages_fail = 0

    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT, follow_redirects=True,
        headers={"User-Agent": "FluxoIA-KB-Crawler/1.0"},
    ) as client:
        while queue and len(visited) < max_pages:
            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            try:
                resp = await client.get(url)
                if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type", ""):
                    pages_fail += 1
                    continue
                html = resp.text[:MAX_PAGE_BYTES]
            except Exception as e:
                logger.warning(f"[MKT-04] crawl GET falhou url={url}: {e}")
                pages_fail += 1
                continue

            texto = _strip_html(html)
            if len(texto) < 50:
                continue

            # Titulo da pagina
            titulo_match = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
            titulo = (titulo_match.group(1) if titulo_match else url)[:180]

            n = await indexar_documento(
                empresa_id=empresa_id,
                titulo=titulo,
                conteudo=texto,
                categoria=categoria,
                source_file=url,
            )
            indexed_chunks += n
            pages_ok += 1

            # Adiciona links na fila se depth permite
            if depth < max_depth:
                for link in _extract_links(html, url)[:20]:
                    if link not in visited:
                        queue.append((link, depth + 1))

    logger.info(
        f"[MKT-04] crawl empresa={empresa_id} start={start_url} "
        f"pages_ok={pages_ok} fail={pages_fail} chunks={indexed_chunks}"
    )
    return {
        "indexed_chunks": indexed_chunks,
        "pages_visited": pages_ok,
        "pages_failed": pages_fail,
        "start_url": start_url,
    }


# ============================================================
# PDF
# ============================================================

async def ingest_pdf(
    empresa_id: int,
    pdf_bytes: bytes,
    titulo: str,
    categoria: str = "documento",
) -> Dict:
    """Extrai texto do PDF (via pypdf) e indexa na KB."""
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.error("[MKT-04] pypdf nao instalado. Rode: pip install pypdf")
        return {"error": "pypdf_missing", "indexed_chunks": 0}

    import io
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        partes = []
        for i, page in enumerate(reader.pages[:200]):  # max 200 paginas
            try:
                txt = page.extract_text() or ""
                if txt.strip():
                    partes.append(f"--- pagina {i+1} ---\n{txt}")
            except Exception as e:
                logger.warning(f"[MKT-04] pagina {i+1} falhou: {e}")

        if not partes:
            return {"error": "pdf_vazio_ou_escaneado", "indexed_chunks": 0}

        conteudo = "\n\n".join(partes)
        n = await indexar_documento(
            empresa_id=empresa_id, titulo=titulo,
            conteudo=conteudo, categoria=categoria,
            source_file=f"pdf:{titulo}",
        )
        logger.info(f"[MKT-04] pdf empresa={empresa_id} titulo='{titulo}' chunks={n}")
        return {"indexed_chunks": n, "paginas_extraidas": len(partes)}
    except Exception as e:
        logger.error(f"[MKT-04] ingest_pdf falhou: {e}")
        return {"error": str(e), "indexed_chunks": 0}


async def ingest_text(
    empresa_id: int,
    titulo: str,
    texto: str,
    categoria: str = "manual",
) -> Dict:
    """Ingestao direta de texto arbitrario."""
    if not texto or not texto.strip():
        return {"indexed_chunks": 0}
    n = await indexar_documento(
        empresa_id=empresa_id, titulo=titulo,
        conteudo=texto, categoria=categoria,
    )
    return {"indexed_chunks": n}
