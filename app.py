import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import re

# ====== SUPABASE ======
from supabase import create_client, Client  # pip install supabase
import os

# ====== MÓDULOS LOCAIS ======
import engine.data_io as data_io
import engine.parse as parse

# ---------------------------------------------
# CONFIG BÁSICA
# ---------------------------------------------
st.set_page_config(page_title="Finance AI — Dashboard + Chat", layout="wide")

PALETTE_DARK = ["#60A5FA", "#F87171", "#34D399", "#22D3EE", "#FBBF24", "#C4B5FD"]
px.defaults.template = "plotly_dark"
px.defaults.color_discrete_sequence = PALETTE_DARK
px.defaults.width = None
px.defaults.height = 320

# ---------------------------------------------
# SUPABASE HELPERS
# ---------------------------------------------
def get_supabase() -> Client:
    url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
    key = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", ""))
    if not url or not key:
        raise RuntimeError("SUPABASE_URL/SUPABASE_KEY não configurados em st.secrets.")
    return create_client(url, key)

def supabase_redirect_url_default() -> str:
    return st.secrets.get("SUPABASE_URL_REDIRECT", "http://localhost:8501/reset")

# ---------------------------------------------
# AUTENTICAÇÃO - UI
# ---------------------------------------------
def auth_login_panel():
    st.title("🔐 Acessar sua conta")
    email = st.text_input("E-mail")
    password = st.text_input("Senha", type="password")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Entrar", use_container_width=True):
            try:
                sb = get_supabase()
                sb.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state["auth_ok"] = True
                st.rerun()
            except Exception:
                st.error("Login inválido. Verifique e tente novamente.")
    with c2:
        st.markdown("&nbsp;")
        if st.button("Esqueci minha senha", use_container_width=True):
            st.session_state["auth_view"] = "forgot"
            st.rerun()

def auth_forgot_panel():
    st.title("🔑 Esqueci minha senha")
    email = st.text_input("Digite seu e-mail")
    if st.button("Enviar link de redefinição"):
        try:
            sb = get_supabase()
            sb.auth.reset_password_email(email, options={"redirect_to": supabase_redirect_url_default()})
            st.success("Se o e-mail existir, você receberá o link para redefinição.")
        except Exception as e:
            st.error(f"Erro ao enviar o e-mail: {e}")
    if st.button("Voltar ao login"):
        st.session_state["auth_view"] = "login"
        st.rerun()

def auth_reset_panel():
    st.title("🔄 Redefinir senha")
    qp = st.query_params
    access_token = qp.get("access_token", [None])
    refresh_token = qp.get("refresh_token", [None])
    access_token = access_token[0] if isinstance(access_token, list) else access_token
    refresh_token = refresh_token[0] if isinstance(refresh_token, list) else refresh_token

    if not access_token or not refresh_token:
        st.error("Link inválido ou expirado. Peça um novo e-mail de redefinição.")
        if st.button("Voltar ao login"):
            st.session_state["auth_view"] = "login"
            st.rerun()
        return

    new_pass = st.text_input("Nova senha", type="password")
    if st.button("Atualizar senha"):
        try:
            sb = get_supabase()
            sb.auth.set_session(access_token=access_token, refresh_token=refresh_token)
            sb.auth.update_user({"password": new_pass})
            st.success("Senha alterada com sucesso! Faça login novamente.")
            st.query_params.clear()
        except Exception as e:
            st.error(f"Erro ao atualizar senha: {e}")
    if st.button("Voltar ao login"):
        st.session_state["auth_view"] = "login"
        st.rerun()

def auth_guard() -> bool:
    if "auth_ok" not in st.session_state: st.session_state["auth_ok"] = False
    if "auth_view" not in st.session_state: st.session_state["auth_view"] = "login"
    if st.session_state["auth_ok"]:
        return True
    view = st.session_state["auth_view"]
    if view == "login":
        auth_login_panel()
    elif view == "forgot":
        auth_forgot_panel()
    elif view == "reset":
        auth_reset_panel()
    else:
        st.session_state["auth_view"] = "login"
        auth_login_panel()
    return False

