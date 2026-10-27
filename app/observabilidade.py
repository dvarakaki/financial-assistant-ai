"""
Registro do que o Assessor faz em cada turno.

A tela de monitoramento não fala com o LangSmith. Ela pergunta para a nossa
API, e a API lê o que este módulo anotou enquanto o fluxo rodava.

Cada chamada de modelo (Gemini ou Groq) deixa: nome do modelo, tokens, custo
e latência. Cada mensagem do usuário deixa: rota, status e a soma das chamadas
daquele turno. O preço é uma tabela fixa, com os modelos configurados em
app/llms.py — o centavo pode divergir do LangSmith, que usa a tabela dele.

Qual "nó" fez a chamada
------------------------
O roteiro desta etapa detecta o nó lendo a metadata que o LangGraph injeta
automaticamente em cada chamada de modelo dentro de um StateGraph. Este
projeto não tem StateGraph: executar_fluxo_assessor encadeia chamadas Python
simples (guardrail -> roteador -> especialista -> orquestrador -> guardrail),
então essa metadata não existe. Em vez dela, cada ponto de chamada se marca
explicitamente com `no_atual(...)` antes de invocar o modelo — é a mesma
ideia, só que o nó é declarado pelo código que já sabe onde está, em vez de
lido de volta de uma metadata que o framework não preenche aqui.

Preços por 1 milhão de tokens (entrada, saída), em dólar — placeholders:
os IDs configurados em app/llms.py (gemini-3.6-flash, qwen/qwen3.8-27b) não
correspondem a nenhuma tabela pública real; os valores abaixo só existem
para a faixa de custo não ficar sempre zerada. Ajuste quando os modelos
reais do projeto forem definidos.
"""
from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

_FUSO = ZoneInfo("America/Sao_Paulo")

# USD por 1 milhão de tokens: (entrada, saída).
PRECO_POR_MILHAO: dict[str, tuple[float, float]] = {
    "gemini-3.6-flash":  (0.30, 2.50),
    "qwen/qwen3.8-27b":  (0.15, 0.60),
}

# O especialista promete Gemini. Groq neste nó é o with_fallbacks de llms.py.
_NOS_ESPECIALISTA = {"financeiro", "agenda"}
_MODELO_ESPECIALISTA = "gemini-3.6-flash"

LIMITE_TURNOS = 50
LIMITE_P95_MS = 8_000
LIMITE_TAXA_ERRO = 0.05

_lock = threading.Lock()
_inicio_processo = time.time()
_em_andamento = 0
_turnos: list[dict[str, Any]] = []
_chamadas: list[dict[str, Any]] = []
_abertos: dict[str, float] = {}
_runs: dict[str, dict[str, Any]] = {}
_ligado = False


def _agora_local() -> str:
    return datetime.now(_FUSO).strftime("%H:%M:%S")


def _nome_modelo(serialized: dict | None, invocation_params: dict | None, resposta_meta: dict | None) -> str:
    candidatos = []
    for fonte in (resposta_meta or {}, invocation_params or {}, (serialized or {}).get("kwargs") or {}):
        for chave in ("model_name", "model"):
            valor = fonte.get(chave)
            if valor:
                candidatos.append(str(valor))
    for nome in candidatos:
        if nome.startswith("models/"):
            nome = nome.split("/", 1)[1]
        return nome
    return "desconhecido"


def _tokens(message: Any) -> tuple[int, int]:
    usage = getattr(message, "usage_metadata", None) or {}
    if not isinstance(usage, dict):
        usage = {
            "input_tokens": getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "output_tokens", 0),
        }
    entrada = int(usage.get("input_tokens") or 0)
    saida = int(usage.get("output_tokens") or 0)
    if entrada or saida:
        return entrada, saida

    meta = getattr(message, "response_metadata", None) or {}
    bruto = meta.get("token_usage") or meta.get("usage") or {}
    entrada = int(bruto.get("prompt_tokens") or bruto.get("input_tokens") or 0)
    saida = int(bruto.get("completion_tokens") or bruto.get("output_tokens") or 0)
    return entrada, saida


def custo_usd(modelo: str, entrada: int, saida: int) -> float:
    precos = PRECO_POR_MILHAO.get(modelo)
    if precos is None:
        for chave, valor in PRECO_POR_MILHAO.items():
            if chave in modelo:
                precos = valor
                break
    if precos is None:
        return 0.0
    preco_entrada, preco_saida = precos
    return (entrada * preco_entrada + saida * preco_saida) / 1_000_000


def _eh_fallback(no: str, modelo: str) -> bool:
    if no not in _NOS_ESPECIALISTA:
        return False
    return _MODELO_ESPECIALISTA not in modelo


# ------------------------------------------------------------------
# Qual nó está chamando o modelo agora, nesta thread.
#
# Sem StateGraph não há metadata de grafo para ler de volta, então quem
# sabe o nó é o próprio chamador: graph.py e guardrail.py entram em
# `with no_atual("financeiro"):` (ou "roteador", "guardrail_entrada" etc.)
# antes de cada .invoke(). O callback só lê o que já foi declarado.
# ------------------------------------------------------------------
_no_por_thread = threading.local()


