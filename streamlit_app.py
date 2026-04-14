import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

# 1. Configuração inicial da página
st.set_page_config(page_title="Dashboard de Vendas", layout="wide")
st.title("📊 Dashboard de Vendas - E-commerce")

# 2. Conectando com o Google Sheets
# Nota: Substitua a URL abaixo pelo link da sua planilha. 
# Para este exemplo simples funcionar direto, a planilha precisa estar com acesso "Qualquer pessoa com o link pode ver".
url_planilha = "https://docs.google.com/spreadsheets/d/1wO3-to-_TjdYUsT9qN9TEyXg7A6dOtuy0RRa79usVTk/edit?usp=sharing"

# Cria a conexão e lê os dados
conn = st.connection("gsheets", type=GSheetsConnection)
df = conn.read(spreadsheet=url_planilha, ttl="10m") # ttl="10m" faz o cache dos dados por 10 minutos

# 3. Tratamento de Dados
# Limpando a coluna 'Receita' para remover o 'R$', pontos e trocar vírgula por ponto para transformar em número
if 'Receita' in df.columns:
    df['Receita_Numerica'] = df['Receita'].astype(str).str.replace('R\$', '', regex=True)
    df['Receita_Numerica'] = df['Receita_Numerica'].str.replace('.', '', regex=False)
    df['Receita_Numerica'] = df['Receita_Numerica'].str.replace(',', '.', regex=False)
    df['Receita_Numerica'] = pd.to_numeric(df['Receita_Numerica'], errors='coerce')

# 4. Criando Filtros na Barra Lateral
st.sidebar.header("Filtros")
estado_selecionado = st.sidebar.multiselect(
    "Selecione o Estado:",
    options=df["Estado"].dropna().unique(),
    default=df["Estado"].dropna().unique()
)

status_selecionado = st.sidebar.multiselect(
    "Status do Pedido:",
    options=df["Status do pedido"].dropna().unique(),
    default=df["Status do pedido"].dropna().unique()
)

# Aplicando os filtros ao dataframe
df_filtrado = df[
    (df["Estado"].isin(estado_selecionado)) & 
    (df["Status do pedido"].isin(status_selecionado))
]

# 5. Criando as Métricas Principais (Cards)
st.markdown("### Resumo")
col1, col2, col3 = st.columns(3)

total_receita = df_filtrado['Receita_Numerica'].sum()
total_pedidos = len(df_filtrado)
ticket_medio = total_receita / total_pedidos if total_pedidos > 0 else 0

col1.metric("Faturamento Total", f"R$ {total_receita:,.2f}".replace(',', '_').replace('.', ',').replace('_', '.'))
col2.metric("Total de Pedidos", total_pedidos)
col3.metric("Ticket Médio", f"R$ {ticket_medio:,.2f}".replace(',', '_').replace('.', ',').replace('_', '.'))

st.divider()

# 6. Criando Gráficos
col_grafico1, col_grafico2 = st.columns(2)

with col_grafico1:
    st.markdown("#### Vendas por Estado")
    vendas_estado = df_filtrado.groupby('Estado')['Receita_Numerica'].sum().reset_index()
    st.bar_chart(vendas_estado, x='Estado', y='Receita_Numerica')

with col_grafico2:
    st.markdown("#### Quantidade por Status")
    status_contagem = df_filtrado['Status do pedido'].value_counts().reset_index()
    st.bar_chart(status_contagem, x='Status do pedido', y='count')

# 7. Tabela de Dados Detalhados
st.markdown("#### Detalhamento dos Pedidos")
st.dataframe(df_filtrado[['Data emissao', 'Cliente', 'Estado', 'Produto', 'Receita', 'Status do pedido']], use_container_width=True)