def render_topbar_user_menu():
    with st.sidebar:
        st.markdown("### 👤 Conta")
        if st.button("Sair"):
            try:
                sb = get_supabase()
                sb.auth.sign_out()
            except Exception:
                pass
            st.session_state["auth_ok"] = False
            st.session_state["auth_view"] = "login"
            st.experimental_set_query_params()
            st.rerun()

# ---------------------------------------------
# ESTADO DO APP (após login)
# ---------------------------------------------
if "ref_date" not in st.session_state: st.session_state.ref_date = date.today()
if "period" not in st.session_state: st.session_state.period = "Mês"
if "pending_tx" not in st.session_state: st.session_state.pending_tx = None
if "chat_log" not in st.session_state: st.session_state.chat_log = []

# ---------------------------------------------
# HELPERS DO FINANCE APP
# ---------------------------------------------
def period_bounds(ref: date, kind: str):
    if kind == "Dia":
        start = ref; end = ref
    elif kind == "Semana":
        start = ref - timedelta(days=ref.weekday()); end = start + timedelta(days=6)
    else:
        start = ref.replace(day=1); end = (start + relativedelta(months=1)) - timedelta(days=1)
    return start, end

def prev_period(ref: date, kind: str):
    if kind == "Dia": return ref - timedelta(days=1)
    if kind == "Semana": return ref - timedelta(weeks=1)
    return (ref.replace(day=1) - relativedelta(days=1)).replace(day=1)

def next_period(ref: date, kind: str):
    if kind == "Dia": return ref + timedelta(days=1)
    if kind == "Semana": return ref + timedelta(weeks=1)
    return (ref.replace(day=1) + relativedelta(months=1))

def fmt_brl(v: float) -> str:
    return (f"R$ {v:,.2f}").replace(",","X").replace(".",",").replace("X",".")

def _ctx_reply(df: pd.DataFrame, saved_row: dict) -> str:
    dfx = df.copy()
    dfx["data"] = pd.to_datetime(dfx["data"], errors="coerce")
    dfx = dfx.dropna(subset=["data"])
    dt = pd.to_datetime(saved_row["data"]).date()
    curm = dfx[(dfx["data"].dt.month==dt.month) & (dfx["data"].dt.year==dt.year)]
    gastos = curm.loc[curm["tipo"]=="gasto","valor"].sum()
    ganhos = curm.loc[curm["tipo"]=="ganho","valor"].sum()
    saldo = ganhos - gastos
    if str(saved_row.get("tipo"))=="gasto":
        return f"Anotado ✅. Esse **gasto** impacta seu saldo do mês para **{fmt_brl(saldo)}**."
    if str(saved_row.get("tipo"))=="ganho":
        return f"Boa! **Receita** registrada. Seu saldo do mês agora é **{fmt_brl(saldo)}**."
    return f"Investimento salvo. Siga aportando! Saldo do mês: **{fmt_brl(saldo)}**."

def _undo_last():
    df = data_io.load()
    if df.empty:
        st.session_state.chat_log.append(("assistant","Não há lançamentos para desfazer.")); return
    data_io.save(df.iloc[:-1])
    st.session_state.chat_log.append(("assistant","Último lançamento removido ✅"))

def _handle_special_commands(msg: str) -> bool:
    t = msg.lower().strip()
    if re.search(r"\bresumo da semana\b", t):
        st.session_state.period="Semana"; st.session_state.ref_date=date.today()
        st.session_state.chat_log.append(("assistant","Resumo da semana aplicado no dashboard.")); return True
    if re.search(r"\bresumo do mês\b|\bresumo deste mês\b", t):
        st.session_state.period="Mês"; st.session_state.ref_date=date.today()
        st.session_state.chat_log.append(("assistant","Resumo do mês aplicado no dashboard.")); return True
    if re.search(r"\bsaldo de hoje\b|\bresumo de hoje\b", t):
        st.session_state.period="Dia"; st.session_state.ref_date=date.today()
        st.session_state.chat_log.append(("assistant","Mostrando saldo de hoje no dashboard.")); return True
    if re.search(r"\bdesfazer último\b|\bdesfazer ultima\b|\bdesfazer última\b", t):
        _undo_last(); return True
    return False

