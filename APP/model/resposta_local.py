"""Resposta local para quando nenhum provedor de LLM responde.

O veredito vem do classificador de regras (`classifier.py`); este modulo so escreve
o texto. A estrutura imita a que o prompt pede ao Gemini (Docs/Model/02 e persona
Lucas em Docs/User/01), para o usuario nao perceber uma quebra de tom quando o
fallback assume:

    Linha 1: titulo de tom
    Linha 2: frase de acolhimento/conclusao
    Linha 3: "Entendi assim: <pergunta>"
    (branco)
    Paragrafo explicativo citando os trechos com [Ref: ID]
    (branco)
    Conclusao iniciando com "A ciencia indica que..."

Nada aqui inventa conteudo: o paragrafo explicativo so reproduz trechos que vieram
da base, que e o mesmo principio de grounding estrito do gerador com LLM.
"""

import hashlib
import re

from APP.schemas import Fonte

MODEL_VERSION = "fallback-local@classifier-v1"
TAMANHO_MAXIMO_TRECHO = 360
MAXIMO_DE_FONTES_CITADAS = 2

TITULOS = {
    "desinformacao": "Resposta sobre o mito",
    "cautela": "Resposta com ressalvas",
    "seguro": "Resposta informativa",
}

# Variacoes para a mesma pergunta nao receber sempre a mesma frase de abertura.
ACOLHIMENTOS = {
    "desinformacao": (
        "Essa ideia circula bastante, mas os estudos não confirmam o que ela promete.",
        "É uma dúvida muito comum, e vale olhar com calma: a evidência não sustenta essa promessa.",
        "Faz sentido desconfiar, porque essa afirmação não se sustenta nos estudos que temos.",
    ),
    "cautela": (
        "Essa pergunta não tem uma resposta única: depende bastante de cada pessoa.",
        "Aqui a resposta é 'depende', e vale entender os porquês antes de mudar qualquer hábito.",
        "Boa pergunta. A evidência existe, mas vem com ressalvas importantes.",
    ),
    "seguro": (
        "Boa notícia: isso tem respaldo nos estudos.",
        "Pode ficar tranquilo, essa informação é confirmada pela evidência disponível.",
        "Sim, e é bom saber que isso tem base científica.",
    ),
}

CONCLUSOES = {
    "desinformacao": (
        "A ciência indica que não existem atalhos milagrosos: resultados consistentes vêm "
        "de uma alimentação equilibrada ao longo do tempo. Se o objetivo é emagrecer ou "
        "melhorar a saúde, um nutricionista pode montar um plano que funcione para você."
    ),
    "cautela": (
        "A ciência indica que essa prática pode fazer sentido para algumas pessoas e não "
        "para outras. Antes de adotar, vale conversar com um nutricionista ou médico, que "
        "pode avaliar a sua situação específica."
    ),
    "seguro": (
        "A ciência indica que esse é um caminho confiável. Manter hábitos assim, dentro de "
        "uma rotina equilibrada, costuma trazer bons resultados."
    ),
}

INTRODUCOES_DE_EVIDENCIA = {
    "desinformacao": "O que os estudos da nossa base mostram é diferente.",
    "cautela": "Os estudos da nossa base trazem pontos que ajudam a pesar isso.",
    "seguro": "Os estudos da nossa base apoiam essa informação.",
}


def montar_resposta_local(
    veredito: str,
    pergunta: str,
    fontes: list[Fonte],
    trechos_por_chunk: dict[str, str],
) -> str:
    """Monta o texto da resposta no formato da persona, ancorado nos trechos."""
    tom = veredito if veredito in TITULOS else "cautela"

    linhas = [
        TITULOS[tom],
        _escolher(ACOLHIMENTOS[tom], pergunta),
        f"Entendi assim: {pergunta.strip()}",
        "",
        _paragrafo_de_evidencias(tom, fontes, trechos_por_chunk),
        "",
        CONCLUSOES[tom],
    ]
    return "\n".join(linhas)


def _paragrafo_de_evidencias(tom: str, fontes: list[Fonte], trechos: dict[str, str]) -> str:
    citacoes = []
    for fonte in fontes[:MAXIMO_DE_FONTES_CITADAS]:
        trecho = resumir_trecho(trechos.get(fonte.chunk_id) or fonte.excerpt)
        if not trecho:
            continue
        citacoes.append(f"O estudo “{fonte.title}” traz que {trecho} [Ref: {fonte.chunk_id}]")

    if not citacoes:
        return (
            "Encontrei estudos relacionados na nossa base, mas os trechos não são "
            "conclusivos o bastante para detalhar aqui."
        )
    return " ".join([INTRODUCOES_DE_EVIDENCIA[tom], *citacoes])


def resumir_trecho(texto: str | None) -> str:
    """Corta o trecho em fim de frase, sem passar do limite, e ajusta o inicio.

    Os chunks sao cortados mecanicamente na ingestao e costumam comecar no meio de
    uma frase; colados crus, deixam a resposta com cara de maquina.
    """
    if not texto:
        return ""
    limpo = re.sub(r"\s+", " ", texto).strip()
    limpo = _descartar_fragmento_inicial(limpo)
    limpo = _descartar_fragmento_final(limpo)
    limpo = limpo.removesuffix("...").strip().rstrip(".").strip()

    if len(limpo) > TAMANHO_MAXIMO_TRECHO:
        corte = limpo[:TAMANHO_MAXIMO_TRECHO]
        fim_de_frase = max(corte.rfind(". "), corte.rfind("; "))
        if fim_de_frase > TAMANHO_MAXIMO_TRECHO // 3:
            limpo = corte[:fim_de_frase]
        else:
            limpo = corte[: corte.rfind(" ")].rstrip(",;:") + "..."
            return _minuscula_inicial(limpo)

    return _minuscula_inicial(limpo) + "."


def _descartar_fragmento_inicial(texto: str) -> str:
    """Pula o pedaco de frase que sobrou do corte anterior do chunk.

    Um chunk que comeca em letra minuscula ("coes avaliadas. Nao foram...") comecou
    no meio de uma frase. Se houver um fim de frase logo adiante, o texto passa a
    comecar dali; senao, fica como esta, porque cortar demais perderia o conteudo.
    """
    if not texto or not texto[0].islower():
        return texto
    fim = re.search(r"[.;!?]\s+(?=[A-ZÀ-Ú0-9])", texto)
    if fim and fim.end() < len(texto) // 2:
        return texto[fim.end() :]
    return texto


def _descartar_fragmento_final(texto: str) -> str:
    """O mesmo problema no fim: chunk que termina sem pontuacao foi cortado no meio."""
    if not texto or texto.endswith((".", "!", "?", "...")):
        return texto
    ultimo_fim = max(texto.rfind(". "), texto.rfind("! "), texto.rfind("? "))
    if ultimo_fim > len(texto) // 3:
        return texto[: ultimo_fim + 1]
    return texto


def _minuscula_inicial(texto: str) -> str:
    # "traz que Os resultados..." -> "traz que os resultados...", sem estragar siglas.
    if len(texto) > 1 and texto[0].isupper() and not texto[1].isupper():
        return texto[0].lower() + texto[1:]
    return texto


def _escolher(opcoes: tuple[str, ...], semente: str) -> str:
    """Escolha deterministica: a mesma pergunta recebe sempre a mesma frase.

    Aleatoriedade verdadeira deixaria os testes e a auditoria (trace_id) sem
    reprodutibilidade.
    """
    indice = int(hashlib.sha256(semente.encode()).hexdigest(), 16) % len(opcoes)
    return opcoes[indice]
