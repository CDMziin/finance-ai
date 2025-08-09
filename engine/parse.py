# parse.py — NLP simples em PT-BR para IA Financeira
# Extrai tipo (gasto/ganho/investimento), valor, data, categoria e descrição
# Ex.: "gastei 37,90 no mercado ontem", "recebi 1500 de salário 05/08", "investi 200 em cdb hoje"

from __future__ import annotations
from datetime import date, timedelta
import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class Parsed:
    data: date
    tipo: Optional[str]
    value: Optional[float]
    categoria: Optional[str]
    descricao: str

# ===================== CATEGORIAS =====================
CATEGORIAS_GASTOS = {
    # Alimentação
    "mercado": "Mercado", "supermercado": "Mercado", "feira": "Mercado",
    "restaurante": "Alimentação Fora", "lanche": "Alimentação Fora", "pizza": "Alimentação Fora",
    "ifood": "Alimentação Fora", "ubereats": "Alimentação Fora",
    # Moradia & Contas
    "aluguel": "Moradia", "condominio": "Moradia", "condomínio": "Moradia",
    "luz": "Contas", "energia": "Contas", "água": "Contas", "agua": "Contas",
    "gás": "Contas", "gas": "Contas", "internet": "Contas", "telefone": "Contas", "celular": "Contas",
    # Transporte
    "transporte": "Transporte", "uber": "Transporte", "99": "Transporte",
    "taxi": "Transporte", "táxi": "Transporte", "gasolina": "Transporte",
    "combustível": "Transporte", "combustivel": "Transporte", "estacionamento": "Transporte",
    # Saúde
    "farmácia": "Saúde", "farmacia": "Saúde", "plano de saúde": "Saúde", "dentista": "Saúde",
    # Educação
    "curso": "Educação", "faculdade": "Educação", "escola": "Educação", "livro": "Educação",
    # Lazer / Viagens
    "cinema": "Lazer", "show": "Lazer", "viagem": "Viagens", "hotel": "Viagens", "passagem": "Viagens",
    # Casa / Pessoais
    "mercado livre": "Casa", "magalu": "Casa", "amazon": "Casa",
    "mobiliário": "Casa", "mobiliario": "Casa",
    "roupa": "Pessoais", "roupas": "Pessoais", "sapato": "Pessoais", "barbearia": "Pessoais",
    # Outros
    "imposto": "Impostos", "taxa": "Taxas", "banco": "Taxas", "tarifa": "Taxas",
}

CATEGORIAS_GANHOS = {
    "salário": "Salário", "salario": "Salário", "13º": "Salário",
    "férias": "Salário", "ferias": "Salário",
    "freela": "Freelance", "freelancer": "Freelance", "bico": "Freelance",
    "bônus": "Bônus", "bonus": "Bônus", "comissão": "Comissões", "comissao": "Comissões",
    "aluguel recebido": "Aluguel", "aluguel": "Aluguel",
    "venda": "Venda de Itens", "vendi": "Venda de Itens",
    "juros": "Rendimentos", "rendimentos": "Rendimentos", "dividendos": "Rendimentos",
    "presente": "Presentes/Doações", "presente recebido": "Presentes/Doações",
    "doação": "Presentes/Doações", "doacao": "Presentes/Doações",
    "prêmio": "Prêmios", "premio": "Prêmios",
}

CATEGORIAS_INVEST = {
    "cdb": "CDB", "tesouro": "Tesouro", "poupança": "Poupança", "poupanca": "Poupança",
    "fundo": "Fundos", "fii": "Fundos Imobiliários",
    "ações": "Ações", "acoes": "Ações", "acao": "Ações",
    "pix": "Reserva/Pix", "cripto": "Cripto", "bitcoin": "Cripto",
}

# ===================== UTILITÁRIOS =====================
DECIMAL_RE = re.compile(r"(?<!\d)(?:r\$\s*)?([\d\.]+\,\d{1,2}|\d+)(?!\d)", re.IGNORECASE)
DATE_SLASH_RE = re.compile(r"\b(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?\b")
DAY_ONLY_RE = re.compile(r"\bdia\s+(\d{1,2})\b", re.IGNORECASE)

