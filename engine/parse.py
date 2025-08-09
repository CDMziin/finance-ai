# parse.py — NLP simples em PT-BR para IA Financeira
# Extrai tipo (gasto/ganho/investimento), valor, data, categoria e descrição
# Ex.: "gastei 37,90 no mercado ontem", "recebi 1500 de salário 05/08", "investi 200 em cdb hoje"

from __future__ import annotations
from datetime import date, timedelta
from dataclasses import dataclass
from typing import Optional
import re

@dataclass
class Parsed:
    data: date
    tipo: Optional[str]
    value: Optional[float]
    categoria: Optional[str]
    descricao: str

# ===== categorias =====
CATEGORIAS_GASTOS = {
    "mercado": "Mercado", "supermercado": "Mercado", "feira": "Mercado",
    "restaurante": "Alimentação Fora", "lanche": "Alimentação Fora", "pizza": "Alimentação Fora",
    "ifood": "Alimentação Fora", "ubereats": "Alimentação Fora",
    "aluguel": "Moradia", "condominio": "Moradia", "condomínio": "Moradia",
    "luz": "Contas", "energia": "Contas", "água": "Contas", "agua": "Contas", "gás": "Contas", "gas": "Contas",
    "internet": "Contas", "telefone": "Contas", "celular": "Contas",
    "transporte": "Transporte", "uber": "Transporte", "99": "Transporte",
    "taxi": "Transporte", "táxi": "Transporte", "gasolina": "Transporte",
    "combustivel": "Transporte", "combustível": "Transporte", "estacionamento": "Transporte",
    "farmacia": "Saúde", "farmácia": "Saúde", "dentista": "Saúde",
    "curso": "Educação", "faculdade": "Educação", "escola": "Educação", "livro": "Educação",
    "cinema": "Lazer", "show": "Lazer", "viagem": "Viagens", "hotel": "Viagens", "passagem": "Viagens",
    "mercado livre": "Casa", "magalu": "Casa", "amazon": "Casa", "mobiliario": "Casa", "mobiliário": "Casa",
    "roupa": "Pessoais", "roupas": "Pessoais", "sapato": "Pessoais", "barbearia": "Pessoais",
    "imposto": "Impostos", "taxa": "Taxas", "banco": "Taxas", "tarifa": "Taxas",
}
CATEGORIAS_GANHOS = {
    "salario": "Salário", "salário": "Salário", "13º": "Salário",
    "ferias": "Salário", "férias": "Salário",
    "freela": "Freelance", "freelancer": "Freelance", "bico": "Freelance",
    "bonus": "Bônus", "bônus": "Bônus", "comissão": "Comissões", "comissao": "Comissões",
    "aluguel": "Aluguel", "aluguel recebido": "Aluguel",
    "venda": "Venda de Itens", "vendi": "Venda de Itens",
    "juros": "Rendimentos", "rendimentos": "Rendimentos", "dividendos": "Rendimentos",
    "presente": "Presentes/Doações", "doação": "Presentes/Doações", "doacao": "Presentes/Doações",
    "prêmio": "Prêmios", "premio": "Prêmios",
}
CATEGORIAS_INVEST = {
    "cdb": "CDB", "tesouro": "Tesouro", "poupanca": "Poupança", "poupança": "Poupança",
    "fundo": "Fundos", "fii": "Fundos Imobiliários", "acoes": "Ações", "ações": "Ações", "acao": "Ações",
    "pix": "Reserva/Pix", "cripto": "Cripto", "bitcoin": "Cripto",
}