@contextmanager
def no_atual(nome: str):
    anterior = getattr(_no_por_thread, "nome", None)
    _no_por_thread.nome = nome
    try:
        yield
    finally:
        _no_por_thread.nome = anterior


def _no_da_thread() -> str:
    return getattr(_no_por_thread, "nome", None) or "outro"


# O id do turno vive num atributo de thread, no mesmo espírito do nó acima:
# o endpoint roda numa thread do uvicorn, e as chamadas de modelo acontecem
# nela. contextvars quebram quando o LangGraph copia o contexto sem este
# valor.
_turno_por_thread = threading.local()


def _turno_da_thread() -> str | None:
    return getattr(_turno_por_thread, "turno_id", None)


class ColetorChamadas(BaseCallbackHandler):
    """Anota cada chamada de chat model sem guardar o texto do prompt."""

    raise_error = False

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        invocation = kwargs.get("invocation_params") or {}
        with _lock:
            _runs[str(run_id)] = {
                "t0": time.perf_counter(),
                "modelo": _nome_modelo(serialized, invocation, None),
                "no": _no_da_thread(),
                "turno_id": _turno_da_thread(),
            }

    def on_llm_end(self, response: LLMResult, *, run_id: Any, **kwargs: Any) -> None:
        chave = str(run_id)
        with _lock:
            abertura = _runs.pop(chave, None)
        if abertura is None or not abertura.get("turno_id"):
            return

        message = None
        try:
            message = response.generations[0][0].message
        except (IndexError, AttributeError):
            message = None

        entrada, saida = _tokens(message) if message is not None else (0, 0)
        meta = getattr(message, "response_metadata", None) if message is not None else None
        modelo = _nome_modelo(None, None, meta)
        if modelo == "desconhecido":
            modelo = abertura["modelo"]

        latencia_ms = int((time.perf_counter() - abertura["t0"]) * 1000)
        registro = {
            "turno_id": abertura["turno_id"],
            "modelo": modelo,
            "no": abertura["no"],
            "tokens_entrada": entrada,
            "tokens_saida": saida,
            "custo_usd": custo_usd(modelo, entrada, saida),
            "latencia_ms": latencia_ms,
            "fallback": _eh_fallback(abertura["no"], modelo),
        }
        with _lock:
            _chamadas.append(registro)

    def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        with _lock:
            _runs.pop(str(run_id), None)


coletor = ColetorChamadas()


def ligar_coleta() -> None:
    """Põe o coletor nos três modelos, uma vez por processo."""
    global _ligado
    if _ligado:
        return
    from app.llms import llm_gemini, llm_groq, llm_rapido

    for modelo in (llm_gemini, llm_groq, llm_rapido):
        atuais = list(modelo.callbacks or [])
        if not any(isinstance(item, ColetorChamadas) for item in atuais):
            modelo.callbacks = [*atuais, coletor]
    _ligado = True


def abrir_turno() -> str:
    ligar_coleta()
    turno_id = uuid.uuid4().hex
    _turno_por_thread.turno_id = turno_id
    with _lock:
        global _em_andamento
        _em_andamento += 1
        _abertos[turno_id] = time.perf_counter()
    return turno_id


def fechar_turno(turno_id: str, session_id: str, rota: str, status: str) -> None:
    _turno_por_thread.turno_id = None
    with _lock:
        inicio = _abertos.pop(turno_id, None)
        if inicio is None:
            return
        global _em_andamento
        _em_andamento = max(0, _em_andamento - 1)

        do_turno = [c for c in _chamadas if c["turno_id"] == turno_id]
        _turnos.append({
            "id": turno_id,
            "hora": _agora_local(),
            "session_id": session_id,
            "latencia_ms": int((time.perf_counter() - inicio) * 1000),
            "rota": rota or "—",
            "status": status,
            "tokens_total": sum(c["tokens_entrada"] + c["tokens_saida"] for c in do_turno),
            "custo_usd": sum(c["custo_usd"] for c in do_turno),
        })

        while len(_turnos) > LIMITE_TURNOS:
            antigo = _turnos.pop(0)
            _chamadas[:] = [c for c in _chamadas if c["turno_id"] != antigo["id"]]


def listar_turnos() -> list[dict[str, Any]]:
    with _lock:
        return [
            {chave: valor for chave, valor in turno.items() if chave != "id"}
            for turno in _turnos
        ]


def listar_chamadas() -> list[dict[str, Any]]:
    with _lock:
        return [
            {chave: valor for chave, valor in chamada.items() if chave != "turno_id"}
            for chamada in _chamadas
        ]


def situacao() -> dict[str, int]:
    with _lock:
        return {
            "em_andamento": _em_andamento,
            "no_ar_segundos": int(time.time() - _inicio_processo),
        }
