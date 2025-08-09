# 🧮 Finance AI — Dashboard + Chat (Streamlit + Supabase)

Aplicativo financeiro simples com:
- Chat para registrar **gastos/ganhos/investimentos** em linguagem natural (PT-BR)
- **Autenticação Supabase** (login, criar conta, reset de senha)
- **RLS**: cada usuário só vê seus próprios dados
- Gráficos modernos (Plotly) e um dashboard enxuto

## 🚀 Stack
- Python, Streamlit
- Plotly, Pandas, python-dateutil
- Supabase (Auth + Postgres)
  
## 🗂️ Estrutura de pastas (sugerida)
.
├─ app.py
├─ engine/
│ ├─ init.py
│ └─ parse.py
├─ requirements.txt
├─ README.md
└─ .streamlit/
└─ secrets.toml 


## 🔐 Variáveis de ambiente (Streamlit Secrets)

Crie o arquivo `.streamlit/secrets.toml` (localmente) e defina:

SUPABASE_URL = "https://<your-project>.supabase.co"
SUPABASE_KEY = "<anon-or-service-role-key>"

No Streamlit Cloud, vá em App → Settings → Secrets e cole as mesmas chaves.

🛠️ Banco de dados (Supabase)
Rode no SQL Editor do Supabase:

Tabela:


create table if not exists public.transactions (
  id          bigint generated always as identity primary key,
  user_id     uuid    not null references auth.users(id) on delete cascade,
  data        date    not null,
  tipo        text    not null check (tipo in ('gasto','ganho','investimento')),
  valor       numeric(12,2) not null,
  categoria   text,
  descricao   text,
  created_at  timestamptz not null default now()
);

create index if not exists idx_transactions_user_date on public.transactions (user_id, data);
alter table public.transactions enable row level security;


2. Políticas RLS:


create policy "read own" on public.transactions
for select using (auth.uid() = user_id);

create policy "insert own" on public.transactions
for insert with check (auth.uid() = user_id);

create policy "update own" on public.transactions
for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "delete own" on public.transactions
for delete using (auth.uid() = user_id);


3. Reset de senha:

Em Authentication → URL Configuration:

Site URL = URL do seu app no Streamlit Cloud

Redirect URLs = mesma URL

O app já usa reset_password_email, então está pronto.

▶️ Rodando localmente
Crie e ative um virtualenv (opcional)

Instale dependências:

pip install -r requirements.txt
Crie .streamlit/secrets.toml com suas chaves

Rode:

streamlit run app.py

☁️ Deploy no Streamlit Cloud
Suba o código no GitHub (raiz contendo app.py, requirements.txt, engine/, .streamlit/ sem o secrets).

No Streamlit Cloud, crie um novo app a partir do repositório (branch main/master).

Em Settings → Secrets, cole:


SUPABASE_URL = "https://<your-project>.supabase.co"
SUPABASE_KEY = "<anon-key>"
Deploy. Pronto!

💬 Exemplos de mensagens (chat)
gastei 37,90 no supermercado ontem

recebi 1500 de salário 05/08

investi 200 em cdb hoje

resumo da semana / resumo do mês / saldo de hoje

desfazer último

🔒 Nota de segurança
Use Anon Key no front (Streamlit) com RLS ativada (como neste projeto).

Para jobs administrativos (mutações em lote, migrações), use a Service Role Key no servidor/CI apenas.