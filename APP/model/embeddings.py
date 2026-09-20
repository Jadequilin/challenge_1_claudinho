"""Geracao local de embeddings usando intfloat/multilingual-e5-base (768 dim).

Documentado em Docs/Model/02_arquitetura_nlp_rag.md e Docs/Data/02_armazenamento_e_estrutura.md.
"""

from functools import lru_cache

import huggingface_hub.utils.logging as hf_logging
from sentence_transformers import SentenceTransformer

# Silencia mensagens informativas do Hugging Face Hub
hf_logging.set_verbosity_error()

MODELO_PADRAO = "intfloat/multilingual-e5-base"


@lru_cache(maxsize=1)
def obter_modelo_embeddings(nome_modelo: str = MODELO_PADRAO) -> SentenceTransformer:
    """Carrega o modelo SentenceTransformer uma única vez em memória."""
    return SentenceTransformer(nome_modelo)


def gerar_embedding_consulta(texto: str) -> list[float]:
    """Gera o embedding normalizado de uma consulta de busca.

    O modelo e5 requer o prefixo 'query: ' para consultas de busca assimétrica.
    """
    texto_limpo = texto.strip()
    if not texto_limpo.startswith("query: "):
        texto_formatado = f"query: {texto_limpo}"
    else:
        texto_formatado = texto_limpo

    modelo = obter_modelo_embeddings()
    vetor = modelo.encode(texto_formatado, normalize_embeddings=True)
    return vetor.tolist()
