import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { App } from './App';
import { definirToken } from './lib/api/cliente';
import { iniciarTema } from './lib/tema';
import './estilos/claudinho.css';
import './estilos/app.css';

/**
 * Sessao provisória.
 *
 * A API exige `Authorization: Bearer`, e o login anônimo do Supabase ainda não existe no
 * backend (ver Docs/Design/design-system.md, secao 8.2). Até lá, o app manda um token de
 * desenvolvimento, que só o modo local da API aceita. Apontar para staging hoje devolve
 * 401 em toda chamada.
 *
 * Este valor NUNCA pode virar um token real: tudo que começa com `VITE_` é embutido no
 * bundle e fica legível para qualquer visitante. O token de verdade virá do
 * `signInAnonymously` em tempo de execução.
 */
definirToken(import.meta.env.VITE_API_TOKEN ?? 'token-de-desenvolvimento');

iniciarTema();

async function iniciar() {
  // `import.meta.env.DEV` vira `false` no build de produção, então este bloco inteiro sai
  // do pacote final. É a garantia de que um `.env` esquecido não publica um app
  // respondendo com os estudos inventados do mock, que seria o pior defeito possível num
  // produto de checagem de desinformação em saúde.
  if (import.meta.env.DEV && import.meta.env.VITE_API_MOCK === 'true') {
    try {
      const { worker } = await import('./mocks/navegador');
      // Com limite de tempo: em navegador que bloqueia service worker, o start fica
      // pendurado e o app nunca monta. Tela em branco e o pior jeito de descobrir isso.
      await Promise.race([
        worker.start({ onUnhandledRequest: 'bypass' }),
        new Promise((_, rejeitar) =>
          setTimeout(() => rejeitar(new Error('o service worker do mock demorou demais')), 3000),
        ),
      ]);
    } catch (erro) {
      // Se o mock nao subir, o app ainda precisa aparecer: tela em branco nao diz nada
      // para quem esta desenvolvendo, e o console diz.
      console.error('Mock da API não iniciou. O app vai tentar falar com a API de verdade.', erro);
    }
  }

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </StrictMode>,
  );
}

void iniciar();
