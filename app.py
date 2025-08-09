# app.py — Finance AI (Supabase + Streamlit)
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import re

# === PERSISTÊNCIA (Supabase) e NLP ===
import data_io_supabase as data_io   
from engine import parse

# -------------------------------------------------------------------
# CONFIG GERAL
# -------------------------------------------------------------------
st.set_page_config(page_title="Finance AI — Dashboard + Chat", layout="wide")

# Tema (escuro fixo)
PALETTE_DARK = ["#60A5FA", "#F87171", "#34D399", "#22D3EE", "#FBBF24", "#C4B5FD"]
px.defaults.template = "plotly_dark"
px.defaults.color_discrete_sequence = PALETTE_DARK
px.defaults.width = None
px.defaults.height = 320

# -------------------------------------------------------------------
# AUTENTICAÇÃO SUPABASE (sidebar)
# -------------------------------------------------------------------
from supabase import create_client

@st.cache_resource(show_spinner=False)
def _sb():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def _clear_session():
    for k in ("user_id", "user_email", "access_token", "refresh_token"):
        st.session_state.pop(k, None)

def _set_session_from_auth_res(auth_res):
    user = getattr(auth_res, "user", None)
    session = getattr(auth_res, "session", None)
    if user:
        st.session_state["user_id"] = user.id
        st.session_state["user_email"] = user.email
    if session:
        st.session_state["access_token"] = session.access_token
        st.session_state["refresh_token"] = session.refresh_token

sb = _sb()

qp = st.query_params()
if qp.get("type", [""])[0] == "recovery":
    st.info("Você veio de um link de recuperação. Faça login com a nova senha.")

with st.sidebar:
    st.markdown("### 🔐 Acesso")
    if "user_id" not in st.session_state:
        tab1, tab2, tab3 = st.tabs(["Entrar", "Criar conta", "Esqueci a senha"])

        with tab1:
            with st.form("signin"):
                email = st.text_input("E-mail", key="signin_email")
                pw = st.text_input("Senha", type="password", key="signin_pw")
                if st.form_submit_button("Entrar"):
                    try:
                        res = sb.auth.sign_in_with_password({"email": email, "password": pw})
                        _set_session_from_auth_res(res)
                        st.success("Login ok!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Falha no login: {e}")

        with tab2:
            with st.form("signup"):
                email_up = st.text_input("E-mail", key="signup_email")
                pw_up = st.text_input("Senha", type="password", key="signup_pw")
                if st.form_submit_button("Criar conta"):
                    try:
                        res = sb.auth.sign_up({
                            "email": email_up,
                            "password": pw_up,
                            "options": {"email_redirect_to": st.secrets.get("RESET_REDIRECT_URL")}
                        })
                        st.success("Conta criada! Verifique seu e-mail para confirmar.")
                    except Exception as e:
                        st.error(f"Erro ao criar conta: {e}")

        with tab3:
            with st.form("forgot"):
                email_fp = st.text_input("E-mail", key="forgot_email")
                if st.form_submit_button("Enviar e-mail de redefinição"):
                    try:
                        sb.auth.reset_password_email(
                            email_fp,
                            options={"redirect_to": st.secrets.get("RESET_REDIRECT_URL")}
                        )
                        st.success("Se o e-mail existir, enviamos o link de redefinição.")
                    except Exception as e:
                        st.error(f"Erro ao enviar e-mail: {e}")
    else:
        st.write(f"Conectado como: **{st.session_state['user_email']}**")
        if st.button("Sair"):
            try:
                sb.auth.sign_out()
            except Exception:
                pass
            _clear_session()
            st.rerun()

# Se não logado, o app para aqui (sidebar fica visível)
if "user_id" not in st.session_state:
    st.stop()

# -------------------------------------------------------------------
# ESTADO
# -------------------------------------------------------------------
if "ref_date" not in st.session_state: st.session_state.ref_date = date.today()
if "period"   not in st.session_state: st.session_state.period   = "Mês"
if "pending_tx" not in st.session_state: st.session_state.pending_tx = None
if "chat_log" not in st.session_state: st.session_state.chat_log = []

# -------------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------------
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
    ok = data_io.delete_last()
    if ok:
        st.session_state.chat_log.append(("assistant","Último lançamento removido ✅"))
    else:
        st.session_state.chat_log.append(("assistant","Não há lançamentos para desfazer."))

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

# -------------------------------------------------------------------
# HEADER
# -------------------------------------------------------------------
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

# -------------------------------------------------------------------
# CHAT
# -------------------------------------------------------------------
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

    # Confirmação pendente
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
                    # grava direto no Supabase
                    data_io.append_row(p)
                    # realinha filtros para o mês do lançamento
                    _saved_date = pd.to_datetime(p["data"]).date()
                    st.session_state.ref_date = _saved_date
                    if st.session_state.period not in ("Dia","Semana","Mês"):
                        st.session_state.period = "Mês"
                    # recarrega e responde
                    DF_now = data_io.load()
                    st.session_state.chat_log.append(("assistant", _ctx_reply(DF_now, p)))
                    st.session_state.pending_tx = None
                    st.rerun()
            with c2:
                if st.button("❌ Cancelar"):
                    st.session_state.chat_log.append(("assistant","Ok, não salvei esse lançamento."))
                    st.session_state.pending_tx = None
                    st.rerun()

    # Envio
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

# -------------------------------------------------------------------
# DASHBOARD
# -------------------------------------------------------------------
start, end = period_bounds(st.session_state.ref_date, st.session_state.period)

# carrega do Supabase (você pode passar start/end pra filtrar no server)
DF_now = data_io.load()
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
