import psycopg2

from app.config import DATABASE_URL


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL não foi configurada nas variáveis de ambiente.")
    return psycopg2.connect(DATABASE_URL)