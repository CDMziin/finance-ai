from pathlib import Path
import pandas as pd
from .parse import Parsed

DATA = Path("data/transactions.csv")
DATA.parent.mkdir(exist_ok=True)
COLUMNS = ["data", "tipo", "valor", "categoria", "descricao"]


def _ensure(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.date
    df["tipo"] = df["tipo"].astype(str).str.lower()
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
    df["categoria"] = df["categoria"].astype(str).str.lower()
    return df


def _fresh_df() -> pd.DataFrame:
    df = pd.DataFrame(columns=COLUMNS)
    df.to_csv(DATA, index=False)
    return df


def load() -> pd.DataFrame:
    if DATA.exists():
        try:
            if DATA.stat().st_size == 0:
                # arquivo existe mas está vazio → recria com cabeçalho
                return _fresh_df()
            df = pd.read_csv(DATA)
        except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError):
            # arquivo corrompido/sem colunas → recria
            df = _fresh_df()
        return _ensure(df)
    else:
        return _fresh_df()


def save(df: pd.DataFrame) -> None:
    df.to_csv(DATA, index=False)


def append_row(df: pd.DataFrame, p: Parsed) -> pd.DataFrame:
    new_row = {
        "data": p.data,
        "tipo": p.tipo,
        "valor": p.value if p.value is not None else 0.0,
        "categoria": p.categoria,
        "descricao": p.descricao,
    }
    df2 = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save(df2)
    return df2