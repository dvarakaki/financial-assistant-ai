from typing import Optional, List
from langchain.tools import tool
from pydantic import BaseModel, Field

from app.infra.db import get_conn


class AddTransactionArgs(BaseModel):
    amount: float = Field(..., description="Valor da transação (use positivo).")
    source_text: str = Field(..., description="Texto original do usuário.")
    occurred_at: Optional[str] = Field(default=None, description="Timestamp ISO 8601; se ausente, usa NOW().")
    type_id: Optional[int] = Field(default=None, description="ID (1=INCOME, 2=EXPENSES, 3=TRANSFER).")
    type_name: Optional[str] = Field(default=None, description="Nome do tipo: INCOME | EXPENSES | TRANSFER.")
    category_id: Optional[int] = Field(default=None, description="ID da categoria.")
    category_name: Optional[str] = Field(default=None, description="Nome da categoria (comida, lazer, etc).")
    description: Optional[str] = Field(default=None, description="Descrição opcional.")
    payment_method: Optional[str] = Field(default=None, description="Forma de pagamento.")

class QueryTransactionsArgs(BaseModel):
    description: Optional[str] = Field(None, description="Busca por texto na descrição ou no texto original.")
    transaction_type: Optional[str] = Field(None, description="Filtrar por: INCOME ou EXPENSES.")
    date_from: Optional[str] = Field(None, description="Data inicial (YYYY-MM-DD).")
    date_to: Optional[str] = Field(None, description="Data final (YYYY-MM-DD).")

class DailyBalanceArgs(BaseModel):
    date_local: str = Field(..., description="Data para consulta (YYYY-MM-DD).")

# --- MAPEAMENTOS (ALIASES) ---

alias_transaction = {
    "INCOME": "INCOME", "ENTRADA": "INCOME", "SALARIO": "INCOME", "GANHEI": "INCOME", "RECEBA": "INCOME",
    "EXPENSE": "EXPENSES", "EXPENSES": "EXPENSES", "DESPESA": "EXPENSES", "PAGO": "EXPENSES", "COMPRA": "EXPENSES", "GASTO": "EXPENSES",
    "TRANSFER": "TRANSFER", "TRANSFERENCIA": "TRANSFER"
}

alias_category = {
    "comida": "comida", "besteira": "besteira", "estudo": "estudo", "férias": "férias", "transporte": "transporte",
    "moradia": "moradia", "saúde": "saúde", "lazer": "lazer", "contas": "contas",
    "investimento": "investimento", "presente": "presente", "outros": "outros"
}


def _resolve_type_category(cur, category_id: Optional[int], category_name: Optional[str]) -> int:
    if category_name:
        c = category_name.strip().lower()
        c = alias_category.get(c, c)
        cur.execute("SELECT id FROM categories WHERE LOWER(name) = %s LIMIT 1;", (c,))
        row = cur.fetchone()
        if row: return row[0]
    return int(category_id) if category_id else 12

def _resolve_type_transaction(cur, type_id: Optional[int], type_name: Optional[str]) -> Optional[int]:
    if type_name:
        t = type_name.strip().upper()
        t = alias_transaction.get(t, t)
        cur.execute("SELECT id FROM transaction_types WHERE UPPER(type)=%s LIMIT 1;", (t,))
        row = cur.fetchone()
        if row: return row[0]
    return int(type_id) if type_id else None

def _execute_select(query: str, params: tuple = ()) -> Optional[list]:
    """Retorna as linhas da consulta, ou None se a consulta falhar."""
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(query, params)
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception as e:
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def _local_date_filter_sql(field: str = "occurred_at") -> str:
    """
    Retorna um trecho SQL para filtragem por dia local em America/Sao_Paulo.
    Ex.: (occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s::date
    """
    return f"(({field} AT TIME ZONE 'America/Sao_Paulo')::date = %s::date)"


# --- FERRAMENTAS (TOOLS) ---

