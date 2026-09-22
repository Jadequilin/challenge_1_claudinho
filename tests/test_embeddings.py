"""Cliente de embeddings (APP/model/embeddings.py) e contrato com o Space.

O objetivo do modo remoto e deixar a API leve para a Vercel e o Render gratuito. Estes
testes garantem que ela continua leve, que o cliente fala o mesmo contrato que o servico
de deploy/embeddings-space, e que falha do servico vira 503, nao "sem evidencia".
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from APP.config import Settings
from APP.model import embeddings, retriever
from tests.conftest import AUTH

RAIZ = Path(__file__).resolve().parents[1]
URL = "https://usuario-embeddings.hf.space"


def _settings(**extra):
    base = {"supabase_url": "https://x.supabase.co", "supabase_key": "x", "embeddings_url": URL}
    return Settings(**{**base, **extra})


@pytest.fixture
def servico(monkeypatch):
    """Servico remoto falso: registra o que recebeu e responde o que o teste mandar."""
    estado = {"pedidos": [], "resposta": lambda textos: {"vetores": [[0.1] * 768 for _ in textos]}}

    def responder(pedido: httpx.Request) -> httpx.Response:
        corpo = __import__("json").loads(pedido.content)
        estado["pedidos"].append({"url": str(pedido.url), "headers": pedido.headers, **corpo})
        resposta = estado["resposta"](corpo["textos"])
        if isinstance(resposta, httpx.Response):
            return resposta
        return httpx.Response(200, json=resposta)

    transporte = httpx.MockTransport(responder)
    original = httpx.Client

    monkeypatch.setattr(
        embeddings.httpx, "Client", lambda **kw: original(transport=transporte, **kw)
    )
    return estado


def test_importar_o_cliente_nao_puxa_o_torch():
    """E o motivo de existir o modo remoto: sem isto a API nao cabe na Vercel (500 MB)."""
    codigo = (
        "import sys, APP.model.embeddings, APP.model.retriever;"
        "print('torch' in sys.modules or 'sentence_transformers' in sys.modules)"
    )
    # Herda o ambiente do sistema: no Windows, sem SYSTEMROOT o Python nem inicializa a
    # rede (WinError 10106). So as credenciais obrigatorias sao sobrescritas.
    ambiente = {**os.environ, "SUPABASE_URL": "x", "SUPABASE_KEY": "x"}
    saida = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        env=ambiente,
    )

    # Sem check=True: se o subprocesso quebrar, a mensagem mostra o erro dele, e nao so
    # "exit status 1".
    assert saida.returncode == 0, saida.stderr
    assert saida.stdout.strip() == "False"


def test_modo_remoto_manda_o_prefixo_e5_e_o_token(monkeypatch, servico):
    monkeypatch.setattr(embeddings, "obter_settings", lambda: _settings(embeddings_token="hf_x"))

    vetor = embeddings.gerar_embedding_consulta("agua com limao emagrece?")

    pedido = servico["pedidos"][0]
    assert len(vetor) == 768
    assert pedido["url"] == f"{URL}/embed"
    assert pedido["textos"] == ["query: agua com limao emagrece?"]
    assert pedido["headers"]["authorization"] == "Bearer hf_x"


def test_prefixo_nao_e_duplicado(monkeypatch, servico):
    monkeypatch.setattr(embeddings, "obter_settings", _settings)

    embeddings.gerar_embedding_consulta("query: ja formatado")

    assert servico["pedidos"][0]["textos"] == ["query: ja formatado"]


def test_vetor_de_outra_dimensao_e_recusado(monkeypatch, servico):
    """Outro modelo no Space (ex.: e5-large, 1024) quebraria a busca no pgvector."""
    monkeypatch.setattr(embeddings, "obter_settings", _settings)
    servico["resposta"] = lambda textos: {"vetores": [[0.1] * 1024]}

    with pytest.raises(embeddings.EmbeddingsIndisponiveis, match="1024"):
        embeddings.gerar_embedding_consulta("ovo")


@pytest.mark.parametrize(
    "falha",
    [httpx.Response(503), httpx.Response(200, json={"outra": "coisa"})],
    ids=["space-dormindo", "resposta-sem-vetores"],
)
def test_falha_do_servico_vira_erro_de_embeddings(monkeypatch, servico, falha):
    monkeypatch.setattr(embeddings, "obter_settings", _settings)
    servico["resposta"] = lambda textos: falha

    with pytest.raises(embeddings.EmbeddingsIndisponiveis):
        embeddings.gerar_embedding_consulta("ovo")


def test_servico_fora_do_ar_responde_503_e_nao_sem_evidencia(client, monkeypatch):
    """Space dormindo nao e 'a base nao tem estudos': isso seria uma resposta falsa."""

    def fora_do_ar(_texto):
        raise embeddings.EmbeddingsIndisponiveis("HTTPStatusError")

    monkeypatch.setattr(retriever, "gerar_embedding_consulta", fora_do_ar)

    resposta = client.post("/api/v1/check-claim", headers=AUTH, json={"text": "ovo faz mal?"})

    assert resposta.status_code == 503
    assert resposta.json()["error"] == "upstream_unavailable"


# ---------- contrato entre o cliente e o servico do Space ----------


class _ModeloFalso:
    def encode(self, textos, normalize_embeddings=True):
        assert normalize_embeddings  # a base foi indexada com vetores normalizados
        return _Lista([[0.5] * 768 for _ in textos])


class _Lista(list):
    def tolist(self):
        return list(self)


def _carregar_servico_do_space():
    caminho = RAIZ / "deploy" / "embeddings-space" / "app.py"
    especificacao = importlib.util.spec_from_file_location("servico_embeddings", caminho)
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


def test_cliente_e_servico_do_space_falam_o_mesmo_contrato(monkeypatch):
    servico = _carregar_servico_do_space()
    servico._estado["modelo"] = _ModeloFalso()  # o torch nao e carregado no teste

    with TestClient(servico.app) as cliente_do_space:
        monkeypatch.setattr(embeddings.httpx, "Client", lambda **_kw: cliente_do_space)
        monkeypatch.setattr(embeddings, "obter_settings", _settings)

        vetor = embeddings.gerar_embedding_consulta("agua com limao emagrece?")

        saude = cliente_do_space.get("/health").json()

    assert vetor == [0.5] * 768
    assert saude == {"status": "ok", "modelo": "intfloat/multilingual-e5-base", "carregado": True}
