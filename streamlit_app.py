import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

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
url_planilha = "https://docs.google.com/spreadsheets/d/1wO3-to-_TjdYUsT9qN9TEyXg7A6dOtuy0RRa79usVTk/edit?gid=1603417773#gid=1603417773"
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


def formatar_brl(valor: float) -> str:
    """Formata float como moeda BRL."""
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def normalizar_texto(valor):
    """Remove acentos e normaliza texto para comparação."""
    if pd.isna(valor):
        return ""
    txt = str(valor).strip().upper()
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return txt


def parse_data_coluna(df: pd.DataFrame, coluna: str) -> pd.Series:
    """Converte uma coluna para datetime normalizada."""
    if coluna not in df.columns:
        return pd.Series(pd.NaT, index=df.index)

    return pd.to_datetime(df[coluna], errors="coerce", dayfirst=True).dt.normalize()


def data_venda_efetiva(df: pd.DataFrame) -> pd.Series:
    """
    Retorna a data efetiva de venda:
    usa 'Data da Venda' quando preenchida
    caso contrário usa 'Data emissao'
    """
    series_venda = parse_data_coluna(df, "Data da Venda")
    series_emissao = parse_data_coluna(df, "Data emissao")
    return series_venda.fillna(series_emissao)


def normalizar_codigo(valor, tamanho_min=6):
    """
    Normaliza o código do produto preservando zeros à esquerda.
    Ex.: 42333.0 vira 042333
    """
    if pd.isna(valor):
        return ""

    txt = str(valor).strip()

    if txt.endswith(".0"):
        txt = txt[:-2]

    num = pd.to_numeric(txt, errors="coerce")
    if pd.notna(num):
        txt = str(int(num))
    else:
        txt = re.sub(r"\D", "", txt)

    if not txt:
        return ""

    return txt.zfill(tamanho_min)


def extrair_cor3(valor):
    """
    Extrai o código de cor com 3 dígitos.
    Ex.: '001 - PRETO' -> '001'
    """
    if pd.isna(valor):
        return ""

    txt = str(valor).strip().upper()

    m = re.match(r"^\s*(\d{1,3})", txt)
    if m:
        return m.group(1).zfill(3)

    digitos = re.sub(r"\D", "", txt)
    if digitos:
        return digitos[:3].zfill(3)

    return ""


def build_img_url(row):
    """
    Monta a URL da imagem do produto.
    Formato: BASE_URL + Código + Cor(3 dígitos) + '1.jpg'
    Exemplo: 042333 + 003 + 1.jpg -> 0423330031.jpg
    """
    try:
        codigo = normalizar_codigo(row.get("Código", ""))
        cor3 = extrair_cor3(row.get("Cor", ""))

        if codigo and cor3:
            return f"{BASE_IMG_URL}{codigo}{cor3}1.jpg"
    except Exception:
        pass

    return ""


def primeiro_valor_nao_vazio(series):
    """Retorna o primeiro valor não vazio de uma série."""
    for v in series:
        if pd.notna(v) and str(v).strip() != "":
            return v
    return ""


def preparar_metricas_visao(df_base: pd.DataFrame, somente_devolucao: bool) -> pd.DataFrame:
    """
    No modo devolução, usa valor absoluto para facilitar a leitura.
    """
    df_out = df_base.copy()

    if somente_devolucao:
        df_out["Receita_Visao"] = df_out["Receita_Num"].abs()
        df_out["Liquido_Visao"] = df_out["Liquido_Num"].abs()
        df_out["Qtd_Visao"] = df_out["Qtd_Num"].abs()
    else:
        df_out["Receita_Visao"] = df_out["Receita_Num"]
        df_out["Liquido_Visao"] = df_out["Liquido_Num"]
        df_out["Qtd_Visao"] = df_out["Qtd_Num"]

    return df_out


