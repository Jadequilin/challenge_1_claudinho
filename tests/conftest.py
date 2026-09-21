import os

import pytest

# Valores de teste fixados ANTES de importar a aplicacao.
# Usamos atribuicao direta (e nao setdefault) de proposito: o CI define
# SUPABASE_URL/SUPABASE_KEY no ambiente do job, e a suite precisa ser
# hermetica — o mesmo resultado na maquina do dev e no GitHub Actions.
os.environ["SUPABASE_URL"] = "https://teste.supabase.co"
os.environ["SUPABASE_KEY"] = "chave-de-teste"
os.environ["APP_ENV"] = "local"

import json  # noqa: E402
import logging  # noqa: E402
import uuid  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from APP.auth import ALGORITMO, AUDIENCIA  # noqa: E402
from APP.config import obter_settings  # noqa: E402
from APP.main import app  # noqa: E402
from APP.model.database import obter_supabase  # noqa: E402
from APP.observabilidade import LOGGER_INFERENCIA  # noqa: E402
from APP.ratelimit import limpar as limpar_limites  # noqa: E402
from APP.repositorios.feedback import obter_repositorio_de_feedback  # noqa: E402
from APP.repositorios.perfil import obter_repositorio_de_perfil  # noqa: E402

AUTH = {"Authorization": "Bearer token-de-teste"}

SEGREDO_DE_TESTE = "segredo-de-teste-nao-usar-em-producao"


@pytest.fixture(autouse=True)
def estado_do_processo():
    """Zera o que vive no processo entre um teste e outro.

    Repositorios em memoria e contador de rate limit sao globais de modulo. Sem esta
    limpeza, um teste enxerga o perfil gravado por outro e a ordem dos arquivos passa a
    mudar o resultado da suite. E autouse de proposito: quem esquecer de pedir a fixture
    nao fica com um teste que passa por engano.
    """
    limpar_estado()
    yield
    limpar_estado()


def limpar_estado() -> None:
    limpar_limites()
    obter_repositorio_de_feedback().limpar()
    obter_repositorio_de_perfil().limpar()
    # O pipeline cria o client do Supabase ao buscar evidencias; sem limpar, o teste que
    # confere que o import nao cria client passa a depender da ordem da suite.
    obter_supabase.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def client_com_jwt(monkeypatch):
    """TestClient com a validacao de JWT ligada, como em staging e producao.

    A configuracao e lida por `obter_settings`, que tem cache. Mexer na variavel de
    ambiente e limpar o cache deixa o modo valendo para TODO mundo na requisicao
    (rota, middleware de log e rate limit), o que um `dependency_overrides` nao faria:
    middleware e rate limit chamam `obter_settings()` direto, fora do FastAPI.
    """
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SEGREDO_DE_TESTE)
    obter_settings.cache_clear()
    try:
        yield TestClient(app)
    finally:
        obter_settings.cache_clear()


def token_de(sub: str = "usuario-123", **alteracoes) -> str:
    """Monta um JWT igual ao que o Supabase Auth emite.

    O `jti` aleatorio existe para que duas chamadas seguidas gerem tokens DIFERENTES do
    mesmo usuario, como acontece a cada renovacao de sessao. Sem ele, os dois tokens
    sairiam byte a byte iguais no mesmo segundo e o teste de renovacao passaria a toa.
    """
    payload = {
        "sub": sub,
        "aud": AUDIENCIA,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
        "jti": uuid.uuid4().hex,
    }
    payload.update(alteracoes.pop("payload", {}))
    segredo = alteracoes.pop("segredo", SEGREDO_DE_TESTE)
    return jwt.encode(payload, segredo, algorithm=ALGORITMO)


def auth_de(sub: str = "usuario-123", **alteracoes) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_de(sub, **alteracoes)}"}


@pytest.fixture
def registros_de_log():
    """Os registros de inferencia emitidos durante o teste, ja decodificados.

    Nao da para usar o caplog do pytest aqui: ele captura pelo logger raiz, e o
    logger de inferencia tem propagate=False de proposito (senao a linha sairia
    duas vezes em producao). Entao ligamos um coletor direto nele.
    """
    coletados: list[dict] = []

    class _Coletor(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            coletados.append(json.loads(record.getMessage()))

    logger = logging.getLogger(LOGGER_INFERENCIA)
    handler = _Coletor()
    logger.addHandler(handler)
    try:
        yield coletados
    finally:
        logger.removeHandler(handler)