# ---------------------------------------------
# GATE DE AUTENTICAÇÃO
# ---------------------------------------------
if not auth_guard():
    st.stop()

render_topbar_user_menu()

# ---------------------------------------------
# APP — SEU DASHBOARD
# ---------------------------------------------
DF = data_io.load().copy()
DF["data"] = pd.to_datetime(DF["data"], errors="coerce")
DF = DF.dropna(subset=["data"]).sort_values("data")

st.markdown("## 🧮 Finance AI — Dashboard + Chat")
st.caption("Registre por texto e visualize tudo em tempo real.")

left, right = st.columns([1,3])
with left:
    colp, colr = st.columns([1,1])
    with colp:
        st.session_state.period = st.selectbox("Período", ["Dia","Semana","Mês"],
                                               index=["Dia","Semana","Mês"].index(st.session_state.period))
    with colr:
        _ref = st.date_input("Referência", value=st.session_state.ref_date, format="YYYY/MM/DD")
        if _ref != st.session_state.ref_date:
            st.session_state.ref_date = _ref; st.rerun()

    q1,q2,q3,q4,q5 = st.columns(5)
    with q1:
        if st.button("Hoje"): st.session_state.period="Dia"; st.session_state.ref_date=date.today(); st.rerun()
    with q2:
        if st.button("Esta semana"): st.session_state.period="Semana"; st.session_state.ref_date=date.today(); st.rerun()
    with q3:
        if st.button("Este mês"): st.session_state.period="Mês"; st.session_state.ref_date=date.today(); st.rerun()
    with q4:
        if st.button("Mês passado"):
            st.session_state.period="Mês"; ref=date.today().replace(day=1)-relativedelta(days=1)
            st.session_state.ref_date=ref; st.rerun()
    with q5:
        if st.button("Próximo mês"):
            st.session_state.period="Mês"; ref=date.today().replace(day=1)+relativedelta(months=1)
            st.session_state.ref_date=ref; st.rerun()

    nav1, nav2 = st.columns(2)
    with nav1:
        if st.button("◀ Anterior"):
            st.session_state.ref_date = prev_period(st.session_state.ref_date, st.session_state.period); st.rerun()
    with nav2:
        if st.button("Próximo ▶"):
            st.session_state.ref_date = next_period(st.session_state.ref_date, st.session_state.period); st.rerun()

