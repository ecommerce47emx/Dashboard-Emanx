import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Dashboard de Vendas", layout="wide")

# URL da sua planilha (Certifique-se de que é o link de compartilhamento)
url_planilha = "https://docs.google.com/spreadsheets/d/1wO3-to-_TjdYUsT9qN9TEyXg7A6dOtuy0RRa79usVTk/edit?usp=sharing"

# Conectando
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    # Lendo os dados
    df = conn.read(spreadsheet=url_planilha, ttl="0") # ttl="0" para forçar atualização enquanto testamos

    # --- PASSO CRUCIAL: LIMPEZA DOS CABEÇALHOS ---
    # Remove espaços vazios antes/depois e garante que o nome seja exatamente o que você colou
    df.columns = [str(c).strip() for c in df.columns]

    # Exibe as colunas detectadas para você conferir no painel (depois pode apagar essa linha)
    # st.write("Colunas detectadas:", df.columns.tolist())

    if "Estado" in df.columns:
        st.title("📊 Dashboard de Vendas")

        # Tratamento da Receita (Removendo R$, pontos e trocando vírgula por ponto)
        if 'Receita' in df.columns:
            df['Receita_Num'] = df['Receita'].astype(str).str.replace('R\$', '', regex=True).str.replace('.', '', regex=False).str.replace(',', '.', regex=False).str.strip()
            df['Receita_Num'] = pd.to_numeric(df['Receita_Num'], errors='coerce').fillna(0)

        # Filtros
        st.sidebar.header("Filtros")
        
        # Estado
        lista_estados = sorted(df["Estado"].dropna().unique())
        estados_sel = st.sidebar.multiselect("Estados", options=lista_estados, default=lista_estados)

        # Status
        lista_status = sorted(df["Status do pedido"].dropna().unique())
        status_sel = st.sidebar.multiselect("Status", options=lista_status, default=lista_status)

        # Filtragem
        df_filtrado = df[df["Estado"].isin(estados_sel) & df["Status do pedido"].isin(status_sel)]

        # Métricas
        c1, c2, c3 = st.columns(3)
        c1.metric("Faturamento", f"R$ {df_filtrado['Receita_Num'].sum():,.2f}")
        c2.metric("Pedidos", len(df_filtrado))
        c3.metric("Qtd Vendida", int(df_filtrado["Quantidade vendida"].sum()))

        # Gráfico Simples
        st.subheader("Faturamento por Estado")
        st.bar_chart(df_filtrado.groupby("Estado")["Receita_Num"].sum())

    else:
        st.error(f"Erro: Coluna 'Estado' não encontrada. Colunas lidas: {df.columns.tolist()}")

except Exception as e:
    st.error(f"Erro ao conectar com a planilha: {e}")
    st.info("Dica: Verifique se a planilha está compartilhada como 'Qualquer pessoa com o link pode ler'.")
