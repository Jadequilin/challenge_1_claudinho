# Deploy do Claudinho

Três peças, cada uma num lugar:

```
App (Expo) ──HTTPS──> API (Vercel) ──> Supabase (dados + pgvector)
                          │
                          ├──> Space de embeddings  (deploy/embeddings-space)
                          └──> Space do Ollama      (deploy/ollama-space)  ──reserva──> Gemini
```

A API **não carrega nenhum modelo**. É isso que a faz caber na Vercel: sem o
`sentence-transformers`, o runtime ocupa cerca de 64 MB, contra 4,4 GB antes, e o limite
da Vercel é 500 MB por função.

Ordem recomendada: **1)** Space de embeddings, **2)** Space do Ollama, **3)** API. A API
depende das duas primeiras para responder de verdade.

---

## 1. Space de embeddings

Siga `deploy/embeddings-space/README.md`. Ao final você tem uma URL do tipo
`https://<usuario>-<space>.hf.space` que responde com `"dimensao": 768`.

## 2. Space do Ollama

Siga `deploy/ollama-space/README.md` (já no ar pela Beatriz).

## 3. API na Vercel

1. Em https://vercel.com/new, importe o repositório do GitHub.
2. **Root Directory:** a raiz do repositório (onde estão `vercel.json` e `api/`).
3. **Framework Preset:** deixe a Vercel detectar (Python/FastAPI). Não configure comando
   de build nem de instalação: ela instala pelo `pyproject.toml`.
4. Em **Environment Variables**, cadastre as variáveis da tabela abaixo.
5. Clique em **Deploy**.

### Variáveis de ambiente

| Variável | Valor | Obrigatória |
|---|---|---|
| `APP_ENV` | `production` | Sim |
| `SUPABASE_URL` | URL do projeto Supabase | Sim |
| `SUPABASE_KEY` | chave do Supabase | Sim |
| `SUPABASE_JWT_SECRET` | Supabase → Project Settings → API → JWT Secret | Sim: sem ela, a API se recusa a subir fora do modo local |
| `EMBEDDINGS_URL` | URL do Space de embeddings | Sim: sem ela, a API tenta carregar o modelo localmente e falha |
| `EMBEDDINGS_TOKEN` | token de leitura do Hugging Face | Sim, se o Space for privado |
| `LLM_BASE_URL` | `https://<usuario>-<space>.hf.space/v1` (Space do Ollama) | Recomendada |
| `LLM_API_KEY` | token de leitura do Hugging Face | Se o Space for privado |
| `GEMINI_API_KEY` | chave do Gemini | Reserva do Ollama |
| `ORIGENS_PERMITIDAS` | `["https://dominio-do-app"]` | Sim, se o app rodar no navegador |

### Conferindo

    curl https://<projeto>.vercel.app/health

Deve responder `{"status": "ok", "environment": "production", ...}`. A documentação
interativa fica em `https://<projeto>.vercel.app/docs`.

Depois, rode o teste de estresse contra o deploy para medir a latência real:

    uv run python -m benchmarks.estresse --url https://<projeto>.vercel.app --usuarios 3 --requisicoes 6

(Em produção o JWT é validado, então o estresse com identidades falsas vai receber 401.
Para medir com JWT real, use o benchmark com `--token`.)

---

## O que se comporta diferente na Vercel

A Vercel roda a API em instâncias que sobem e somem conforme a demanda. Três efeitos:

- **Perfil e feedback em memória.** Os dois repositórios ainda são os em memória
  (`APP/repositorios/perfil.py` e `APP/repositorios/feedback.py`), esperando as tabelas
  `profiles` e `feedback` no Supabase; o passo a passo está no docstring de cada
  `RepositorioSupabase`. Na Vercel, um perfil ou feedback salvo numa requisição pode não
  existir na seguinte. **Precisam das tabelas antes de serem usados de verdade.**
- **Rate limit por instância.** O contador fica na memória de cada instância, então o limite
  de 10/min vale por instância, não por usuário no total. Aceitável para o MVP; para valer de
  verdade, o contador vai para o Redis (Upstash), como previsto no `Docs/Production/03`.
- **Primeira chamada lenta.** Instância nova (cold start) e Space dormindo somam atraso na
  primeira checagem depois de um tempo parado. Se o Space de embeddings não responder, a API
  devolve **503** ("tente de novo em instantes"), e não uma falsa resposta de "sem evidência".

---

## Alternativa: Render

Se a Vercel der problema, o mesmo código sobe no Render pelo `Dockerfile`, que também não
instala mais o torch:

1. https://dashboard.render.com → **New → Web Service** → conecte o repositório.
2. **Runtime:** Docker. **Plan:** Free.
3. As mesmas variáveis de ambiente da tabela acima.

O Render roda um processo contínuo, então o perfil em memória e o rate limit se comportam
de forma consistente enquanto ele está acordado. Em compensação, o plano gratuito dorme
após 15 minutos sem uso, e o primeiro acesso depois disso demora para acordar.

---

## Desenvolvimento local

Sem `EMBEDDINGS_URL`, a API usa o modelo local. Instale as dependências de ML:

    uv pip install -r requirements-dev.txt -r requirements-ml.txt

Com `EMBEDDINGS_URL` apontando para o Space, basta o `requirements-dev.txt`.
