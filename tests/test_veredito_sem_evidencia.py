"""Veredito quando os estudos recuperados nao tratam da pergunta.

Achado no app publicado em 06/10: os dois exemplos da tela inicial saiam com o cartao
"Pode confiar" ou "E mito" e, logo abaixo, um texto dizendo que os estudos nao trazem
informacao sobre o tema. A busca tinha devolvido trechos sobre outro assunto, o modelo
percebeu, mas o risk_score que ele mandou junto virava veredito do mesmo jeito.
"""

import pytest

from APP.config import obter_settings
from APP.model import generator
from APP.model.pipeline import executar_pipeline_de_checagem
from APP.schemas import CheckClaimRequest
from tests._dubles import PROVEDOR_FALSO

SEM_ESTUDO = "Os estudos disponíveis não trazem informações sobre isso."


def _responder_com(monkeypatch, resposta: dict) -> None:
    monkeypatch.setattr(generator, "gerar_json", lambda *_a, **_k: (resposta, PROVEDOR_FALSO))


def _checar(texto: str):
    return executar_pipeline_de_checagem(
        CheckClaimRequest(input_type="text", text=texto), obter_settings(), 0, "trace"
    )


@pytest.mark.parametrize(
    ("pergunta", "score"),
    [
        ("arroz com feijão é proteína completa mesmo?", 0.1),  # saia "Pode confiar"
        ("pão francês inflama o corpo?", 0.78),  # saia "É mito"
    ],
)
def test_estudos_que_nao_tratam_da_pergunta_viram_sem_evidencia(monkeypatch, pergunta, score):
    _responder_com(
        monkeypatch,
        {"answer": SEM_ESTUDO, "risk_score": score, "evidencia_suficiente": False},
    )

    resposta = _checar(pergunta)

    assert resposta.verdict == "sem_evidencia"
    assert resposta.risk_score == 0.5
    assert resposta.answer == SEM_ESTUDO


def test_padrao_de_consenso_nao_vira_veredito_sem_estudo(monkeypatch):
    """A pergunta casa o padrão de consenso seguro de arroz e feijão. Sem estudo para
    mostrar, o padrão não pode transformar a resposta em "Pode confiar"."""
    _responder_com(
        monkeypatch,
        {"answer": SEM_ESTUDO, "risk_score": 0.1, "evidencia_suficiente": False},
    )

    assert _checar("arroz e feijão juntos formam proteína completa?").verdict == "sem_evidencia"


def test_booleano_entre_aspas_tambem_conta(monkeypatch):
    """Modelo pequeno às vezes devolve "false" como texto."""
    _responder_com(
        monkeypatch,
        {"answer": SEM_ESTUDO, "risk_score": 0.9, "evidencia_suficiente": "false"},
    )

    assert _checar("pão francês inflama o corpo?").verdict == "sem_evidencia"


@pytest.mark.parametrize("campo", [{"evidencia_suficiente": True}, {}])
def test_com_evidencia_ou_sem_o_campo_o_score_decide(monkeypatch, campo):
    """Sem o campo é o formato das versões de prompt anteriores: nada muda para elas."""
    _responder_com(
        monkeypatch,
        {"answer": "Isso é mito [Ref: chunk_teste_01].", "risk_score": 0.8, **campo},
    )

    assert _checar("pão francês inflama o corpo?").verdict == "desinformacao"
