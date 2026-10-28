import threading
from contextlib import contextmanager

import psycopg2
from langchain_core.runnables import RunnableConfig

from app.config import DATABASE_URL


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL não foi configurada nas variáveis de ambiente.")
    return psycopg2.connect(DATABASE_URL)


class TransacaoTurno:
    """Uma transação Postgres que dura o turno inteiro (etapa 8).

    As tools de escrita gravam aqui sem commit. Quem decide se a escrita
    permanece é executar_fluxo_assessor (app/graph.py), depois do juiz:
    aprovado -> confirmar(); qualquer outro caso -> fechar() sem confirmar,
    e o Postgres descarta tudo. Se o processo cair no meio do turno, a
    conexão cai junto e o efeito é o mesmo.

    A conexão só abre na primeira escrita: turno de FAQ ou de consulta não
    paga a conexão, e um banco fora do ar continua virando o erro amigável
    da tool, como antes.
    """

    def __init__(self) -> None:
        self._conn = None
        # O ToolNode roda as tool calls de uma mesma resposta em paralelo
        # (threads). O cursor e a sequência de SAVEPOINT não podem se
        # misturar entre elas, então uma escrita espera a outra terminar.
        self._lock = threading.Lock()

    @contextmanager
    def escrita(self):
        """Cursor para uma escrita, isolada num SAVEPOINT.

        Faz o papel do rollback() que cada tool tinha: um erro desfaz só
        esta escrita, não as anteriores do mesmo turno.
        """
        with self._lock:
            if self._conn is None:
                self._conn = get_conn()
            cur = self._conn.cursor()
            try:
                cur.execute("SAVEPOINT escrita;")
                yield cur
                cur.execute("RELEASE SAVEPOINT escrita;")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT escrita;")
                raise
            finally:
                cur.close()

    def confirmar(self) -> None:
        if self._conn is not None:
            self._conn.commit()

    def fechar(self) -> None:
        # Fechar sem commit descarta o que não foi confirmado.
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def transacao_do_turno(config: RunnableConfig) -> TransacaoTurno:
    """A transação do turno, que vem no RunnableConfig — mesmo caminho do
    user_id em app/tools/perfil.py. O modelo nunca preenche esse valor."""
    transacao = (config or {}).get("configurable", {}).get("transacao")
    if transacao is None:
        raise RuntimeError("Escrita fora de um turno: sem transação no RunnableConfig.")
    return transacao