def calcular_status_e_projecao(data_ini, data_fim, total_atual):
    """
    Calcula a projeção mensal apenas quando:
    - o filtro está dentro de um único mês
    - é o mês atual
    - o mês ainda não terminou
    - o filtro começou no dia 1
    - o filtro cobre os dados até ontem
    """
    if data_ini is None or data_fim is None:
        return {"status": "sem_periodo"}

    data_ini = pd.Timestamp(data_ini).normalize()
    data_fim = pd.Timestamp(data_fim).normalize()

    if data_ini.year != data_fim.year or data_ini.month != data_fim.month:
        return {"status": "multiplos_meses"}

    inicio_mes = data_ini.replace(day=1)
    fim_mes = inicio_mes + pd.offsets.MonthEnd(1)

    hoje_sp = pd.Timestamp(datetime.now(ZoneInfo("America/Sao_Paulo")).date())
    ontem_sp = hoje_sp - pd.Timedelta(days=1)
    inicio_mes_atual = hoje_sp.replace(day=1)

    mes_referencia = data_ini.replace(day=1)

    if mes_referencia > inicio_mes_atual:
        return {
            "status": "futuro",
            "inicio_mes": inicio_mes,
            "fim_mes": fim_mes,
            "dias_mes": fim_mes.day,
        }

    if mes_referencia < inicio_mes_atual:
        if data_ini == inicio_mes and data_fim >= fim_mes:
            return {
                "status": "finalizado",
                "inicio_mes": inicio_mes,
                "fim_mes": fim_mes,
                "dias_mes": fim_mes.day,
            }
        return {
            "status": "intervalo_parcial",
            "inicio_mes": inicio_mes,
            "fim_mes": fim_mes,
            "dias_mes": fim_mes.day,
        }

    if data_ini != inicio_mes:
        return {
            "status": "intervalo_parcial",
            "inicio_mes": inicio_mes,
            "fim_mes": fim_mes,
            "dias_mes": fim_mes.day,
        }

    if ontem_sp >= fim_mes:
        return {
            "status": "finalizado",
            "inicio_mes": inicio_mes,
            "fim_mes": fim_mes,
            "dias_mes": fim_mes.day,
        }

    if data_fim < ontem_sp:
        return {
            "status": "intervalo_parcial",
            "inicio_mes": inicio_mes,
            "fim_mes": fim_mes,
            "dias_mes": fim_mes.day,
        }

    dias_passados = ontem_sp.day
    dias_mes = fim_mes.day
    dias_restantes = dias_mes - dias_passados

    if dias_passados <= 0:
        return {
            "status": "sem_base",
            "inicio_mes": inicio_mes,
            "fim_mes": fim_mes,
            "dias_mes": dias_mes,
        }

    projecao = (total_atual / dias_passados) * dias_mes

    return {
        "status": "em_andamento",
        "inicio_mes": inicio_mes,
        "fim_mes": fim_mes,
        "dias_mes": dias_mes,
        "dias_passados": dias_passados,
        "dias_restantes": dias_restantes,
        "projecao": projecao,
    }


