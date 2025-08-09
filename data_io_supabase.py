# data_io_supabase.py
# Interface de persistência no Supabase para a IA Financeira

import os
import pandas as pd
from datetime import date
from supabase import create_client, Client
import streamlit as st

# Credenciais do Supabase vindas do .streamlit/secrets.toml
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

# Cria cliente Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TABLE_NAME = "transactions"

def get_user_id() -> str:
    """Retorna o ID do usuário autenticado pelo st_authenticator."""
    if "user" not in st.session_state or not st.session_state["user"]:
        raise ValueError("Usuário não autenticado")
    return st.session_state["user"]["id"]

def load_transactions() -> pd.DataFrame:
    """Carrega todos os lançamentos do usuário logado."""
    user_id = get_user_id()
    resp = supabase.table(TABLE_NAME).select("*").eq("user_id", user_id).order("data").execute()
    if not resp.data:
        return pd.DataFrame(columns=["data", "tipo", "valor", "categoria", "descricao", "created_at"])
    df = pd.DataFrame(resp.data)
    df["data"] = pd.to_datetime(df["data"]).dt.date
    return df

def save_transaction(data: date, tipo: str, valor: float, categoria: str, descricao: str):
    """Salva um novo lançamento no Supabase."""
    user_id = get_user_id()
    payload = {
        "user_id": user_id,
        "data": str(data),
        "tipo": tipo,
        "valor": round(float(valor), 2),
        "categoria": categoria,
        "descricao": descricao,
    }
    resp = supabase.table(TABLE_NAME).insert(payload).execute()
    if resp.error:
        raise RuntimeError(f"Erro ao salvar: {resp.error}")

def delete_transaction(row_id: int):
    """Remove um lançamento específico."""
    user_id = get_user_id()
    supabase.table(TABLE_NAME).delete().eq("user_id", user_id).eq("id", row_id).execute()
