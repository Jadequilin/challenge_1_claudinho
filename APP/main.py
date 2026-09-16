from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from APP.auth import verificar_configuracao
from APP.config import obter_settings
from APP.errors import registrar_handlers
from APP.middleware import LoggingDeInferencia
from APP.observabilidade import configurar_logging
from APP.routers import check_claim, feedback, health, profile

app = FastAPI(
    title="Claudinho — API de checagem de desinformacao nutricional",
    version="0.1.0",
    description=(
        "Challenge 1. O endpoint /check-claim ainda responde com dados MOCKADOS: "
        "o contrato esta congelado, o pipeline de RAG entra depois."
    ),
)

settings = obter_settings()
# Derruba a subida se o ambiente nao estiver pronto, em vez de deixar a API responder
# com a autenticacao desligada ou com o CORS barrando o app inteiro.
verificar_configuracao(settings)

configurar_logging()
app.add_middleware(LoggingDeInferencia)
# O app e um PWA em outro dominio, entao sem CORS o navegador bloqueia toda chamada.
# Em local a lista vem vazia e o valor abaixo libera o servidor de desenvolvimento.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origens_permitidas or ["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
registrar_handlers(app)
app.include_router(health.router)
app.include_router(check_claim.router)
app.include_router(feedback.router)
app.include_router(profile.router)
