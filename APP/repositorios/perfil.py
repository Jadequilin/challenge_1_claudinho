"""Persistencia do perfil de saude.

Mesma estrutura do `APP/repositorios/feedback.py`, e pelo mesmo motivo: a tabela
`profiles` ainda NAO existe no Supabase (o schema em Docs/Data/02_armazenamento_e_estrutura.md
tem `sources`, `training_data` e `chunks`). O acesso fica atras de uma interface para
que a rota ja funcione hoje, guardando em memoria, e a troca depois seja em um lugar so.

O consentimento da LGPD NAO e checado aqui de proposito: quem recusa perfil com condicao
clinica sem `consent_health_data` e o validador do `Profile` em APP/schemas.py, antes do
dado chegar neste modulo. Duplicar a regra daria a impressao de duas travas quando existe
uma so, e a copia daqui nunca teria como ser exercitada por teste.
"""

from typing import Protocol

from APP.schemas import Profile


class RepositorioDePerfil(Protocol):
    def salvar(self, usuario_hash: str, perfil: Profile) -> Profile:
        """Cria ou substitui o perfil do usuario e devolve o que ficou gravado."""
        ...

    def buscar(self, usuario_hash: str) -> Profile | None:
        """Devolve o perfil do usuario, ou None se ele ainda nao preencheu."""
        ...


class RepositorioEmMemoria:
    """Implementacao atual: um dicionario dentro do processo.

    NAO e persistencia: some quando o processo reinicia, e cada instancia da API tem o
    seu proprio dicionario. Na pratica o usuario perde o perfil a cada deploy. Serve
    enquanto o alvo e demo local e a tabela nao existe.
    """

    efemero = True

    def __init__(self) -> None:
        self.perfis: dict[str, Profile] = {}

    def salvar(self, usuario_hash: str, perfil: Profile) -> Profile:
        self.perfis[usuario_hash] = perfil
        return perfil

    def buscar(self, usuario_hash: str) -> Profile | None:
        return self.perfis.get(usuario_hash)

    def limpar(self) -> None:
        """Usado pelos testes para isolar um caso do outro."""
        self.perfis.clear()


class RepositorioSupabase:
    """Implementacao definitiva, falta a tabela.

    ------------------------------------------------------------------
    O QUE FAZER PARA LIGAR ISSO (na ordem):
    ------------------------------------------------------------------

    1) Combinar o schema com a frente de Dados (Beatriz), que e a dona do
       Docs/Data/02_armazenamento_e_estrutura.md. Ponto de partida, derivado do contrato
       da secao 2.3 do Production/01:

           create table profiles (
             user_id             uuid primary key references auth.users(id) on delete cascade,
             sex                 text check (sex in ('F','M','outro','nao_informado')),
             birth_date          date,
             height_cm           int,
             weight_kg           numeric,
             conditions          text[] not null default '{}',
             dietary_restrictions text[] not null default '{}',
             routine             text check (routine in ('sedentaria','leve','moderada','intensa')),
             consent_health_data boolean not null default false,
             updated_at          timestamptz not null default now()
           );

       Dois pontos para decidir com a Maria Clara antes de rodar:

       - `conditions` e dado sensivel de saude. Vale definir prazo de expurgo e como
         atender o `DELETE /profile` previsto para depois do MVP.
       - Gestacao e amamentacao entram em `conditions` ou ganham coluna propria? O
         Docs/User/01 deixou isso em aberto, e os filtros do Ethics/02 dependem da
         resposta.

    2) Habilitar RLS: cada usuario le e escreve apenas a propria linha. Sem isso, um
       usuario autenticado le a condicao clinica dos outros.

    3) Implementar `salvar` e `buscar` com o client sincrono do Supabase, indexando por
       `user_id` (o `sub` do JWT), e nao pelo hash: o hash serve para o log, a tabela usa
       a FK de verdade.

    4) Trocar a implementacao em `obter_repositorio_de_perfil` e apagar este aviso.
    """

    def salvar(self, usuario_hash: str, perfil: Profile) -> Profile:
        raise NotImplementedError(
            "A tabela `profiles` ainda nao existe no Supabase. "
            "Veja o passo a passo no docstring de RepositorioSupabase "
            "(APP/repositorios/perfil.py)."
        )

    def buscar(self, usuario_hash: str) -> Profile | None:
        raise NotImplementedError(
            "A tabela `profiles` ainda nao existe no Supabase. "
            "Veja o passo a passo no docstring de RepositorioSupabase "
            "(APP/repositorios/perfil.py)."
        )


# Instancia unica: sem isso cada requisicao criaria um dicionario novo e o perfil
# salvo sumiria dentro do mesmo processo.
_repositorio_em_memoria = RepositorioEmMemoria()


def obter_repositorio_de_perfil() -> RepositorioDePerfil:
    """Dependencia do FastAPI que entrega o repositorio em uso.

    QUANDO A TABELA EXISTIR: troque o retorno por `RepositorioSupabase()`.
    """
    return _repositorio_em_memoria