# ===== utilitários =====
DECIMAL_RE = re.compile(r"(?<!\d)(?:r\$\s*)?([\d\.]+\,\d{1,2}|\d+)(?!\d)", re.IGNORECASE)
DATE_SLASH_RE = re.compile(r"\b(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?\b")
DAY_ONLY_RE = re.compile(r"\bdia\s+(\d{1,2})\b", re.IGNORECASE)
MESES = {"jan":1,"janeiro":1,"fev":2,"fevereiro":2,"mar":3,"março":3,"marco":3,"abr":4,"abril":4,
         "mai":5,"maio":5,"jun":6,"junho":6,"jul":7,"julho":7,"ago":8,"agosto":8,"set":9,"setembro":9,
         "out":10,"outubro":10,"nov":11,"novembro":11,"dez":12,"dezembro":12}
MESES_RE = re.compile(r"\b(\d{1,2})\s+de\s+([a-zçãéô]+)(?:\s+de\s+(\d{4}))?\b", re.IGNORECASE)

VERBOS_GASTO = ["gastei","paguei","pagar","comprei","comprar","saquei","retirei","retiro"]
VERBOS_GANHO = ["recebi","ganhei","entrou","caiu","depositaram","pague","pagaram"]
VERBOS_INVEST = ["investi","apliquei","aportei","aportar","comprar ações","comprei ações","apliquei em"]

def _parse_valor(t: str) -> float | None:
    t2 = t.lower().replace("r$", " ")
    # 5k / 5 mil
    m = re.search(r"\b(\d+(?:[\.,]\d+)?)\s*k\b", t2)
    if m:
        return float(m.group(1).replace('.', '').replace(',', '.')) * 1000
    m = re.search(r"\b(\d+(?:[\.,]\d+)?)\s*mil\b", t2)
    if m:
        return float(m.group(1).replace('.', '').replace(',', '.')) * 1000
    m = DECIMAL_RE.search(t2)
    if not m:
        return None
    raw = m.group(1)
    raw2 = raw.replace('.', '').replace(',', '.') if "," in raw else raw
    try: return float(raw2)
    except: return None

def _parse_data(texto: str, hoje: date | None = None) -> date:
    hoje = hoje or date.today()
    t = texto.lower()
    if "hoje" in t: return hoje
    if "ontem" in t: return hoje - timedelta(days=1)
    if "anteontem" in t: return hoje - timedelta(days=2)
    if "amanhã" in t or "amanha" in t: return hoje + timedelta(days=1)
    m = DATE_SLASH_RE.search(t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        y = hoje.year if y is None else (int(y) + 2000 if int(y) < 100 else int(y))
        return date(y, mo, d)
    m = DAY_ONLY_RE.search(t)
    if m: return date(hoje.year, hoje.month, int(m.group(1)))
    m = MESES_RE.search(t)
    if m:
        d = int(m.group(1)); mes = MESES.get(m.group(2).lower())
        if mes: return date(int(m.group(3) or hoje.year), mes, d)
    return hoje

def _detect_tipo(t: str) -> str:
    tl = t.lower()
    if any(w in tl for w in VERBOS_GASTO): return "gasto"
    if any(w in tl for w in VERBOS_GANHO): return "ganho"
    if any(w in tl for w in VERBOS_INVEST): return "investimento"
    if re.search(r"\-\s?\d", tl): return "gasto"
    return "ganho"

def _detect_categoria(t: str, tipo: str | None) -> str:
    tl = t.lower()
    table = (CATEGORIAS_GASTOS if tipo=="gasto" else
             CATEGORIAS_GANHOS if tipo=="ganho" else
             CATEGORIAS_INVEST if tipo=="investimento" else {})
    for k, v in table.items():
        if k in tl: return v
    for k, v in {**CATEGORIAS_GASTOS, **CATEGORIAS_GANHOS, **CATEGORIAS_INVEST}.items():
        if k in tl: return v
    return "outros"

def parse_message(texto: str) -> Parsed:
    tipo = _detect_tipo(texto)
    valor = _parse_valor(texto)
    data  = _parse_data(texto)
    cat   = _detect_categoria(texto, tipo)
    desc  = texto.strip()
    return Parsed(data=data, tipo=tipo, value=valor, categoria=cat, descricao=desc)