# ──────────────────────────────────────────────
# 5. CARGA E TRATAMENTO DOS DADOS
# ──────────────────────────────────────────────
try:
    df = conn.read(spreadsheet=url_planilha, ttl="0")
    df.columns = [str(c).strip() for c in df.columns]

    # Colunas monetárias
    for col_orig, col_num in [
        ("Receita", "Receita_Num"),
        ("Liquido", "Liquido_Num"),
        ("Custo medio", "Custo_Num"),
    ]:
        df[col_num] = df[col_orig].apply(limpar_moeda) if col_orig in df.columns else 0.0

    # Quantidade vendida numérica
    df["Qtd_Num"] = pd.to_numeric(df.get("Quantidade vendida"), errors="coerce").fillna(0)

    # Datas
    df["Data_Emissao_Filtro"] = parse_data_coluna(df, "Data emissao")
    df["Data_Venda_Efetiva"] = data_venda_efetiva(df)

    # Identificação de devolução pelo Grupo de Marketplace
    df["Eh_Devolucao"] = (
        df["Grupo de Marketplace"]
        .apply(normalizar_texto)
        .str.contains("DEVOLUCAO", na=False)
    )

    # URL da imagem
    df["img_url"] = df.apply(build_img_url, axis=1)

    # ──────────────────────────────────────────
    # 6. VALIDAÇÃO DE COLUNAS OBRIGATÓRIAS
    # ──────────────────────────────────────────
    colunas_necessarias = ["Grupo de Marketplace", "Tipo pedido", "Data emissao"]
    if not all(col in df.columns for col in colunas_necessarias):
        st.error("Colunas obrigatórias não encontradas. Verifique a planilha.")
        st.write("Colunas detectadas:", df.columns.tolist())
        st.stop()

    # ──────────────────────────────────────────
    # 7. FILTROS LATERAIS
    # ──────────────────────────────────────────
    st.sidebar.header("Filtros")

    # Marketplace
    mkt_lista = sorted(df["Grupo de Marketplace"].dropna().unique())
    mkt_sel = st.sidebar.multiselect("Marketplace", options=mkt_lista, default=mkt_lista)

    # Marca
    if "Marca" in df.columns:
        marca_lista = sorted(df["Marca"].dropna().unique())
        marca_sel = st.sidebar.multiselect("Marca", options=marca_lista, default=marca_lista)
    else:
        marca_sel = None

    # Toggle devolução
    somente_devolucao = st.sidebar.toggle("Somente Devolução", value=False)

    # Filtro de período por Data emissao
    datas_validas = df["Data_Emissao_Filtro"].dropna()
    if not datas_validas.empty:
        data_min = datas_validas.min().date()
        data_max = datas_validas.max().date()

        periodo = st.sidebar.date_input(
            "Período de Venda",
            value=(data_min, data_max),
            min_value=data_min,
            max_value=data_max,
        )

        if isinstance(periodo, (list, tuple)) and len(periodo) == 2:
            data_ini = pd.Timestamp(periodo[0]).normalize()
            data_fim = pd.Timestamp(periodo[1]).normalize()
        else:
            data_ini = pd.Timestamp(data_min).normalize()
            data_fim = pd.Timestamp(data_max).normalize()
    else:
        data_ini, data_fim = None, None

    # ──────────────────────────────────────────
    # 8. APLICANDO FILTROS
    # ──────────────────────────────────────────
    df_f = df[df["Grupo de Marketplace"].isin(mkt_sel)].copy()

    if marca_sel is not None:
        df_f = df_f[df_f["Marca"].isin(marca_sel)]

    if data_ini is not None and data_fim is not None:
        df_f = df_f[
            (df_f["Data_Emissao_Filtro"] >= data_ini) &
            (df_f["Data_Emissao_Filtro"] <= data_fim)
        ]

    if somente_devolucao:
        df_f = df_f[df_f["Eh_Devolucao"]].copy()

    df_f = preparar_metricas_visao(df_f, somente_devolucao)

    # ──────────────────────────────────────────
    # 9. CABEÇALHO
    # ──────────────────────────────────────────
    st.title("Dashboard de Performance de Vendas")

    if somente_devolucao:
        st.caption(
            f"{len(df_f):,} registros exibidos | modo devolução ativo | período filtrado por Data emissao"
        )
    else:
        st.caption(
            f"{len(df_f):,} pedidos exibidos após filtros aplicados | período filtrado por Data emissao"
        )

    # ──────────────────────────────────────────
    # 10. CSS DAS MÉTRICAS
    # ──────────────────────────────────────────
    st.markdown(
        """
        <style>
        div[data-testid="stMetric"] {
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(128,128,128,0.18);
            border-radius: 12px;
            padding: 14px 16px;
        }
        div[data-testid="stMetricLabel"] {
            font-size: 0.95rem;
        }
        div[data-testid="stMetricValue"] {
            font-size: 1.45rem;
            line-height: 1.15;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # ──────────────────────────────────────────
    # 11. MÉTRICAS PRINCIPAIS
    # ──────────────────────────────────────────
    receita_total = df_f["Receita_Visao"].sum()
    liquido_total = df_f["Liquido_Visao"].sum()
    custo_medio = df_f["Custo_Num"].mean() if len(df_f) > 0 else 0.0
    qtd_total = int(df_f["Qtd_Visao"].sum())
    total_pedidos = len(df_f)

    info_proj = calcular_status_e_projecao(
        data_ini=data_ini,
        data_fim=data_fim,
        total_atual=receita_total
    )

    linha1 = st.columns(3)
    linha2 = st.columns(3)

    linha1[0].metric("Receita Total", formatar_brl(receita_total))
    linha1[1].metric("Líquido Total", formatar_brl(liquido_total))
    linha1[2].metric("Custo Médio", formatar_brl(custo_medio))

    linha2[0].metric("Itens Vendidos", f"{qtd_total:,}")
    linha2[1].metric("Total de Pedidos", f"{total_pedidos:,}")

    if info_proj["status"] == "em_andamento":
        linha2[2].metric("Projeção do Mês", formatar_brl(info_proj["projecao"]))
        st.caption(
            f"Mês em andamento. {info_proj['dias_passados']} dias passados, "
            f"{info_proj['dias_restantes']} dias restantes, total de {info_proj['dias_mes']} dias."
        )
    elif info_proj["status"] == "finalizado":
        linha2[2].metric("Projeção do Mês", "Mês finalizado")
        st.caption("O mês filtrado já foi encerrado, então não há projeção.")
    elif info_proj["status"] == "intervalo_parcial":
        linha2[2].metric("Projeção do Mês", "N/D")
        st.caption("Para projetar o mês atual, o filtro precisa cobrir o mês desde o dia 1 até ontem.")
    elif info_proj["status"] == "multiplos_meses":
        linha2[2].metric("Projeção do Mês", "N/D")
        st.caption("A projeção mensal funciona apenas quando o filtro está dentro de um único mês.")
    elif info_proj["status"] == "futuro":
        linha2[2].metric("Projeção do Mês", "N/D")
        st.caption("O período selecionado está em um mês futuro.")
    else:
        linha2[2].metric("Projeção do Mês", "N/D")

    st.divider()

    # ──────────────────────────────────────────
    # 12. GRÁFICO: VENDAS POR DIA
    # ──────────────────────────────────────────
    if somente_devolucao:
        st.subheader("Devoluções por Dia")
    else:
        st.subheader("Vendas por Dia")

    if not df_f["Data_Venda_Efetiva"].isna().all():
        df_dia = (
            df_f.groupby(df_f["Data_Venda_Efetiva"].dt.date)["Receita_Visao"]
            .sum()
            .reset_index()
            .rename(columns={"Data_Venda_Efetiva": "Data", "Receita_Visao": "Receita"})
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
                y=alt.Y("Receita:Q", title="Valor (R$)"),
                tooltip=[
                    alt.Tooltip("Data:T", title="Data", format="%d/%m/%Y"),
                    alt.Tooltip("Receita:Q", title="Valor", format=",.2f"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(chart_linha, use_container_width=True)
    else:
        st.info("Sem dados de data disponíveis para o período selecionado.")

    st.divider()

    # ──────────────────────────────────────────
    # 13. GRÁFICO: MARKETPLACE × TIPO PEDIDO
    # ──────────────────────────────────────────
    if somente_devolucao:
        st.subheader("Devoluções por Marketplace")

        df_mkt = (
            df_f.groupby(["Grupo de Marketplace"])["Receita_Visao"]
            .sum()
            .reset_index()
            .rename(columns={"Receita_Visao": "Receita"})
        )

        chart_bar = (
            alt.Chart(df_mkt)
            .mark_bar()
            .encode(
                x=alt.X("Grupo de Marketplace:N", title="Marketplace", sort="-y"),
                y=alt.Y("Receita:Q", title="Valor (R$)"),
                tooltip=[
                    "Grupo de Marketplace:N",
                    alt.Tooltip("Receita:Q", format=",.2f"),
                ],
            )
            .properties(height=320)
        )
    else:
        st.subheader("Faturamento por Marketplace e Tipo de Pedido")

        df_mkt = (
            df_f.groupby(["Grupo de Marketplace", "Tipo pedido"])["Receita_Visao"]
            .sum()
            .reset_index()
            .rename(columns={"Receita_Visao": "Receita"})
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
    # 14. RANKING DE PRODUTOS
    # ──────────────────────────────────────────
    st.subheader("Ranking de Produtos")

    col_produto = "Produto" if "Produto" in df_f.columns else None

    if col_produto:
        if somente_devolucao:
            tab_receita, tab_qtd = st.tabs(["Por Valor Devolvido", "Por Quantidade Devolvida"])
        else:
            tab_receita, tab_qtd = st.tabs(["Por Receita", "Por Quantidade Vendida"])

        df_rank_base = (
            df_f.groupby(col_produto)
            .agg(
                Receita=("Receita_Visao", "sum"),
                Quantidade=("Qtd_Visao", "sum"),
                img_url=("img_url", primeiro_valor_nao_vazio),
            )
            .reset_index()
        )

        TOP_N = st.slider("Número de produtos no ranking", 5, 30, 10, key="top_n")

        def render_ranking(df_rank: pd.DataFrame, col_valor: str, fmt_fn=None):
            df_top = df_rank.nlargest(TOP_N, col_valor).reset_index(drop=True)
            df_top.index += 1

            for pos, row in df_top.iterrows():
                cols = st.columns([0.6, 1.2, 5, 2])

                cols[0].markdown(f"{pos}")

                if row["img_url"]:
                    cols[1].image(row["img_url"], width=60)
                else:
                    cols[1].markdown("—")

                cols[2].markdown(str(row[col_produto]))

                valor = row[col_valor]
                texto = fmt_fn(valor) if fmt_fn else f"{int(valor):,}"
                cols[3].markdown(texto)

        with tab_receita:
            render_ranking(df_rank_base, "Receita", formatar_brl)

        with tab_qtd:
            render_ranking(df_rank_base, "Quantidade")

    else:
        st.info("Coluna 'Produto' não encontrada na planilha.")

    st.divider()

    # ──────────────────────────────────────────
    # 15. TABELA DETALHADA
    # ──────────────────────────────────────────
    with st.expander("Ver Detalhamento dos Pedidos"):
        df_exibir = df_f.copy()

        if somente_devolucao:
            df_exibir["Receita Visual"] = df_exibir["Receita_Visao"]
            df_exibir["Quantidade Visual"] = df_exibir["Qtd_Visao"]
            df_exibir["Liquido Visual"] = df_exibir["Liquido_Visao"]

        colunas_base = [
            "Data emissao",
            "Data da Venda",
            "Grupo de Marketplace",
            "Tipo pedido",
            "Marca",
            "Produto",
            "Receita",
            "Liquido",
            "Custo medio",
            "Quantidade vendida",
            "Status do pedido",
        ]

        if somente_devolucao:
            colunas_base.extend(["Receita Visual", "Quantidade Visual", "Liquido Visual"])

        colunas_exibir = [c for c in colunas_base if c in df_exibir.columns]

        st.dataframe(df_exibir[colunas_exibir], use_container_width=True)

except Exception as e:
    st.error(f"Não foi possível carregar os dados: {e}")
    st.exception(e)
