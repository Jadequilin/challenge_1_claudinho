import { Check, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';

import { Aviso } from '../componentes/Aviso';
import { Bolha } from '../componentes/Bolha';
import { Botao } from '../componentes/Botao';
import { ErroDaApi, MENSAGEM_DE_ERRO, checarAlegacao } from '../lib/api/cliente';
import type { PedidoDeChecagem } from '../lib/api/tipos';
import type { ItemDoHistorico } from '../lib/armazenamento';
import { gravar, registrarNoHistorico } from '../lib/armazenamento';

interface EstadoDaRota {
  pedido: PedidoDeChecagem;
  entrada: string;
  origem?: ItemDoHistorico['origem'];
}

/**
 * Progresso da checagem.
 *
 * Duas coisas aqui são menos óbvias do que parecem:
 *
 * 1. **Cancelar precisa cancelar de verdade.** Sem abortar a requisição, a resposta chega
 *    depois, entra no histórico e joga a pessoa para uma tela que ela desistiu de ver. Na
 *    recusa segura isso é grave: cancelar é o gesto de quem se arrependeu de perguntar.
 * 2. **Tentar de novo precisa refazer o pedido.** Por isso a tentativa é estado, e não um
 *    booleano em ref: é ela que reexecuta o efeito. A limpeza do efeito cuida do disparo
 *    duplo do StrictMode, abortando a primeira requisição.
 *
 * A alegação extraída apareceria aqui, antes da resposta, como pede a Docs/User/02, seção
 * 2.4. Depende de a API devolver esse campo em separado, e tem issue própria.
 */
export function Carregando() {
  const { state } = useLocation();
  const navegar = useNavigate();
  const [passo, setPasso] = useState(0);
  const [erro, setErro] = useState<ErroDaApi | null>(null);
  const [tentativa, setTentativa] = useState(0);

  const dados = state as EstadoDaRota | null;

  useEffect(() => {
    if (!dados) return;

    const controlador = new AbortController();
    let cancelado = false;

    const relogio = setInterval(() => setPasso((atual) => Math.min(atual + 1, 2)), 900);

    checarAlegacao(dados.pedido, controlador.signal)
      .then((resposta) => {
        if (cancelado) return;
        const guardado = registrarNoHistorico({
          em: Date.now(),
          entrada: dados.entrada,
          origem: dados.origem,
          resposta,
        });
        gravar('rascunho', '');
        navegar(`/resultado/${guardado.id}`, { replace: true });
      })
      .catch((falha: unknown) => {
        // Aborto é saída pela porta da frente: a tela já foi embora, não há o que mostrar.
        if (cancelado || (falha instanceof DOMException && falha.name === 'AbortError')) return;
        setErro(
          falha instanceof ErroDaApi ? falha : new ErroDaApi('desconhecido', 0, String(falha)),
        );
      })
      .finally(() => clearInterval(relogio));

    return () => {
      cancelado = true;
      controlador.abort();
      clearInterval(relogio);
    };
    // `tentativa` está nas dependências de propósito: mudá-la é o que refaz a checagem.
  }, [dados, navegar, tentativa]);

  if (!dados) return <Navigate to="/" replace />;

  /** Volta para a checagem devolvendo o que a pessoa escreveu, para ela não digitar de novo. */
  function voltarComRascunho() {
    const pedido = dados?.pedido;
    if (pedido?.input_type === 'text' && pedido.text) gravar('rascunho', pedido.text);
    else if (pedido?.input_type === 'url' && pedido.url) gravar('rascunho', pedido.url);
    navegar('/');
  }

  const passos = [
    dados.pedido.input_type === 'url'
      ? 'Abrindo o post'
      : dados.pedido.input_type === 'image'
        ? 'Lendo o texto do print'
        : 'Entendendo sua dúvida',
    'Procurando nos estudos',
    'Escrevendo a resposta',
  ];

  return (
    <div className="tela">
      <header className="tela-topo">
        <button className="icon-btn" aria-label="Cancelar checagem" onClick={voltarComRascunho}>
          <X aria-hidden="true" />
        </button>
        <span className="topbar-title">Checando</span>
      </header>

      <main className="tela-conteudo">
        <div className="conversa">
          <Bolha origem={dados.origem}>{dados.entrada}</Bolha>

          {erro ? (
            <Aviso
              tipo="erro"
              titulo="Não consegui terminar a checagem"
              acoes={
                <>
                  <Botao
                    pequeno
                    variante="secundaria"
                    onClick={() => {
                      // Quem limpa o erro e o progresso é o evento, não o efeito: efeito
                      // que chama setState em cascata dispara render a mais sem precisar.
                      setErro(null);
                      setPasso(0);
                      setTentativa((n) => n + 1);
                    }}
                  >
                    Tentar de novo
                  </Botao>
                  <Botao pequeno variante="discreta" onClick={voltarComRascunho}>
                    Voltar
                  </Botao>
                </>
              }
            >
              {MENSAGEM_DE_ERRO[erro.codigo]}
              {erro.tentarEm ? ` Tente de novo em ${erro.tentarEm} segundos.` : ''}
            </Aviso>
          ) : (
            <>
              <div className="reply reply-pendente" aria-live="polite">
                <ol className="steps">
                  {passos.map((rotulo, indice) => {
                    const estado = indice < passo ? 'done' : indice === passo ? 'active' : 'todo';
                    return (
                      <li className="step" data-state={estado} key={rotulo}>
                        <span className="step-mark">
                          {estado === 'done' ? (
                            <Check aria-hidden="true" />
                          ) : estado === 'active' ? (
                            <span className="spinner" />
                          ) : (
                            <span className="dot" />
                          )}
                        </span>
                        {rotulo}
                      </li>
                    );
                  })}
                </ol>
              </div>

              <div className="pilha-curta" aria-hidden="true">
                <div className="skeleton" style={{ width: '92%' }} />
                <div className="skeleton" style={{ width: '100%' }} />
                <div className="skeleton" style={{ width: '74%' }} />
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