MESES = {
    "jan": 1, "janeiro": 1,
    "fev": 2, "fevereiro": 2,
    "mar": 3, "março": 3, "marco": 3,
    "abr": 4, "abril": 4,
    "mai": 5, "maio": 5,
    "jun": 6, "junho": 6,
    "jul": 7, "julho": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "setembro": 9,
    "out": 10, "outubro": 10,
    "nov": 11, "novembro": 11,
    "dez": 12, "dezembro": 12,
}
MESES_RE = re.compile(r"\b(\d{1,2})\s+de\s+([a-zçãéô]+)(?:\s+de\s+(\d{4}))?\b", re.IGNORECASE)

VERBOS_GASTO = ["gastei", "paguei", "pagar", "comprei", "comprar", "saquei", "retirei", "retiro"]
VERBOS_GANHO = ["recebi", "ganhei", "entrou", "caiu", "depositaram", "pague", "pagaram"]
VERBOS_INVEST = ["investi", "apliquei", "aportei", "aportar", "comprar ações", "comprei ações", "apliquei em"]

# ===================== PARSE DE VALOR =====================
def _parse_valor(texto: str) -> float | None:
    t = texto.lower().replace("r$", " ")
    m_k = re.search(r"\b(\d+(?:[\.,]\d+)?)\s*k\b", t)
    if m_k:
        num = m_k.group(1).replace('.', '').replace(',', '.')
        try: return float(num) * 1000
        except: pass
    m_mil = re.search(r"\b(\d+(?:[\.,]\d+)?)\s*mil\b", t)
    if m_mil:
        num = m_mil.group(1).replace('.', '').replace(',', '.')
        try: return float(num) * 1000
        except: pass

    m = DECIMAL_RE.search(t)
    if not m: return None
    raw = m.group(1)
    if "," in raw: raw2 = raw.replace('.', '').replace(',', '.')
    else: raw2 = raw
    try: return float(raw2)
    except ValueError: return None

# ===================== PARSE DE DATA =====================
def _parse_data(texto: str, hoje: date | None = None) -> date:
    hoje = hoje or date.today()
    t = texto.lower()

    if re.search(r"\bhoje\b", t): return hoje
    if re.search(r"\bontem\b", t): return hoje - timedelta(days=1)
    if re.search(r"\banteontem\b", t): return hoje - timedelta(days=2)
    if re.search(r"\bamanh[ãa]\b", t): return hoje + timedelta(days=1)

    m = DATE_SLASH_RE.search(t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if y is None: y = hoje.year
        else:
            y = int(y)
            if y < 100: y += 2000
        return date(y, mo, d)

    m = DAY_ONLY_RE.search(t)
    if m:
        d = int(m.group(1))
        return date(hoje.year, hoje.month, d)

    m = MESES_RE.search(t)
    if m:
        d = int(m.group(1)); nome = m.group(2).lower(); y = m.group(3)
        mo = MESES.get(nome)
        if mo:
            y = int(y) if y else hoje.year
            return date(y, mo, d)

    return hoje

# ===================== PARSE DE CATEGORIA =====================
def _detect_categoria(t: str, tipo: str | None) -> str:
    tl = t.lower()
    if tipo == "gasto":
        for k, v in CATEGORIAS_GASTOS.items():
            if k in tl: return v
    if tipo == "ganho":
        for k, v in CATEGORIAS_GANHOS.items():
            if k in tl: return v
    if tipo == "investimento":
        for k, v in CATEGORIAS_INVEST.items():
            if k in tl: return v
    for k, v in {**CATEGORIAS_GASTOS, **CATEGORIAS_GANHOS, **CATEGORIAS_INVEST}.items():
        if k in tl: return v
    return "outros"

# ===================== PARSE DE TIPO =====================
def _detect_tipo(t: str) -> str:
    tl = t.lower()
    if any(w in tl for w in VERBOS_GASTO): return "gasto"
    if any(w in tl for w in VERBOS_GANHO): return "ganho"
    if any(w in tl for w in VERBOS_INVEST): return "investimento"
    if re.search(r"\-\s?\d", tl): return "gasto"
    return "ganho"

# ===================== API =====================
def parse_message(texto: str) -> Parsed:
    tipo = _detect_tipo(texto)
    valor = _parse_valor(texto)
    data = _parse_data(texto)
    categoria = _detect_categoria(texto, tipo)
    desc = texto.strip()
    return Parsed(data=data, tipo=tipo, value=valor, categoria=categoria, descricao=desc)
