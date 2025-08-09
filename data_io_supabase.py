# data_io_supabase.py
from __future__ import annotations
import streamlit as st
import pandas as pd
from datetime import date, datetime
from typing import Optional
from supabase import create_client

TABLE = "transactions"

# ---------------- Base / cliente ----------------

@st.cache_resource(show_spinner=False)
def _sb():
    """Cliente base do projeto (usa URL e anon KEY do secrets)."""
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def _client():
    """
    Cliente com o JWT do usuário aplicado no PostgREST.
    ESSENCIAL para RLS liberar SELECT/INSERT/DELETE do usuário logado.
    """
    sb = _sb()
    token = st.session_state.get("access_token")
    if token:
        try:
            sb.postgrest.auth(token)
        except Exception:
            # se falhar, segue sem token (vai dar permission denied nas queries)
            pass
    return sb

def _uid() -> Optional[str]:
    return st.session_state.get("user_id")

def _to_iso(v) -> str:
    """Converte date/datetime/str em 'YYYY-MM-DD' (o que a tabela espera)."""
    if isinstance(v, date) and not isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, str):
        # aceita 'YYYY-MM-DD' ou 'DD/MM/YYYY'
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            pass
        try:
            d = datetime.strptime(v, "%d/%m/%Y").date()
            return d.isoformat()
        except ValueError:
            pass
    # fallback: hoje
    return date.today().isoformat()

# ---------------- API usada pelo app ----------------

def load(start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """
    Carrega lançamentos do usuário logado.
    Retorna colunas: data, tipo, valor, categoria, descricao, id, created_at
    """
    uid = _uid()
    if not uid:
        return pd.DataFrame(columns=["data","tipo","valor","categoria","descricao","id","created_at"])

    sb = _client()  # <<< usa cliente com JWT
    q = sb.table(TABLE).select("*").eq("user_id", uid)
    if start is not None:
        q = q.gte("data", _to_iso(start))
    if end is not None:
        q = q.lte("data", _to_iso(end))
    q = q.order("data", desc=False).order("created_at", desc=False)

    try:
        res = q.execute()
    except Exception as e:
        # mostra o motivo real na UI pra depurar (permission denied, coluna, etc.)
        st.error(f"Supabase APIError em load(): {e}")
        return pd.DataFrame(columns=["data","tipo","valor","categoria","descricao","id","created_at"])

    rows = res.data or []
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["data","tipo","valor","categoria","descricao","id","created_at"])

    # normaliza tipos esperados
    if "data" in df.columns:
        df["data"] = pd.to_datetime(df["data"], errors="coerce")
    if "valor" in df.columns:
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    cols = ["data","tipo","valor","categoria","descricao","id","created_at"]
    return df[cols] if all(c in df.columns for c in cols) else df

def append_row(row: dict) -> int | None:
    """Insere um lançamento para o usuário logado. Retorna o id inserido."""
    uid = _uid()
    if not uid:
        raise RuntimeError("Sem usuário na sessão. Faça login primeiro.")

    payload = {
        "user_id": uid,
        "data": _to_iso(row.get("data")),
        "tipo": row.get("tipo"),
        "valor": float(row["valor"]) if row.get("valor") is not None else None,
        "categoria": row.get("categoria"),
        "descricao": row.get("descricao"),
    }

    sb = _client()  # <<< usa cliente com JWT
    try:
        res = sb.table(TABLE).insert(payload).select("id").single().execute()
    except Exception as e:
        st.error(f"Supabase APIError em append_row(): {e}")
        return None

    return res.data.get("id") if res.data else None

def delete_last() -> bool:
    """Remove o último lançamento (mais recente por created_at) do usuário."""
    uid = _uid()
    if not uid:
        return False

    sb = _client()  # <<< usa cliente com JWT
    try:
        sel = sb.table(TABLE).select("id").eq("user_id", uid).order("created_at", desc=True).limit(1).execute()
        rows = sel.data or []
        if not rows:
            return False
        last_id = rows[0]["id"]
        sb.table(TABLE).delete().eq("id", last_id).execute()
        return True
    except Exception as e:
        st.error(f"Supabase APIError em delete_last(): {e}")
        return False
