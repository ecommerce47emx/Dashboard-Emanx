import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

# 1. Configuração da Página
st.set_page_config(page_title="Dashboard de Vendas", layout="wide")

# 2. URL da Planilha (Substitua pelo seu link de compartilhamento)
url_planilha = "https://docs.google.com/spreadsheets/d/1wO3-to-_TjdYUsT9qN9TEyXg7A6dOtuy0RRa79usVTk/edit?usp=sharing"

# 3. Conexão com Google Sheets
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    # Lendo os dados (ttl=0 força o refresh para testarmos agora)
    df = conn.read(spreadsheet=url_planilha, ttl="0")

    # --- TRATAMENTO DE COLUNAS ---
    # Limpa espaços em branco invisíveis nos nomes das colunas
    df.columns = [str(c).strip() for c in df.columns]

    # --- TRATAMENTO DE VALORES (MOEDA) ---
    def limpar_moeda(valor):
        if pd.isna(valor) or valor == "" or valor == " R$ -  ":
            return 0.0
        v = str(valor).replace('R$', '').replace('.', '').replace(',', '.').strip()
        try:
            return float(v)
        except:
            return 0.0

    if 'Receita' in df.columns:
        df['Receita_Num'] = df['Receita'].apply(limpar_moeda)
    
    # --- INTERFACE ---
    st.title("📊 Dashboard de Performance de Vendas")

    # Verificação de segurança: se as colunas necessárias existem
    colunas_necessarias = ["Grupo de Marketplace", "Tipo pedido", "Status do pedido"]
    if all(col in df.columns for col in colunas_necessarias):

        # --- FILTROS LATERAIS ---
        st.sidebar.header("Filtros de Visualização")
        
        # Filtro de Marketplace
        mkt_lista = sorted(df["Grupo de Marketplace"].dropna().unique())
        mkt_sel = st.sidebar.multiselect("Selecione o Marketplace", options=mkt_lista, default=mkt_lista)

        # Filtro de Status
        status_lista = sorted(df["Status do pedido"].dropna().unique())
        status_sel = st.sidebar.multiselect("Status do Pedido", options=status_lista, default=status_lista)

        # Aplicando filtros
        df_filtrado = df[
            (df["Grupo de Marketplace"].isin(mkt_sel)) & 
            (df["Status do pedido"].isin(status_sel))
        ]

        # --- MÉTRICAS PRINCIPAIS ---
        c1, c2, c3 = st.columns(3)
        total_faturamento = df_filtrado['Receita_Num'].sum()
        c1.metric("Faturamento Total", f"R$ {total_faturamento:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
        c2.metric("Total de Pedidos", len(df_filtrado))
        
        qtd_total = pd.to_numeric(df_filtrado["Quantidade vendida"], errors='coerce').sum()
        c3.metric("Itens Vendidos", int(qtd_total))

        st.divider()

        # --- GRÁFICO: MARKETPLACE E TIPO PEDIDO ---
        st.subheader("Faturamento por Grupo de Marketplace e Tipo de Pedido")
        
        # Agrupando os dados
        df_chart = df_filtrado.groupby(['Grupo de Marketplace', 'Tipo pedido'])['Receita_Num'].sum().reset_index()
        
        # Pivotando para criar o gráfico de barras empilhadas
        df_pivot = df_chart.pivot(index='Grupo de Marketplace', columns='Tipo pedido', values='Receita_Num').fillna(0)
        
        st.bar_chart(df_pivot)

        # --- TABELA DETALHADA ---
        with st.expander("Ver Detalhamento dos Pedidos"):
            colunas_exibir = ['Data emissao', 'Grupo de Marketplace', 'Tipo pedido', 'Produto', 'Receita', 'Status do pedido']
            st.dataframe(df_filtrado[colunas_exibir], use_container_width=True)

    else:
        st.error(f"Erro: Colunas não encontradas. Verifique se os nomes na planilha estão corretos.")
        st.write("Colunas detectadas:", df.columns.tolist())

except Exception as e:
    st.error(f"Não foi possível carregar os dados: {e}")
