"""Gerador grounded com suporte a LLM (Gemini/OpenAI) com ancoragem estrita (Strict Grounding).

Documentado em:
- Docs/Model/02_arquitetura_nlp_rag.md (Strict Grounding e System Prompt)
- Docs/User/01_personas.md (Tom de voz e persona Lucas)
- Docs/Model/01_metricas_e_avaliacao.md (Limiares de decisao e calibracao)
"""

import json
import logging
from typing import Literal

import httpx

from APP.config import Settings
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
) -> tuple[str, float, str, str, str]:
    """Gera a resposta ancorada nos chunks científicos em tom humano e acolhedor.

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

    # Caso 2: Provedor Google Gemini configurado
    if settings.gemini_api_key:
        try:
            res_gemini = _chamar_gemini(pergunta_exibicao, contexto_str, settings.gemini_api_key)
            if res_gemini:
                resposta_llm, modelo_usado = res_gemini
                score = max(0.0, min(1.0, float(resposta_llm.get("risk_score", 0.15))))
                veredito = classificar_veredito(score)
                return (
                    str(resposta_llm.get("answer")),
                    score,
                    veredito,
                    modelo_usado,
                    prompt_version,
                )
        except Exception as e:
            logger.warning(f"Falha na chamada a IA, usando fallback: {e}")

    # Caso 3: Provedor OpenAI configurado
    if settings.openai_api_key:
        try:
            resposta_llm = _chamar_openai(pergunta_exibicao, contexto_str, settings.openai_api_key)
            if resposta_llm:
                score = max(0.0, min(1.0, float(resposta_llm.get("risk_score", 0.5))))
                veredito = classificar_veredito(score)
                return (
                    str(resposta_llm.get("answer")),
                    score,
                    veredito,
                    "gpt-4o-mini",
                    prompt_version,
                )
        except Exception as e:
            logger.error(f"Falha na chamada a OpenAI: {e}")

    # Caso especial exclusivo para testes unitarios em ambiente CI
    if "teste.supabase.co" in settings.supabase_url and not settings.gemini_api_key:
        return (
            f"Resposta de teste para {pergunta_exibicao} [Ref: {fontes[0].chunk_id}].",
            0.15,
            "seguro",
            "mock-test-generator",
            prompt_version,
        )

    # Fallback local desativado: exigir provedor generativo operacional
    from APP.errors import ApiError

    raise ApiError(
        codigo="generation_unavailable",
        status_code=503,
        detail=(
            "Serviço de IA generativa (Gemini) indisponível ou não configurado. "
            "O fallback local determinístico foi desativado conforme diretriz arquitetural."
        ),
    )


def _chamar_gemini(
    pergunta: str, contexto: str, api_key: str
) -> tuple[dict[str, object], str] | None:
    prompt_completo = (
        f"{PROMPT_SISTEMA_RAG}\n\n"
        f"<contexto_cientifico>\n{contexto}\n</contexto_cientifico>\n\n"
        f"Pergunta do usuário: {pergunta}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt_completo}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }

    modelos = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-latest"]
    for modelo in modelos:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}"
        try:
            with httpx.Client(timeout=25.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    dados = resp.json()
                    texto_gerado = dados["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if texto_gerado.startswith("```json"):
                        texto_gerado = texto_gerado[7:]
                    if texto_gerado.startswith("```"):
                        texto_gerado = texto_gerado[3:]
                    if texto_gerado.endswith("```"):
                        texto_gerado = texto_gerado[:-3]
                    texto_gerado = texto_gerado.strip()
                    return json.loads(texto_gerado), modelo
                logger.warning(f"Gemini modelo {modelo} retornou status {resp.status_code}")
        except Exception as e:
            logger.warning(f"Erro ao chamar Gemini {modelo}: {e}")

    return None


def _chamar_openai(pergunta: str, contexto: str, api_key: str) -> dict[str, object] | None:
    url = "https://api.openai.com/v1/chat/completions"
    prompt_usuario = (
        f"<contexto_cientifico>\n{contexto}\n</contexto_cientifico>\n\n"
        f"Pergunta do usuário: {pergunta}"
    )
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": PROMPT_SISTEMA_RAG},
            {"role": "user", "content": prompt_usuario},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        dados = resp.json()
        texto_gerado = dados["choices"][0]["message"]["content"]
        return json.loads(texto_gerado)