@tool("add_transaction", args_schema=AddTransactionArgs)
def add_transaction(
    amount: float, source_text: str, occurred_at: Optional[str] = None,
    type_id: Optional[int] = None, type_name: Optional[str] = None,
    category_id: Optional[int] = None, category_name: Optional[str] = None,
    description: Optional[str] = None, payment_method: Optional[str] = None,
) -> dict:
    """Insere uma transação financeira no banco de dados Postgres."""
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        resolved_type = _resolve_type_transaction(cur, type_id, type_name)
        if not resolved_type:
            return {"status": "error", "message": "Tipo de transação inválido."}
        
        resolved_cat = _resolve_type_category(cur, category_id, category_name)

        if occurred_at:
            sql = """INSERT INTO transactions (amount, type, category_id, description, payment_method, occurred_at, source_text)
                     VALUES (%s, %s, %s, %s, %s, %s::timestamptz, %s) RETURNING id, occurred_at;"""
            cur.execute(sql, (amount, resolved_type, resolved_cat, description, payment_method, occurred_at, source_text))
        else:
            sql = """INSERT INTO transactions (amount, type, category_id, description, payment_method, occurred_at, source_text)
                     VALUES (%s, %s, %s, %s, %s, NOW(), %s) RETURNING id, occurred_at;"""
            cur.execute(sql, (amount, resolved_type, resolved_cat, description, payment_method, source_text))

        new_id, occurred = cur.fetchone()
        conn.commit()
        return {"status": "ok", "id": new_id, "occurred_at": str(occurred)}
    except Exception as e:
        if conn:
            conn.rollback()
        return {"status": "error", "message": "Não foi possível registrar a transação no momento."}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@tool("query_transactions", args_schema=QueryTransactionsArgs)
def query_transactions(
    description: Optional[str] = None, transaction_type: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None
) -> list:
    """Consulta transações com filtros por texto (source_text/description), tipo (type) e datas."""
    order = "ASC" if (date_from and date_to) else "DESC"
    sql = "SELECT SUM(amount) FROM transactions WHERE 1=1"
    params = []

    if description:
        sql += " AND (description ILIKE %s OR source_text ILIKE %s)"
        params.extend([f"%{description}%", f"%{description}%"])
    if transaction_type:
        t = alias_transaction.get(transaction_type.upper(), transaction_type.upper())
        sql += " AND type = (SELECT id FROM transaction_types WHERE type = %s)"
        params.append(t)
    if date_from:
        sql += " AND (occurred_at AT TIME ZONE 'America/Sao_Paulo')::date >= %s"
        params.append(date_from)
    if date_to:
        sql += " AND (occurred_at AT TIME ZONE 'America/Sao_Paulo')::date <= %s"
        params.append(date_to)

    result = _execute_select(sql, tuple(params))
    if result is None:
        return {"status": "error", "message": "Não foi possível consultar as transações no momento."}
    return result

@tool("total_balance")
def total_balance() -> dict:
    """Retorna o saldo total (INCOME - EXPENSES) em todo histórico, ignora TRANSFER."""
    sql = """
        SELECT COALESCE(SUM(CASE WHEN type = 1 THEN amount ELSE 0 END), 0) - 
               COALESCE(SUM(CASE WHEN type = 2 THEN amount ELSE 0 END), 0) as balance
        FROM transactions WHERE type != 3;
    """
    result = _execute_select(sql)
    if result is None:
        return {"status": "error", "message": "Não foi possível consultar o saldo no momento."}

    balance_val = result[0].get('balance', 0) if result else 0
    return {"total_balance": float(balance_val), "currency": "BRL"}


@tool("daily_balance", args_schema=DailyBalanceArgs)
def daily_balance(date_local: str) -> dict:
    """Retorna o saldo (INCOME - EXPENSES) do dia específico informado (YYYY-MM-DD) em America/Sao_Paulo.
       Ignora TRANSFER (type=3)"""
    sql = """
        SELECT COALESCE(SUM(CASE WHEN type = 1 THEN amount ELSE 0 END), 0) - 
               COALESCE(SUM(CASE WHEN type = 2 THEN amount ELSE 0 END), 0) as balance
        FROM transactions WHERE type != 3 AND (occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s;
    """
    result = _execute_select(sql, (date_local,))
    if result is None:
        return {"status": "error", "message": "Não foi possível consultar o saldo no momento."}

    balance_val = result[0].get('balance', 0) if result else 0
    return {"date": date_local, "daily_balance": float(balance_val), "currency": "BRL"}


class UpdateTransactionArgs(BaseModel):
    id: Optional[int] = Field(
        default=None,
        description="ID da transação a atualizar. Se ausente, será feita uma busca por (match_text + date_local)."
    )
    match_text: Optional[str] = Field(
        default=None,
        description="Texto para localizar transação quando id não for informado (busca em source_text/description)."
    )
    date_local: Optional[str] = Field(
        default=None,
        description="Data local (YYYY-MM-DD) em America/Sao_Paulo; usado em conjunto com match_text quando id ausente."
    )
    amount: Optional[float] = Field(default=None, description="Novo valor.")
    type_id: Optional[int] = Field(default=None, description="Novo type_id (1/2/3).")
    type_name: Optional[str] = Field(default=None, description="Novo type_name: INCOME | EXPENSES | TRANSFER.")
    category_id: Optional[int] = Field(default=None, description="Nova categoria (id).")
    category_name: Optional[str] = Field(default=None, description="Nova categoria (nome).")
    description: Optional[str] = Field(default=None, description="Nova descrição.")
    payment_method: Optional[str] = Field(default=None, description="Novo meio de pagamento.")
    occurred_at: Optional[str] = Field(default=None, description="Novo timestamp ISO 8601.")

