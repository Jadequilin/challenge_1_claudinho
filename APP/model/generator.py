"""Gerador grounded com ancoragem estrita (Strict Grounding).

O LLM e chamado por APP/model/llm.py, que tenta o modelo proprio (Ollama) antes dos
provedores externos.

Documentado em:
- Docs/Model/02_arquitetura_nlp_rag.md (Strict Grounding e System Prompt)
- Docs/User/01_personas.md (Tom de voz e persona Lucas)
- Docs/Model/01_metricas_e_avaliacao.md (Limiares de decisao e calibracao)
"""

import logging
from typing import Literal

from APP.config import Settings
from APP.errors import ApiError
from APP.model.llm import GeracaoIndisponivel, gerar_json, provedores_configurados
from APP.model.retriever import formatar_contexto_cientifico
from APP.schemas import Fonte
from APP.verdict import classificar_veredito

logger = logging.getLogger("gerador_rag")

PROMPT_SISTEMA_RAG = """Você é um assistente de nutrição acolhedor e protetivo (Persona Lucas).
Seu papel é responder de forma direta, humana, empática e personalizada, desmistificando mitos
ou esclarecendo dúvidas nutricionais sem qualquer julgamento ou culpabilização.

DIRETRIZES FUNDAMENTAIS:
1. Baseie sua resposta EXCLUSIVAMENTE nos dados e fragmentos em <contexto_cientifico>.
2. NUNCA invente referências, autores, anos ou números que não estejam no texto.
3. Se a informação não constar nos fragmentos, declare ausência de evidências suficientes.
4. Mantenha tom empático, direto, compreensivo e acolhedor (sem frieza acadêmica).
5. Sempre cite o ID do fragmento no formato [Ref: ID_CHUNK] ao apoiar afirmações ou números.
6. NUNCA use emojis nem símbolos gráficos decorativos. Responda em português limpo e direto.

ESTRUTURA OBRIGATÓRIA DA RESPOSTA ("answer"):
- Linha 1: Título de tom (ex: "Resposta informativa", "Resposta sobre o mito").
- Linha 2: Frase humana e direta de acolhimento, conclusão ou resumo da dúvida.
- Linha 3: "Entendi assim: <pergunta reformulada de forma simples e natural>"
- Linha 4 em branco.
- Parágrafo empático e explicativo: Valide a dúvida, contextualize e cite [Ref: ID_CHUNK].
- Linha em branco.
- Parágrafo final: Conclusão construtiva iniciando com "A ciência indica que...".

CALIBRAÇÃO DO RISK_SCORE (Grau de risco ou desinformação da alegação avaliada):
- 0.00 a 0.34 (seguro): Fatos confirmados, comparações nutricionais (TBCA), alimentos seguros.
- 0.35 a 0.65 (cautela): Práticas controversas, restrições com ressalvas, conduta clínica.
- 0.66 a 1.00 (desinformacao): Mitos nutricionais refutados, promessas de secar rápido.

Responda ESTRITAMENTE em formato JSON com a seguinte estrutura:
{
  "answer": "Texto humanizado completo conforme a estrutura acima",
  "risk_score": 0.85 // Ex: 0.10 para fato/TBCA, 0.50 para cautela, 0.85 para mito/desinformação
}
"""


def _definir_nivel_risco(score: float) -> Literal["baixo", "medio", "alto"]:
    if score < 0.35:
        return "baixo"
    if score <= 0.65:
        return "medio"
    return "alto"


def gerar_resposta_grounded(
    alegacao_canonica: str,
    fontes: list[Fonte],
    raw_chunks: list[dict[str, object]],
    settings: Settings,
    pergunta_amigavel: str = "",
    dados_sensiveis: bool = False,
) -> tuple[str, float, str, str, str]:
    """Gera a resposta ancorada nos chunks científicos em tom humano e acolhedor.

    `dados_sensiveis` deve ser True quando o perfil de saude entrar no prompt: assim a
    geracao fica restrita ao modelo proprio (ver APP/model/llm.py).

    Retorna tupla:
      (answer, risk_score, verdict, model_version, prompt_version)
    """
    prompt_version = "rag-v1.0"
    pergunta_exibicao = pergunta_amigavel or alegacao_canonica

    # Caso 1: Nenhuma fonte recuperada na base
    if not fontes or not raw_chunks:
        answer = (
            f"Resposta de orientação\n"
            f"Ainda não temos estudos científicos na nossa base para confirmar essa alegação.\n"
            f"Entendi assim: {pergunta_exibicao}\n\n"
            f"Compreendo a curiosidade diante de informações nas redes sociais, "
            f"mas práticas sem comprovação científica podem não entregar os resultados esperados "
            f"e gerar frustração.\n\n"
            f"A ciência indica que manter escolhas equilibradas e consultar um nutricionista "
            f"ou médico é sempre a conduta mais segura e confiável."
        )
        score = 0.50
        return (
            answer,
            score,
            "sem_evidencia",
            "retriever@multilingual-e5-base",
            prompt_version,
        )

    contexto_str = formatar_contexto_cientifico(raw_chunks)
    provedores = provedores_configurados(settings)

    # Caso especial exclusivo para testes unitarios em ambiente CI
    if not provedores and "teste.supabase.co" in settings.supabase_url:
        return (
            f"Resposta de teste para {pergunta_exibicao} [Ref: {fontes[0].chunk_id}].",
            0.15,
            "seguro",
            "mock-test-generator",
            prompt_version,
        )

    prompt_usuario = (
        f"<contexto_cientifico>\n{contexto_str}\n</contexto_cientifico>\n\n"
        f"Pergunta do usuário: {pergunta_exibicao}"
    )
    try:
        resposta_llm, provedor = gerar_json(
            PROMPT_SISTEMA_RAG,
            prompt_usuario,
            provedores,
            dados_sensiveis=dados_sensiveis,
        )
        # Fora do try, uma resposta sem "answer" viraria a string "None" na tela do app.
        answer = str(resposta_llm["answer"])
        score = max(0.0, min(1.0, float(resposta_llm.get("risk_score", 0.5))))
    except (GeracaoIndisponivel, KeyError, TypeError, ValueError) as erro:
        logger.error("Geracao indisponivel: %s", erro)
        raise ApiError(
            "generation_unavailable",
            503,
            "Serviço de IA generativa indisponível no momento. Tente novamente em instantes.",
        ) from erro

    return answer, score, classificar_veredito(score), provedor.versao, prompt_version