with right:
    st.subheader("💬 Chat de lançamentos")

    if len(st.session_state.chat_log)==0:
        st.session_state.chat_log.append(("assistant",
            "Oi! Me diga algo como: 'gastei 32,50 no mercado ontem' ou 'recebi 1500 de salário'."))

    for role, text in st.session_state.chat_log[-12:]:
        st.chat_message(role).write(text)

    with st.expander("Exemplos úteis", expanded=False):
        st.markdown("- **gastei 37,90 no supermercado ontem**")
        st.markdown("- **recebi 1500 de salário 05/08**")
        st.markdown("- **investi 200 em CDB hoje**")
        st.markdown("- **resumo da semana** / **resumo do mês** / **saldo de hoje**")
        st.markdown("- **desfazer último** (remove a última transação salva)")

    with st.form("chat_form", clear_on_submit=True):
        user_msg = st.text_input("Mensagem", placeholder="Digite aqui...", key="chat_input")
        submitted = st.form_submit_button("Enviar")

    if st.session_state.pending_tx:
        p = st.session_state.pending_tx
        with st.container(border=True):
            st.markdown(
                f"**Confirmar lançamento?**\n\n"
                f"Tipo: `{p['tipo']}` | Valor: **{fmt_brl(p['valor'])}** | "
                f"Data: `{p['data']}` | Categoria: `{p['categoria']}`\n\n"
                f"Descrição: _{p['descricao']}_"
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ Confirmar"):
                    df_atual = data_io.load().copy()
                    df2 = pd.concat([df_atual, pd.DataFrame([p])], ignore_index=True)
                    data_io.save(df2)

                    _saved_date = pd.to_datetime(p["data"]).date()
                    st.session_state.ref_date = _saved_date
                    if st.session_state.period not in ("Dia","Semana","Mês"):
                        st.session_state.period = "Mês"

                    DF_now = data_io.load().copy()
                    DF_now["data"] = pd.to_datetime(DF_now["data"], errors="coerce")
                    DF_now = DF_now.dropna(subset=["data"]).sort_values("data")

                    st.session_state.chat_log.append(("assistant", _ctx_reply(DF_now, p)))
                    st.session_state.pending_tx = None
                    st.rerun()
            with c2:
                if st.button("❌ Cancelar"):
                    st.session_state.chat_log.append(("assistant","Ok, não salvei esse lançamento."))
                    st.session_state.pending_tx = None
                    st.rerun()

    if submitted and user_msg:
        st.session_state.chat_log.append(("user", user_msg))
        if not _handle_special_commands(user_msg):
            P = parse.parse_message(user_msg)
            if P.value is None:
                st.session_state.chat_log.append(("assistant", "❌ Não encontrei o valor. Ex: 'gastei **32,50** no mercado'."))
            else:
                st.session_state.pending_tx = {
                    "data": P.data,
                    "tipo": P.tipo,
                    "valor": P.value,
                    "categoria": P.categoria,
                    "descricao": P.descricao,
                }
                st.session_state.chat_log.append(("assistant","Vou registrar isso. Confirma abaixo?"))
        st.rerun()

# ===== KPIs =====
start, end = period_bounds(st.session_state.ref_date, st.session_state.period)
DF_now = data_io.load().copy()
DF_now["data"] = pd.to_datetime(DF_now["data"], errors="coerce")
DF_now = DF_now.dropna(subset=["data"]).sort_values("data")

cur = DF_now[DF_now["data"].between(pd.Timestamp(start), pd.Timestamp(end))]
prev_ref = prev_period(st.session_state.ref_date, st.session_state.period)
ps, pe = period_bounds(prev_ref, st.session_state.period)
prev = DF_now[DF_now["data"].between(pd.Timestamp(ps), pd.Timestamp(pe))]

def kpi_box(label, value, delta, good=True):
    col = "#22C55E" if (good and delta>=0) or (not good and delta<0) else "#EF4444"
    st.markdown(
        f"<div style='border-radius:14px;padding:14px 16px;background:rgba(255,255,255,0.04)'>"
        f"<div style='font-size:13px;opacity:.8'>{label}</div>"
        f"<div style='font-size:24px;font-weight:600;margin-top:2px'>{fmt_brl(value)}</div>"
        f"<div style='font-size:12px;margin-top:4px;color:{col}'>Δ {fmt_brl(delta)}</div>"
        f"</div>", unsafe_allow_html=True
    )

r_cur = cur.loc[cur["tipo"]=="ganho","valor"].sum()
g_cur = cur.loc[cur["tipo"]=="gasto","valor"].sum()
s_cur = r_cur - g_cur
r_prev = prev.loc[prev["tipo"]=="ganho","valor"].sum()
g_prev = prev.loc[prev["tipo"]=="gasto","valor"].sum()
s_prev = r_prev - g_prev

c1,c2,c3 = st.columns(3)
with c1: kpi_box("Receitas", r_cur, r_cur-r_prev, good=True)
with c2: kpi_box("Despesas", g_cur, g_cur-g_prev, good=False)
with c3: kpi_box("Saldo", s_cur, s_cur-s_prev, good=True)

st.caption(f"Período: {start.strftime('%d/%m/%Y')}–{end.strftime('%d/%m/%Y')}")

# ===== gráficos =====
def _brl0(v: float) -> str:
    return (f"R$ {v:,.0f}").replace(",","X").replace(".",",").replace("X",".")

def _top_n_with_outros(df: pd.DataFrame, n: int = 6) -> pd.DataFrame:
    df = df.sort_values("valor", ascending=False).reset_index(drop=True)
    if len(df) <= n: return df
    outros = pd.DataFrame([{"categoria":"Outros","valor":df["valor"].iloc[n:].sum()}])
    return pd.concat([df.iloc[:n], outros], ignore_index=True)

if not cur.empty:
    c1, c2 = st.columns(2)

    with c1:
        gastos_cat = cur[cur["tipo"]=="gasto"].groupby("categoria")["valor"].sum().reset_index()
        if not gastos_cat.empty:
            gastos_cat = _top_n_with_outros(gastos_cat, 6)
            fig = px.pie(gastos_cat, names="categoria", values="valor", title="Despesas por Categoria")
            fig.update_traces(textposition="inside", textinfo="percent+label", textfont_size=16)
            fig.update_layout(height=500, width=500, title_font_size=20, legend_font_size=14)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem despesas no período selecionado.")

    with c2:
        receitas_cat = cur[cur["tipo"]=="ganho"].groupby("categoria")["valor"].sum().reset_index()
        if not receitas_cat.empty:
            receitas_cat = _top_n_with_outros(receitas_cat, 6)
            fig = px.pie(receitas_cat, names="categoria", values="valor", title="Receitas por Categoria")
            fig.update_traces(textposition="inside", textinfo="percent+label", textfont_size=16)
            fig.update_layout(height=500, width=500, title_font_size=20, legend_font_size=14)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem receitas no período selecionado.")

    d = cur[cur["tipo"].isin(["ganho","gasto"])].copy()
    d["sinal"] = d["tipo"].map({"ganho":1,"gasto":-1})
    dd = d.groupby("data", as_index=False).apply(lambda x: pd.Series({"saldo":(x["valor"]*x["sinal"]).sum()}))
    max_abs = float(dd["saldo"].abs().max()) if not dd.empty else 0.0
    use_mil = max_abs >= 10000
    if use_mil:
        dd["y"] = dd["saldo"]/1000.0; dd["label"] = dd["y"].map(lambda v: (f"{v:,.1f}").replace(",","X").replace(".",",").replace("X","."))
        ytitle = "Saldo (R$ mil)"
    else:
        dd["y"] = dd["saldo"]; dd["label"] = dd["y"].map(_brl0); ytitle = "Saldo (R$)"
    fig_saldo = px.bar(dd, x="data", y="y", text="label", title="Saldo Diário", color="y",
                       color_continuous_scale=["#F87171","#34D399"])
    fig_saldo.update_traces(textposition="outside", cliponaxis=False,
                            hovertemplate="Saldo: R$ %{customdata:,.2f}<extra></extra>",
                            customdata=dd["saldo"])
    ymin, ymax = float(dd["y"].min()), float(dd["y"].max())
    pad = max((ymax-ymin)*0.15, 0.1)
    fig_saldo.update_yaxes(range=[ymin-pad, ymax+pad])
    fig_saldo.update_coloraxes(cmid=0, showscale=False)
    if use_mil: fig_saldo.update_yaxes(ticksuffix=" mil", tickformat=",.1f")
    else:       fig_saldo.update_yaxes(tickprefix="R$ ", tickformat=",.0f")
    fig_saldo.update_layout(xaxis_title="", yaxis_title=ytitle)
    st.plotly_chart(fig_saldo, use_container_width=True)

    dd2 = dd.sort_values("data").copy()
    dd2["saldo_acumulado"] = dd2["y"].cumsum()
    fig_acum = px.line(dd2, x="data", y="saldo_acumulado", title="Saldo acumulado no período")
    fig_acum.update_traces(mode="lines+markers", hovertemplate="Acumulado: %{y}<extra></extra>")
    if use_mil: fig_acum.update_yaxes(ticksuffix=" mil", tickformat=",.1f")
    else:       fig_acum.update_yaxes(tickprefix="R$ ", tickformat=",.0f")
    st.plotly_chart(fig_acum, use_container_width=True)

    st.subheader("📜 Lançamentos no período")
    cur_view = cur.sort_values(["data","tipo","categoria"]).copy()
    cur_view["Data"] = cur_view["data"].dt.strftime("%d/%m/%Y")
    cur_view["Valor"] = cur_view["valor"].map(fmt_brl)
    cur_view = cur_view.rename(columns={"tipo":"Tipo","categoria":"Categoria","descricao":"Descrição"})[
        ["Data","Tipo","Categoria","Descrição","Valor"]
    ]
    st.dataframe(cur_view, use_container_width=True, hide_index=True)
else:
    st.info("Sem lançamentos no período selecionado.")
