# data_io_supabase.py
from __future__ import annotations
import streamlit as st
import pandas as pd
from datetime import date
from supabase import create_client

TABLE = "transactions"

# --- cliente supabase (lido de st.secrets) ---
@st.cache_resource(show_spinner=False)
def _sb():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def _uid() -> str | None:
    # o app coloca user_id na sessão após login
    return st.session_state.get("user_id")

def _to_iso(d) -> str:
    if isinstance(d, (pd.Timestamp, )):
        d = d.date()
    if isinstance(d, date):
        return d.isoformat()
    return str(d)

# ------------------ API usada pelo app ------------------

def load(start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """Carrega lançamentos do usuário logado, opcionalmente filtrando por data."""
    uid = _uid()
    if not uid:
        return pd.DataFrame(columns=["data","tipo","valor","categoria","descricao","id","created_at"])

    sb = _sb()
    q = sb.table(TABLE).select("*").eq("user_id", uid)
    if start is not None:
        q = q.gte("data", _to_iso(start))
    if end is not None:
        q = q.lte("data", _to_iso(end))
    q = q.order("data", desc=False).order("created_at", desc=False)
    res = q.execute()
    rows = res.data or []
    if not rows:
        return pd.DataFrame(columns=["data","tipo","valor","categoria","descricao","id","created_at"])

    df = pd.DataFrame(rows)
    # normaliza tipos esperados pelo app
    if "valor" in df:
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    return df[["data","tipo","valor","categoria","descricao","id","created_at"]]

def append_row(row: dict) -> int | None:
    """Insere um lançamento para o usuário logado. Retorna o id inserido."""
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

    sb = _sb()
    res = sb.table(TABLE).insert(payload).select("id").single().execute()
    if res.data:
        return res.data.get("id")
    return None

def delete_last() -> bool:
    """Remove o último lançamento (mais recente por created_at) do usuário."""
    uid = _uid()
    if not uid:
        return False

    sb = _sb()
    # pega o último id
    sel = sb.table(TABLE).select("id").eq("user_id", uid).order("created_at", desc=True).limit(1).execute()
    rows = sel.data or []
    if not rows:
        return False

    last_id = rows[0]["id"]
    sb.table(TABLE).delete().eq("id", last_id).execute()
    return True
