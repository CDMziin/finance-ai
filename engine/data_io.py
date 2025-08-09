"""
data_io_supabase.py
Camada de persistência usando Supabase (tabela: public.transactions)

Requisitos:
- st.secrets["SUPABASE_URL"] e st.secrets["SUPABASE_KEY"]
- RLS ativo e políticas conforme README/SQL que enviei

Convenções:
- Para saber o usuário logado, usamos `st.session_state["user_id"]` (uuid do Supabase).
  -> Defina isso quando autenticar (ex.: após sign_in, setar user.id na sessão).
"""

from __future__ import annotations
import math
import pandas as pd
import streamlit as st
from datetime import date, datetime
from typing import Iterable, Dict, Any, List, Optional
from supabase import create_client, Client


# ========================= Supabase Client =========================

@st.cache_resource(show_spinner=False)
def _get_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def _require_user_id() -> str:
    uid = st.session_state.get("user_id")
    if not uid:
        # Se preferir, só retorne "" e trate no app
        raise RuntimeError("Sem user_id na sessão. Faça login primeiro.")
    return uid


# ========================= Helpers =========================

def _to_date(v) -> date:
    if isinstance(v, date):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        # Aceita "YYYY-MM-DD" ou "DD/MM/YYYY"
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            try:
                return datetime.strptime(v, "%d/%m/%Y").date()
            except ValueError:
                pass
    # fallback: hoje
    return date.today()


def _normalize_rows(rows: Iterable[Dict[str, Any]], user_id: str) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        out.append({
            "user_id":   user_id,
            "data":      _to_date(r.get("data")),
            "tipo":      str(r.get("tipo")),
            "valor":     float(r.get("valor", 0) or 0),
            "categoria": r.get("categoria") or None,
            "descricao": r.get("descricao") or "",
        })
    return out


def _chunked(iterable: List[Dict[str, Any]], size: int = 500):
    for i in range(0, len(iterable), size):
        yield iterable[i:i+size]


# ========================= CRUD de transações =========================

def load(start: Optional[date] = None, end: Optional[date] = None) -> pd.DataFrame:
    """
    Lê as transações do usuário logado (RLS garante isolamento).
    Filtros opcionais por data.
    Retorna um DataFrame com colunas: data(timestamptz/date), tipo, valor, categoria, descricao, id, created_at
    """
    supabase = _get_client()
    uid = _require_user_id()

    q = supabase.table("transactions").select("*").eq("user_id", uid)
    if start:
        q = q.gte("data", start.isoformat())
    if end:
        q = q.lte("data", end.isoformat())
    q = q.order("data", desc=False)

    res = q.execute()
    data = res.data or []

    df = pd.DataFrame(data)
    if not df.empty:
        # padroniza dtypes
        df["data"] = pd.to_datetime(df["data"], errors="coerce")
        if "valor" in df.columns:
            df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    else:
        df = pd.DataFrame(columns=["data","tipo","valor","categoria","descricao","id","created_at","user_id"])

    return df


def append_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Insere UM lançamento para o usuário corrente.
    row esperado: {data, tipo, valor, categoria, descricao}
    Retorna o registro criado (com id).
    """
    supabase = _get_client()
    uid = _require_user_id()
    payload = _normalize_rows([row], uid)[0]
    res = supabase.table("transactions").insert(payload).select("*").execute()
    if not res.data:
        raise RuntimeError("Falha ao inserir transação.")
    return res.data[0]


def append_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Insere VÁRIOS lançamentos de uma vez (chunked).
    Retorna lista com os registros criados.
    """
    supabase = _get_client()
    uid = _require_user_id()
    payload = _normalize_rows(list(rows), uid)
    created: List[Dict[str, Any]] = []
    for chunk in _chunked(payload, 500):
        res = supabase.table("transactions").insert(chunk).select("*").execute()
        created.extend(res.data or [])
    return created


def delete_last() -> bool:
    """
    Remove o último lançamento do usuário (order by created_at desc).
    Retorna True se deletou algo.
    """
    supabase = _get_client()
    uid = _require_user_id()

    # pega o último id
    sel = supabase.table("transactions") \
        .select("id") \
        .eq("user_id", uid) \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()

    rows = sel.data or []
    if not rows:
        return False

    last_id = rows[0]["id"]
    supabase.table("transactions").delete().eq("id", last_id).execute()
    return True


# --------------- Compat layer (APIs antigas) -----------------
# Se quiser manter seu app atual com .load() e .save(df),
# a função abaixo "substitui tudo do usuário" (não recomendado em produção),
# mas útil para migração/compatibilidade.

def save(df: pd.DataFrame):
    """
    **CUIDADO**: apaga todos os lançamentos do usuário e insere o conteúdo do df.
    Use apenas para compatibilidade temporária.
    Espera colunas: data, tipo, valor, categoria, descricao
    """
    supabase = _get_client()
    uid = _require_user_id()

    # Apaga tudo do usuário
    supabase.table("transactions").delete().eq("user_id", uid).execute()

    if df is None or df.empty:
        return

    rows = df.to_dict(orient="records")
    payload = _normalize_rows(rows, uid)
    for chunk in _chunked(payload, 500):
        supabase.table("transactions").insert(chunk).execute()
