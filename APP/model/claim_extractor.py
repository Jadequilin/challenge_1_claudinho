"""Módulo de Normalização, Extração de Claims e Guardrails Pre-Retrieval.

Documentado em:
- Docs/Model/03_processamento_linguagem_internet.md (Few-Shot e termos)
- Docs/Ethics/01_seguranca_e_anti_alucinacao.md (Safe Refusal Policy)
- Docs/Ethics/02_grupos_de_risco_e_filtros.md (Protecao de grupos vulneraveis)
"""

import re

MAPA_TERMOS_POPULARES = {
    r"\bsecar (a )?barriga\b": "perda de gordura abdominal",
    r"\bqueimar gordura\b": "lipólise e oxidação de ácidos graxos",
    r"\bdesinchar( o corpo)?\b": "redução de retenção hídrica corporal",
    r"\bveneno branco\b": "açúcar refinado ou sal de cozinha",
    r"\breset metab[oó]lico\b": "aumento da taxa metabólica basal",
    r"\bshot de vinagre\b": "ingestão de ácido acético em jejum",
    r"\bágua com gratid[aã]o\b": "água fluidificada sem alteração química",
    r"\binflamar o corpo\b": "indução de marcadores inflamatórios sistêmicos",
    r"\bchutar o balde\b": "episódio de hiperfagia alimentar sem planejamento",
}

# Padrões de risco crítico (Docs/Ethics/01 e Docs/Ethics/02)
PADROES_RISCO_CRITICO = [
    # Jejum hídrico extremo / privação severa de alimentos / dietas líquidas
    (
        r"(jejum.*([3-9]|\d{2,})\s*dias|"
        r"quantos dias posso (ficar|aguentar).*"
        r"(sem comer|em jejum|tomando [aá]gua|s[oó] no |s[oó] na |"
        r"s[oó] de |apenas no |s[oó] bebendo)|"
        r"ficar\s*([3-9]|\d{2,})\s*dias.*(sem comer|s[oó] no|s[oó] de|apenas|em jejum)|"
        r"dieta\s*(l[ií]quida|do lim[aã]o|da [aá]gua).*([3-9]|\d{2,})\s*dias|"
        r"(s[oó]|apenas)\s*(no|tomando|com)\s*(suco|[aá]gua|ch[aá]|lim[aã]o).*(secar|emagrecer|perder)\s*([3-9]|\d+)\s*kg|"
        # Duracao da privacao perguntada sem numero ("quanto tempo aguento sem comer").
        r"(quanto tempo|quantos dias|quantas horas).{0,40}"
        r"(aguent|consigo ficar|posso ficar|d[aá] pra ficar).{0,30}"
        r"sem (comer|me alimentar|se alimentar)|"
        r"sem comer.{0,40}(emagrecer|perder \d+|secar))",
        "Esse jejum eu não vou calcular, porque ele pode te fazer mal.",
        "Compreendo a vontade de ter resultados rápidos, mas práticas como restrições "
        "extremas ou uso de substâncias sem indicação trazem riscos sérios à saúde "
        "(como fraqueza, deficiências nutricionais e alterações metabólicas).",
        "A ciência indica que mudanças sustentáveis e orientadas por um profissional "
        "de saúde são o caminho mais seguro e eficaz.",
    ),
    # Ingestão de substâncias nocivas / tóxicas / entorpecentes
    (
        r"(coca[ií]na|crack|hero[ií]na|anfetamina|rebite|metanfetamina|chumbinho|"
        r"veneno|raticida|[oó]leo mineral em jejum|semente de ma[cç][aã].*c[aâ]ncer|vitamina b17|"
        r"[aá]gua oxigenada|beber desinfetante|queimador(es)? de gordura sem registro|"
        r"subst[aâ]ncia(s)? qu[ií]mica(s)?|detergente|alvejante)",
        "Essa orientação eu não posso te passar, porque essa substância pode te fazer mal.",
        "Compreendo a curiosidade e a vontade de encontrar soluções para o corpo, "
        "mas o uso de substâncias tóxicas, entorpecentes ou não alimentares (como óleo mineral, "
        "drogas ou compostos químicos) traz riscos sérios à saúde (como intoxicação aguda, "
        "pneumonia lipídica, arritmias e perigo imediato à vida).",
        "A ciência indica que o cuidado com a nutrição deve ser feito sempre com base "
        "em escolhas seguras e com orientação de um profissional de saúde.",
    ),
    # Condutas de Transtorno Alimentar agudo / purgativas (Persona Camila)
    (
        r"(como vomitar.*depois de comer|vomitar para emagrecer|quantos laxantes tomar para secar|"
        # Vomito e laxante so contam com intencao de peso: "e normal vomitar depois de
        # comer muito?" e duvida de sintoma e nao pode cair na recusa.
        r"(provocar|induzir|for[cç]ar)\s+(o\s+)?v[oô]mito(?=.*(emagrec|engord|peso|secar|caloria))|"
        r"vomitar(?=.*(emagrec|engord|peso|secar|caloria))|"
        r"laxantes?(?=.*(emagrec|engord|peso|secar|barriga)))",
        "Esse método compensatório eu não vou te ensinar, porque ele pode te fazer mal.",
        "Compreendo o sofrimento ou a culpa que podem surgir em relação à comida e ao corpo, "
        "mas métodos compensatórios e purgativos (como vômito induzido ou abuso de laxantes) "
        "trazem riscos sérios à saúde (como graves desequilíbrios eletrolíticos, desgaste "
        "esofágico e risco iminente de parada cardíaca).",
        "Se você está enfrentando dificuldades com a sua alimentação e imagem corporal, "
        "buscar acolhimento de um psicólogo, psiquiatra ou nutricionista especializado é o "
        "caminho de cuidado mais seguro e importante.",
    ),
    # Abandono de terapia médica essencial (Persona Renata)
    (
        r"(cur(a|ar) (a )?diabetes|parar (a )?metformina|parar (a )?insulina|"
        r"substituir (o )?rem[eé]dio|"
        r"(largar|parar de tomar|abandonar|suspender|tirar|deixar de tomar)\s+"
        r"(o |a |os |as |do |da )?(rem[eé]dio|medica[cç][aã]o|medicamento|insulina|metformina))",
        "Essa troca de medicamento eu não vou indicar, porque ela pode te fazer mal.",
        "Compreendo a vontade de buscar opções mais naturais no dia a dia, mas nenhum "
        "alimento, chá ou prática substitui terapias farmacológicas ou o controle clínico "
        "para diabetes e outras condições crônicas.",
        "A ciência indica que qualquer alteração em medicações deve ser feita "
        "exclusivamente sob acompanhamento médico.",
    ),
]


