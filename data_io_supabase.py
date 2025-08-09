# data_io_supabase.py
"""
Camada de persistência usando Supabase (tabela: public.transactions)

Requisitos no Streamlit Cloud / local:
- st.secrets["SUPABASE_URL"]
- st.secrets["SUPABASE_KEY"]

Sessão esperada (definida no app após login):
- st.session_state["user_id"]        -> UUID do usuário no Supabase
- st.session_state["access_token"]   -> JWT do usuário autenticado (para RLS)

Funções usadas pelo app:
- load(start: date | None = None, end: date | None = None) -> pd.DataFrame
- append_row(row: dict) -> int | None
- delete_last() -> bool
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Dict, Any, List, Optional

import pandas as pd
import streamlit as st
from supabase import create_client

TABLE = "transactions"


# ------------------ Cliente Supabase ------------------

@st.cache_resource(show_spinner=False)
def _sb():
    """Client base (sem token de usuário aplicado)."""
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def _client():
    """
    Retorna o client com o token do usuário atual aplicado no PostgREST.
    Isso é essencial para as Row Level Security (RLS) funcionarem.
    """
    sb = _sb()
    token = st.session_state.get("access_token")
    if token:
        try:
            sb.postgrest.auth(token)
        except Exception:
            # Se falhar, seguimos sem token (mas RLS pode bloquear)
            pass
    return sb


# ------------------ Helpers ------------------

def _uid() -> str | None:
    """UUID do usuário logado (definido no app após autenticação)."""
    return st.session_state.get("user_id")


def _to_iso(d) -> Optional[str]:
    """Converte date/str para 'YYYY-MM-DD' (ou retorna None)."""
    if d is None:
        return None
    if isinstance(d, str):
        return d  # assume ISO válido; o app já manda nesse formato
    try:
        return pd.to_datetime(d).date().isoformat()
    except Exception:
        return None


# ------------------ API usada pelo app ------------------

def load(start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """
    Carrega os lançamentos do usuário logado, aplicando RLS via token.
    Filtros opcionais por data (feitos no servidor).
    Retorna colunas: data, tipo, valor, categoria, descricao, id, created_at
    """
    uid = _uid()
    if not uid:
        return pd.DataFrame(columns=["data", "tipo", "valor", "categoria", "descricao", "id", "created_at"])

    try:
        sb = _client()
        q = sb.table(TABLE).select("*").eq("user_id", uid)
        if start is not None:
            q = q.gte("data", _to_iso(start))
        if end is not None:
            q = q.lte("data", _to_iso(end))
        q = q.order("data", desc=False).order("created_at", desc=False)

        res = q.execute()
        rows = res.data or []
        if not rows:
            return pd.DataFrame(columns=["data", "tipo", "valor", "categoria", "descricao", "id", "created_at"])

        df = pd.DataFrame(rows)
        # normaliza dtypes
        df["data"] = pd.to_datetime(df["data"], errors="coerce")
        if "valor" in df:
            df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
        # garante colunas esperadas
        for col in ["categoria", "descricao", "id", "created_at"]:
            if col not in df.columns:
                df[col] = None
        return df[["data", "tipo", "valor", "categoria", "descricao", "id", "created_at"]]
    except Exception as e:
        st.error(f"Supabase APIError em load(): {e}")
        return pd.DataFrame(columns=["data", "tipo", "valor", "categoria", "descricao", "id", "created_at"])


def append_row(row: Dict[str, Any]) -> Optional[int]:
    """
    Insere UM lançamento para o usuário logado.
    `row` esperado: {data, tipo, valor, categoria, descricao}
    Retorna o `id` criado (se vier no retorno) ou None.
    """
    uid = _uid()
    if not uid:
        raise RuntimeError("Sem usuário na sessão.")

    payload = {
        "user_id": uid,
        "data": _to_iso(row.get("data")),
        "tipo": row.get("tipo"),
        "valor": float(row.get("valor")) if row.get("valor") is not None else None,
        "categoria": row.get("categoria"),
        "descricao": row.get("descricao"),
    }

    try:
        sb = _client()
        # No client síncrono, insert(...).select() não existe; apenas execute()
        res = sb.table(TABLE).insert(payload).execute()
        if res.data and len(res.data) > 0:
            return res.data[0].get("id")
        return None
    except Exception as e:
        st.error(f"Supabase APIError em append_row(): {e}")
        return None


def delete_last() -> bool:
    """
    Remove o último lançamento (mais recente por created_at) do usuário logado.
    Retorna True se algo foi deletado.
    """
    uid = _uid()
    if not uid:
        return False

    try:
        sb = _client()
        sel = (
            sb.table(TABLE)
            .select("id")
            .eq("user_id", uid)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = sel.data or []
        if not rows:
            return False

        last_id = rows[0]["id"]
        sb.table(TABLE).delete().eq("id", last_id).execute()
        return True
    except Exception as e:
        st.error(f"Supabase APIError em delete_last(): {e}")
        return False