@tool("update_transaction", args_schema=UpdateTransactionArgs)
def update_transaction(
    id: Optional[int] = None,
    match_text: Optional[str] = None,
    date_local: Optional[str] = None,
    amount: Optional[float] = None,
    type_id: Optional[int] = None,
    type_name: Optional[str] = None,
    category_id: Optional[int] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
    occurred_at: Optional[str] = None,
) -> dict:
    """
    Atualiza uma transação existente.
    Estratégias:
      - Se 'id' for informado: atualiza diretamente por ID.
      - Caso contrário: localiza a transação mais recente que combine (match_text em source_text/description)
        E (date_local em America/Sao_Paulo), então atualiza.
    Retorna: status, rows_affected, id, e o registro atualizado.
    """
    if not any([amount, type_id, type_name, category_id, category_name, description, payment_method, occurred_at]):
        return {"status": "error", "message": "Nada para atualizar: forneça pelo menos um campo (amount, type, category, description, payment_method, occurred_at)."}

    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Resolve target_id
        target_id = id
        if target_id is None:
            if not match_text or not date_local:
                return {"status": "error", "message": "Sem 'id': informe match_text E date_local para localizar o registro."}

            # Buscar o mais recente no dia local informado que combine o texto
            cur.execute(
                f"""
                SELECT t.id
                FROM transactions t
                WHERE (t.source_text ILIKE %s OR t.description ILIKE %s)
                  AND {_local_date_filter_sql("t.occurred_at")}
                ORDER BY t.occurred_at DESC
                LIMIT 1;
                """,
                (f"%{match_text}%", f"%{match_text}%", date_local)
            )
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": "Nenhuma transação encontrada para os filtros fornecidos."}
            target_id = row[0]

        # Resolver type_id / category_id a partir de nomes, se fornecidos
        resolved_type_id = _resolve_type_transaction(cur, type_id, type_name) if (type_id or type_name) else None
        resolved_category_id = category_id
        if category_name and not category_id:
            resolved_category_id = _resolve_type_category(cur, category_name)

        # Montar SET dinâmico
        sets = []
        params: List[object] = []
        if amount is not None:
            sets.append("amount = %s")
            params.append(amount)
        if resolved_type_id is not None:
            sets.append("type = %s")
            params.append(resolved_type_id)
        if resolved_category_id is not None:
            sets.append("category_id = %s")
            params.append(resolved_category_id)
        if description is not None:
            sets.append("description = %s")
            params.append(description)
        if payment_method is not None:
            sets.append("payment_method = %s")
            params.append(payment_method)
        if occurred_at is not None:
            sets.append("occurred_at = %s::timestamptz")
            params.append(occurred_at)

        if not sets:
            return {"status": "error", "message": "Nenhum campo válido para atualizar."}

        params.append(target_id)

        cur.execute(
            f"UPDATE transactions SET {', '.join(sets)} WHERE id = %s;",
            params
        )
        rows_affected = cur.rowcount
        conn.commit()

        # Retornar o registro atualizado
        cur.execute(
            """
            SELECT
              t.id, t.occurred_at, t.amount, tt.type AS type_name,
              c.name AS category_name, t.description, t.payment_method, t.source_text
            FROM transactions t
            JOIN transaction_types tt ON tt.id = t.type
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.id = %s;
            """,
            (target_id,)
        )
        r = cur.fetchone()
        updated = None
        if r:
            updated = {
                "id": r[0],
                "occurred_at": str(r[1]),
                "amount": float(r[2]),
                "type": r[3],
                "category": r[4],
                "description": r[5],
                "payment_method": r[6],
                "source_text": r[7],
            }

        return {
            "status": "ok",
            "rows_affected": rows_affected,
            "id": target_id,
            "updated": updated
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"status": "error", "message": "Não foi possível atualizar a transação no momento."}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


TOOLS = [add_transaction, query_transactions, total_balance, daily_balance, update_transaction]
