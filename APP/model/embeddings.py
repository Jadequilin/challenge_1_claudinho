"""Embeddings de consulta com intfloat/multilingual-e5-base (768 dimensoes).

Documentado em Docs/Model/02_arquitetura_nlp_rag.md e Docs/Data/02_armazenamento_e_estrutura.md.

Dois modos, escolhidos pela configuracao:

- **Remoto** (`EMBEDDINGS_URL` definida): chama o servico de deploy/embeddings-space. E o
  modo de producao. A API nao carrega o modelo nem importa o torch, entao fica leve o
  bastante para a Vercel (limite de 500 MB por funcao) e para o Render gratuito (512 MB).
- **Local** (sem `EMBEDDINGS_URL`): carrega o modelo no proprio processo. So para
  desenvolvimento; exige `requirements-ml.txt`.

Os dois usam o MESMO modelo: trocar de modelo mudaria os vetores e obrigaria a reindexar
a base inteira no pgvector.
"""

from functools import lru_cache

import httpx

from APP.config import obter_settings

MODELO_PADRAO = "intfloat/multilingual-e5-base"
DIMENSAO = 768
PREFIXO_CONSULTA = "query: "


class EmbeddingsIndisponiveis(RuntimeError):
    """O servico remoto falhou ou devolveu um vetor incompativel com a base."""


def gerar_embedding_consulta(texto: str) -> list[float]:
    """Gera o embedding normalizado de uma consulta de busca.

    O e5 exige o prefixo 'query: ' para consultas em busca assimetrica.
    """
    texto_limpo = texto.strip()
    formatado = (
        texto_limpo
        if texto_limpo.startswith(PREFIXO_CONSULTA)
        else (f"{PREFIXO_CONSULTA}{texto_limpo}")
    )

    settings = obter_settings()
    if settings.embeddings_url:
        vetor = _remoto(formatado, settings)
    else:
        vetor = _local(formatado)

    if len(vetor) != DIMENSAO:
        # Vetor de outra dimensao quebraria a busca no pgvector com um erro pouco claro.
        raise EmbeddingsIndisponiveis(f"vetor com {len(vetor)} dimensoes, esperado {DIMENSAO}")
    return vetor


def _remoto(texto: str, settings) -> list[float]:
    cabecalhos = {}
    if settings.embeddings_token:
        cabecalhos["Authorization"] = f"Bearer {settings.embeddings_token}"
    try:
        with httpx.Client(timeout=settings.embeddings_timeout_s) as cliente:
            resposta = cliente.post(
                f"{settings.embeddings_url.rstrip('/')}/embed",
                json={"textos": [texto]},
                headers=cabecalhos,
            )
            resposta.raise_for_status()
            return [float(x) for x in resposta.json()["vetores"][0]]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as erro:
        # A mensagem so leva o tipo do erro: a URL poderia carregar dados da requisicao.
        raise EmbeddingsIndisponiveis(type(erro).__name__) from erro


def _local(texto: str) -> list[float]:
    return obter_modelo_embeddings().encode(texto, normalize_embeddings=True).tolist()


@lru_cache(maxsize=1)
def obter_modelo_embeddings(nome_modelo: str = MODELO_PADRAO):
    """Carrega o modelo local uma unica vez.

    Import dentro da funcao, de proposito: no modo remoto o sentence-transformers nem
    precisa estar instalado, e importar no topo do modulo puxaria o torch para a API.
    """
    import huggingface_hub.utils.logging as hf_logging
    from sentence_transformers import SentenceTransformer

    hf_logging.set_verbosity_error()
    return SentenceTransformer(nome_modelo)
