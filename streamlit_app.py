import streamlit as st
import pandas as pd
import altair as alt

from streamlit_gsheets import GSheetsConnection

# ──────────────────────────────────────────────
# 1. CONFIGURAÇÃO DA PÁGINA
# ──────────────────────────────────────────────
st.set_page_config(page_title="Dashboard de Vendas", layout="wide")

# ──────────────────────────────────────────────
# 2. URL DA PLANILHA
# ──────────────────────────────────────────────
url_planilha = "https://docs.google.com/spreadsheets/d/1wO3-to-_TjdYUsT9qN9TEyXg7A6dOtuy0RRa79usVTk/edit?usp=sharing"
BASE_IMG_URL = "https://emanxtelecom.com.br/imagens/"

# ──────────────────────────────────────────────
# 3. CONEXÃO COM GOOGLE SHEETS
# ──────────────────────────────────────────────
conn = st.connection("gsheets", type=GSheetsConnection)

# ──────────────────────────────────────────────
# 4. HELPERS
# ──────────────────────────────────────────────
def limpar_moeda(valor):
    """Converte valores monetários em float."""
    if pd.isna(valor) or str(valor).strip() in ("", "R$ -", " R$ - "):
        return 0.0
    v = str(valor).replace("R$", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(v)
    except ValueError:
        return 0.0


def build_img_url(row):
    """
    Monta a URL da imagem do produto.
    Formato: BASE_URL + Código + 3 primeiros dígitos de Cor + "1.jpg"
    Exemplo: Código=014482 | Cor="001 - PRETO" → 0144820011.jpg
    Os 3 primeiros chars do campo Cor já são o código numérico da cor.
    """
    try:
        codigo = str(row.get("Código", "")).strip()
        cor    = str(row.get("Cor", "")).strip()   # campo exato da planilha
        if codigo and cor and cor.lower() != "nan":
            cor3 = cor[:3]          # "001 - PRETO" → "001"
            return f"{BASE_IMG_URL}{codigo}{cor3}1.jpg"
    except Exception:
        pass
    return ""


def formatar_brl(valor: float) -> str:
    """Formata float como moeda BRL."""
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def data_venda_efetiva(df: pd.DataFrame) -> pd.Series:
    """
    Retorna a data efetiva de venda:
    - usa 'Data da Venda' quando preenchida
    - caso contrário usa 'Data emissao'
    """
    col_venda   = "Data da Venda"
    col_emissao = "Data emissao"

    series_venda   = pd.to_datetime(df[col_venda],   errors="coerce", dayfirst=True) \
                     if col_venda   in df.columns else pd.NaT
    series_emissao = pd.to_datetime(df[col_emissao], errors="coerce", dayfirst=True) \
                     if col_emissao in df.columns else pd.NaT

    if isinstance(series_venda, pd.Series) and isinstance(series_emissao, pd.Series):
        return series_venda.fillna(series_emissao)
    elif isinstance(series_venda, pd.Series):
        return series_venda
    elif isinstance(series_emissao, pd.Series):
        return series_emissao
    else:
        return pd.Series(pd.NaT, index=df.index)


# ──────────────────────────────────────────────
# 5. CARGA E TRATAMENTO DOS DADOS
# ──────────────────────────────────────────────
try:
    df = conn.read(spreadsheet=url_planilha, ttl="0")
    df.columns = [str(c).strip() for c in df.columns]   # remove espaços nos nomes

    # Colunas monetárias  (nomes exatos da planilha)
    for col_orig, col_num in [
        ("Receita",      "Receita_Num"),
        ("Liquido",      "Liquido_Num"),   # sem acento
        ("Custo medio",  "Custo_Num"),     # coluna correta
    ]:
        df[col_num] = df[col_orig].apply(limpar_moeda) if col_orig in df.columns else 0.0

    # Quantidade vendida numérica
    df["Qtd_Num"] = pd.to_numeric(df.get("Quantidade vendida"), errors="coerce").fillna(0)

    # Data efetiva de venda
    df["Data_Venda_Efetiva"] = data_venda_efetiva(df)

    # URL de imagem
    df["img_url"] = df.apply(build_img_url, axis=1)

    # ──────────────────────────────────────────
    # 6. VALIDAÇÃO DE COLUNAS OBRIGATÓRIAS
    # ──────────────────────────────────────────
    colunas_necessarias = ["Grupo de Marketplace", "Tipo pedido"]
    if not all(col in df.columns for col in colunas_necessarias):
        st.error("Colunas obrigatórias não encontradas. Verifique a planilha.")
        st.write("Colunas detectadas:", df.columns.tolist())
        st.stop()

    # ──────────────────────────────────────────
    # 7. FILTROS LATERAIS
    # ──────────────────────────────────────────
    st.sidebar.header("🔍 Filtros")

    # Filtro de Marketplace
    mkt_lista = sorted(df["Grupo de Marketplace"].dropna().unique())
    mkt_sel   = st.sidebar.multiselect("Marketplace", options=mkt_lista, default=mkt_lista)

    # Filtro de Marca  (coluna exata da planilha)
    if "Marca" in df.columns:
        marca_lista = sorted(df["Marca"].dropna().unique())
        marca_sel   = st.sidebar.multiselect("Marca", options=marca_lista, default=marca_lista)
    else:
        marca_sel = None

    # Filtro de período
    datas_validas = df["Data_Venda_Efetiva"].dropna()
    if not datas_validas.empty:
        data_min = datas_validas.min().date()
        data_max = datas_validas.max().date()
        periodo  = st.sidebar.date_input(
            "Período de Venda",
            value=(data_min, data_max),
            min_value=data_min,
            max_value=data_max,
        )
        if isinstance(periodo, (list, tuple)) and len(periodo) == 2:
            data_ini, data_fim = pd.Timestamp(periodo[0]), pd.Timestamp(periodo[1])
        else:
            data_ini, data_fim = pd.Timestamp(data_min), pd.Timestamp(data_max)
    else:
        data_ini, data_fim = None, None

    # ──────────────────────────────────────────
    # 8. APLICANDO FILTROS
    # ──────────────────────────────────────────
    df_f = df[df["Grupo de Marketplace"].isin(mkt_sel)].copy()

    if marca_sel is not None:
        df_f = df_f[df_f["Marca"].isin(marca_sel)]

    if data_ini and data_fim:
        df_f = df_f[
            (df_f["Data_Venda_Efetiva"] >= data_ini) &
            (df_f["Data_Venda_Efetiva"] <= data_fim)
        ]

    # ──────────────────────────────────────────
    # 9. CABEÇALHO
    # ──────────────────────────────────────────
    st.title("📊 Dashboard de Performance de Vendas")
    st.caption(f"{len(df_f):,} pedidos exibidos após filtros aplicados")

    # ──────────────────────────────────────────
    # 10. MÉTRICAS PRINCIPAIS
    # ──────────────────────────────────────────
    receita_total  = df_f["Receita_Num"].sum()
    liquido_total  = df_f["Liquido_Num"].sum()
    custo_medio    = df_f["Custo_Num"].mean() if df_f["Custo_Num"].sum() > 0 else 0.0
    qtd_total      = int(df_f["Qtd_Num"].sum())
    total_pedidos  = len(df_f)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("💰 Receita Total",    formatar_brl(receita_total))
    c2.metric("✅ Líquido Total",    formatar_brl(liquido_total))
    c3.metric("📦 Custo Médio",      formatar_brl(custo_medio))
    c4.metric("📬 Itens Vendidos",   f"{qtd_total:,}")
    c5.metric("🛒 Total de Pedidos", f"{total_pedidos:,}")

    st.divider()

    # ──────────────────────────────────────────
    # 11. GRÁFICO: VENDAS POR DIA
    # ──────────────────────────────────────────
    st.subheader("📅 Vendas por Dia (Receita)")

    if not df_f["Data_Venda_Efetiva"].isna().all():
        df_dia = (
            df_f.groupby(df_f["Data_Venda_Efetiva"].dt.date)["Receita_Num"]
            .sum()
            .reset_index()
            .rename(columns={"Data_Venda_Efetiva": "Data", "Receita_Num": "Receita"})
        )
        df_dia["Data"] = pd.to_datetime(df_dia["Data"])

        chart_linha = (
            alt.Chart(df_dia)
            .mark_area(
                line={"color": "#4F8BFF"},
                color=alt.Gradient(
                    gradient="linear",
                    stops=[
                        alt.GradientStop(color="#4F8BFF", offset=1),
                        alt.GradientStop(color="rgba(79,139,255,0.05)", offset=0),
                    ],
                    x1=1, x2=1, y1=1, y2=0,
                ),
            )
            .encode(
                x=alt.X("Data:T", title="Data"),
                y=alt.Y("Receita:Q", title="Receita (R$)"),
                tooltip=[
                    alt.Tooltip("Data:T", title="Data", format="%d/%m/%Y"),
                    alt.Tooltip("Receita:Q", title="Receita", format=",.2f"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(chart_linha, use_container_width=True)
    else:
        st.info("Sem dados de data disponíveis para o período selecionado.")

    st.divider()

    # ──────────────────────────────────────────
    # 12. GRÁFICO: MARKETPLACE × TIPO PEDIDO
    # ──────────────────────────────────────────
    st.subheader("🏪 Faturamento por Marketplace e Tipo de Pedido")

    df_mkt = (
        df_f.groupby(["Grupo de Marketplace", "Tipo pedido"])["Receita_Num"]
        .sum()
        .reset_index()
        .rename(columns={"Receita_Num": "Receita"})
    )

    chart_bar = (
        alt.Chart(df_mkt)
        .mark_bar()
        .encode(
            x=alt.X("Grupo de Marketplace:N", title="Marketplace", sort="-y"),
            y=alt.Y("Receita:Q", title="Receita (R$)"),
            color=alt.Color("Tipo pedido:N", title="Tipo"),
            tooltip=[
                "Grupo de Marketplace:N",
                "Tipo pedido:N",
                alt.Tooltip("Receita:Q", format=",.2f"),
            ],
        )
        .properties(height=320)
    )
    st.altair_chart(chart_bar, use_container_width=True)

    st.divider()

    # ──────────────────────────────────────────
    # 13. RANKING DE PRODUTOS
    # ──────────────────────────────────────────
    st.subheader("🏆 Ranking de Produtos")

    col_produto = "Produto" if "Produto" in df_f.columns else None

    if col_produto:
        tab_receita, tab_qtd = st.tabs(["💰 Por Receita", "📦 Por Quantidade Vendida"])

        df_rank_base = (
            df_f.groupby(col_produto)
            .agg(
                Receita=("Receita_Num", "sum"),
                Quantidade=("Qtd_Num", "sum"),
                img_url=("img_url", "first"),
            )
            .reset_index()
        )

        TOP_N = st.slider("Número de produtos no ranking", 5, 30, 10, key="top_n")

        def render_ranking(df_rank: pd.DataFrame, col_valor: str, label: str, fmt_fn=None):
            """Renderiza tabela de ranking com imagem do produto."""
            df_top = df_rank.nlargest(TOP_N, col_valor).reset_index(drop=True)
            df_top.index += 1   # ranking começa em 1

            for pos, row in df_top.iterrows():
                cols = st.columns([0.5, 1.2, 5, 2])
                cols[0].markdown(f"**#{pos}**")

                # Imagem
                if row["img_url"]:
                    cols[1].image(row["img_url"], width=60)
                else:
                    cols[1].markdown("—")

                # Nome do produto
                cols[2].markdown(f"**{row[col_produto]}**")

                # Valor
                valor = row[col_valor]
                texto = fmt_fn(valor) if fmt_fn else f"{int(valor):,}"
                cols[3].markdown(f"**{texto}**")

        with tab_receita:
            render_ranking(df_rank_base, "Receita", "Receita", formatar_brl)

        with tab_qtd:
            render_ranking(df_rank_base, "Quantidade", "Quantidade")

    else:
        st.info("Coluna 'Produto' não encontrada na planilha.")

    st.divider()

    # ──────────────────────────────────────────
    # 14. TABELA DETALHADA
    # ──────────────────────────────────────────
    with st.expander("📋 Ver Detalhamento dos Pedidos"):
        colunas_exibir = [
            c for c in [
                "Data_Venda_Efetiva", "Grupo de Marketplace", "Tipo pedido",
                "Marca", "Produto", "Receita", "Liquido", "Custo medio",
                "Quantidade vendida", "Status do pedido",
            ]
            if c in df_f.columns or c == "Data_Venda_Efetiva"
        ]
        st.dataframe(df_f[colunas_exibir], use_container_width=True)

except Exception as e:
    st.error(f"Não foi possível carregar os dados: {e}")
    st.exception(e)
