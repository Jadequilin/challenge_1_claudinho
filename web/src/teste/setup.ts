import '@testing-library/jest-dom/vitest';

import { configure } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';

// O padrao do findBy e 1s, e o mock simula o atraso de rede da checagem. Sem isto, todo
// teste de fluxo precisaria repetir um timeout proprio.
configure({ asyncUtilTimeout: 5000 });

import { servidor } from './servidor';

// O mesmo mock do navegador roda nos testes, entao teste e desenvolvimento nao divergem.
beforeAll(() => servidor.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  servidor.resetHandlers();
  localStorage.clear();
});
afterAll(() => servidor.close());
