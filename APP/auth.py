"""Autenticacao da API: validacao do JWT emitido pelo Supabase Auth.

Dois modos, decididos pela configuracao:

- **Producao/staging**: exige `SUPABASE_JWT_SECRET` e valida assinatura, expiracao e
  audiencia do token. A identidade devolvida e o `sub` (id do usuario no Supabase).
- **Local**: sem o segredo configurado, aceita qualquer token nao vazio e o devolve
  como identidade. Serve para desenvolvimento e para a suite de testes.

O modo local NUNCA vale fora de `APP_ENV=local`: `verificar_configuracao` roda na subida
da aplicacao e derruba o processo se o segredo faltar. Sem essa trava, um deploy com a
variavel esquecida subiria com a autenticacao efetivamente desligada, e o sistema guarda
dado de saude.

A identidade precisa ser ESTAVEL entre sessoes: e ela que indexa o perfil de saude e o
balde do rate limit. Usar o token cru daria um id novo a cada renovacao (o Supabase
rotaciona o access token de hora em hora), o perfil sumiria depois de sair e entrar de
novo e a cota se renovaria sozinha a cada refresh.
"""

import jwt
from fastapi import Depends, Header

from APP.config import Settings, obter_settings
from APP.errors import ApiError

# O Supabase Auth emite tokens HS256 com esta audiencia para usuarios logados.
ALGORITMO = "HS256"
AUDIENCIA = "authenticated"


def verificar_configuracao(settings: Settings) -> None:
    """Falha rapido na subida quando o ambiente nao esta pronto para valer.

    As duas variaveis quebram em silencio quando faltam: sem o segredo, a API aceita
    qualquer token; sem as origens, o navegador bloqueia toda chamada do app antes de
    ela sair da maquina, sem erro no servidor e sem linha de log.
    """
    if settings.app_env == "local":
        return

    faltando = []
    if not settings.supabase_jwt_secret:
        faltando.append("SUPABASE_JWT_SECRET (sem ele a API aceitaria qualquer token)")
    if not settings.origens_permitidas:
        faltando.append("ORIGENS_PERMITIDAS (sem ela o navegador bloqueia as chamadas do app)")

    if faltando:
        raise RuntimeError(
            f"Configuracao obrigatoria ausente com APP_ENV={settings.app_env!r}: "
            + "; ".join(faltando)
        )


def token_do_header(authorization: str | None) -> str | None:
    """Extrai o token do header `Authorization: Bearer <token>`."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip() or None


def identidade_do_token(token: str, settings: Settings) -> str:
    """Devolve a identidade do usuario ou levanta `unauthorized`."""
    if not settings.supabase_jwt_secret:
        return token  # modo local

    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[ALGORITMO],
            audience=AUDIENCIA,
        )
    except jwt.ExpiredSignatureError:
        raise ApiError("unauthorized", 401, "token expirado") from None
    except jwt.InvalidTokenError:
        # Assinatura invalida, audiencia errada, formato quebrado: a causa exata nao volta
        # para o cliente, ela so ajudaria quem esta tentando forjar um token.
        raise ApiError("unauthorized", 401, "token invalido") from None

    usuario = payload.get("sub")
    if not usuario:
        raise ApiError("unauthorized", 401, "token sem identificacao de usuario")
    return usuario


def identidade_do_header(authorization: str | None, settings: Settings | None = None) -> str | None:
    """Mesma identidade da rota, porem sem levantar erro.

    Serve para quem roda ANTES da rota e nao pode interromper a requisicao: o middleware
    de log e a checagem de rate limit. Token ausente ou invalido devolve None, e quem
    chamou decide o que fazer (o log grava `user_id_hash: null`, o rate limit cai no IP).
    """
    token = token_do_header(authorization)
    if token is None:
        return None
    try:
        return identidade_do_token(token, settings or obter_settings())
    except ApiError:
        return None


async def exigir_autenticacao(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(obter_settings),
) -> str:
    """Dependencia das rotas autenticadas. Devolve a identidade do usuario."""
    token = token_do_header(authorization)
    if token is None:
        raise ApiError("unauthorized", 401)
    return identidade_do_token(token, settings)