def reformular_pergunta_amigavel(texto: str) -> str:
    """Reformula a dúvida do usuário em uma interrogação clara, natural e empática."""
    t = texto.strip()
    t = re.sub(r"[!?.]{2,}", "?", t)

    # Mapeamento de termos informais comuns
    regras_amigaveis = [
        (r"\bsecar 10kg\b", "perder 10 kg"),
        (r"\bsecar a barriga\b", "reduzir a gordura abdominal"),
        (r"\bdesinchar a barriga\b", "reduzir o inchaço"),
        (r"\bdesinchar o corpo\b", "reduzir o inchaço"),
        (r"\bdesincha a barriga\b", "reduz o inchaço"),
        (r"\bdesincha o corpo\b", "reduz o inchaço"),
        (r"\bdesinflama o corpo\b", "reduz a inflamação"),
        (r"\bshot de vinagre de ma[cç][aã]\b", "vinagre de maçã"),
        (r"\bshot de vinagre\b", "vinagre de maçã"),
        (r"(\d+)kg\b", r"\1 kg"),
        (r"\s+antes de uma festa\b", ""),
    ]
    for p, r in regras_amigaveis:
        t = re.sub(p, r, t, flags=re.IGNORECASE)

    t = " ".join(t.split())
    if not t.endswith("?"):
        t = f"{t}?"

    if len(t) > 1:
        t = t[0].upper() + t[1:]
    return t


def checar_recusa_segura(
    texto: str,
    pergunta_amigavel: str | None = None,
) -> tuple[bool, str]:
    """Avalia se o texto aciona um guardrail ético e formata a Resposta de Cuidado."""
    texto_norm = texto.lower().strip()
    pergunta = pergunta_amigavel or reformular_pergunta_amigavel(texto)

    for padrao, abertura, justificativa, orientacao in PADROES_RISCO_CRITICO:
        if re.search(padrao, texto_norm):
            resposta_humana = (
                f"Resposta de cuidado\n"
                f"{abertura}\n"
                f"Entendi assim: {pergunta}\n\n"
                f"{justificativa}\n\n"
                f"{orientacao}"
            )
            return True, resposta_humana

    return False, ""


def normalizar_alegacao_heuristica(texto: str) -> str:
    """Normaliza o texto do usuário substituindo girias nutricionais por termos científicos.

    Utilizado como baseline ou fallback quando nao houver LLM extrator conectado.
    """
    normalizado = texto.strip()
    normalizado = re.sub(r"[kK]{3,}", "", normalizado)
    normalizado = re.sub(r"[!?.]{2,}", "?", normalizado)

    for padrao, substituto in MAPA_TERMOS_POPULARES.items():
        normalizado = re.sub(padrao, substituto, normalizado, flags=re.IGNORECASE)

    normalizado = " ".join(normalizado.split())

    # Assegura formato interrogativo caso dúvida
    if not normalizado.endswith("?"):
        normalizado = f"{normalizado}?"

    return normalizado
