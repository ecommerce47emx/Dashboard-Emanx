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
    if pd.isna(valor) or str(valor).strip() in ("", "R$ -", " R$ - "):
        return 0.0

    v = str(valor).replace("R$", "").replace(".", "").replace(",", ".").strip()

    try:
        return float(v)
    except ValueError:
        return 0.0


def formatar_brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def normalizar_texto(valor):
    if pd.isna(valor):
        return ""
    txt = str(valor).strip().upper()
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return txt


def parse_data_serie(series: pd.Series) -> pd.Series:
    """
    Parse robusto para datas brasileiras.
    Prioriza formatos explícitos antes de cair no parser genérico.
    """
    if series is None:
        return pd.Series(dtype="datetime64[ns]")

    raw = series.astype("string").str.strip()
    parsed = pd.Series(pd.NaT, index=series.index)

    formatos = [
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d-%m-%Y",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
    ]

    faltando = raw.notna() & (raw != "")

    for fmt in formatos:
        if not faltando.any():
            break
        tentativa = pd.to_datetime(raw[faltando], format=fmt, errors="coerce")
        ok = tentativa.notna()
        if ok.any():
            parsed.loc[tentativa[ok].index] = tentativa[ok]
        faltando = parsed.isna() & raw.notna() & (raw != "")

    if faltando.any():
        raw_limpo = (
            raw[faltando]
            .str.replace("T", " ", regex=False)
            .str.replace("Z", "", regex=False)
            .str.replace(r"\.\d+$", "", regex=True)
        )
        tentativa = pd.to_datetime(raw_limpo, errors="coerce", dayfirst=True)
        ok = tentativa.notna()
        if ok.any():
            parsed.loc[tentativa[ok].index] = tentativa[ok]

    faltando = parsed.isna() & raw.notna() & (raw != "")
    if faltando.any():
        numericos = pd.to_numeric(
            raw[faltando].str.replace(",", ".", regex=False),
            errors="coerce"
        )
        ok = numericos.notna()
        if ok.any():
            datas_excel = pd.to_datetime(
                numericos[ok],
                unit="D",
                origin="1899-12-30",
                errors="coerce"
            )
            parsed.loc[datas_excel.index] = datas_excel

    return pd.to_datetime(parsed, errors="coerce").dt.normalize()


def parse_data_coluna(df: pd.DataFrame, coluna: str) -> pd.Series:
    if coluna not in df.columns:
        return pd.Series(pd.NaT, index=df.index)
    return parse_data_serie(df[coluna])


def normalizar_codigo(valor, tamanho_min=6):
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
    try:
        codigo = normalizar_codigo(row.get("Código", ""))
        cor3 = extrair_cor3(row.get("Cor", ""))

        if codigo and cor3:
            return f"{BASE_IMG_URL}{codigo}{cor3}1.jpg"
    except Exception:
        pass

    return ""


def primeiro_valor_nao_vazio(series):
    for v in series:
        if pd.notna(v) and str(v).strip() != "":
            return v
    return ""


def obter_delta_info(atual, anterior):
    atual = float(atual or 0)
    anterior = float(anterior or 0)

    if anterior == 0:
        if atual == 0:
            return "0,0%", "neutral"
        return "Novo", "up"

    delta = ((atual - anterior) / abs(anterior)) * 100

    if delta > 0:
        classe = "up"
    elif delta < 0:
        classe = "down"
    else:
        classe = "neutral"

    return f"{delta:+.1f}%".replace(".", ","), classe


def calcular_delta_percentual(atual, anterior):
    texto, _ = obter_delta_info(atual, anterior)
    return texto


def formatar_chip_delta(atual, anterior):
    texto, classe = obter_delta_info(atual, anterior)
    mapa = {
        "up": "#15803d",
        "down": "#dc2626",
        "neutral": "#475569",
    }
    fundo = {
        "up": "rgba(34,197,94,0.12)",
        "down": "rgba(239,68,68,0.12)",
        "neutral": "rgba(100,116,139,0.12)",
    }
    return f"""
    <span style="
        display:inline-block;
        padding:4px 10px;
        border-radius:999px;
        font-size:0.85rem;
        color:{mapa[classe]};
        background:{fundo[classe]};
        white-space:nowrap;
    ">
        {texto}
    </span>
    """


def periodo_anterior(data_ini, data_fim):
    data_ini = pd.Timestamp(data_ini).normalize()
    data_fim = pd.Timestamp(data_fim).normalize()

    dias_periodo = (data_fim - data_ini).days + 1
    fim_anterior = data_ini - pd.Timedelta(days=1)
    ini_anterior = fim_anterior - pd.Timedelta(days=dias_periodo - 1)

    return ini_anterior.normalize(), fim_anterior.normalize(), dias_periodo


def filtrar_intervalo(df_base: pd.DataFrame, coluna_data: str, ini, fim) -> pd.DataFrame:
    if coluna_data not in df_base.columns:
        return df_base.iloc[0:0].copy()

    ini = pd.Timestamp(ini).normalize()
    fim = pd.Timestamp(fim).normalize()

    return df_base[
        (df_base[coluna_data] >= ini) &
        (df_base[coluna_data] <= fim)
    ].copy()


def calcular_status_e_projecao(data_ini, data_fim, total_atual):
    if data_ini is None or data_fim is None:
        return {"status": "sem_periodo"}

    data_ini = pd.Timestamp(data_ini).normalize()
    data_fim = pd.Timestamp(data_fim).normalize()

    if data_ini.year != data_fim.year or data_ini.month != data_fim.month:
        return {"status": "multiplos_meses"}

    hoje_sp = pd.Timestamp(datetime.now(ZoneInfo("America/Sao_Paulo")).date())
    ontem_sp = hoje_sp - pd.Timedelta(days=1)

    inicio_mes_filtro = data_ini.replace(day=1)
    fim_mes_filtro = inicio_mes_filtro + pd.offsets.MonthEnd(1)
    inicio_mes_atual = hoje_sp.replace(day=1)

    if inicio_mes_filtro < inicio_mes_atual:
        return {"status": "finalizado"}

    if inicio_mes_filtro > inicio_mes_atual:
        return {"status": "futuro"}

    if data_ini != inicio_mes_filtro:
        return {"status": "intervalo_parcial"}

    if data_fim < ontem_sp:
        return {"status": "intervalo_parcial"}

    dias_passados = ontem_sp.day
    dias_mes = fim_mes_filtro.day
    dias_restantes = dias_mes - dias_passados

    if dias_passados <= 0:
        return {"status": "sem_base"}

    projecao = (total_atual / dias_passados) * dias_mes

    return {
        "status": "em_andamento",
        "dias_passados": dias_passados,
        "dias_restantes": dias_restantes,
        "dias_mes": dias_mes,
        "projecao": projecao,
    }


def aplicar_filtros_dimensionais(df_base, marketplaces_sel, marcas_sel, categorias_sel, incluir_devolucao):
    if marketplaces_sel:
        mask_marketplace = df_base["Grupo de Marketplace"].isin(marketplaces_sel)
    else:
        mask_marketplace = pd.Series(False, index=df_base.index)

    if incluir_devolucao:
        mask_marketplace = mask_marketplace | df_base["Eh_Devolucao"]
    else:
        mask_marketplace = mask_marketplace & (~df_base["Eh_Devolucao"])

    df_out = df_base[mask_marketplace].copy()

    if marcas_sel is not None:
        df_out = df_out[df_out["Marca"].isin(marcas_sel)]

    if categorias_sel is not None:
        df_out = df_out[df_out["Categoria"].isin(categorias_sel)]

    return df_out


def montar_df_comparativo(df_base, coluna_data, coluna_valor, data_ini, data_fim):
    data_ini = pd.Timestamp(data_ini).normalize()
    data_fim = pd.Timestamp(data_fim).normalize()

    ini_ant, fim_ant, dias_periodo = periodo_anterior(data_ini, data_fim)

    base_valida = df_base[df_base[coluna_data].notna()].copy()

    datas_atuais = pd.date_range(data_ini, data_fim, freq="D")
    datas_anteriores = pd.date_range(ini_ant, fim_ant, freq="D")

    atual = (
        filtrar_intervalo(base_valida, coluna_data, data_ini, data_fim)
        .groupby(coluna_data, as_index=True)[coluna_valor]
        .sum()
        .reindex(datas_atuais, fill_value=0)
        .reset_index()
    )
    atual.columns = ["Data_Original", "Valor"]
    atual["Posicao_Dia"] = range(1, len(atual) + 1)
    atual["Serie"] = "Período Atual"

    anterior = (
        filtrar_intervalo(base_valida, coluna_data, ini_ant, fim_ant)
        .groupby(coluna_data, as_index=True)[coluna_valor]
        .sum()
        .reindex(datas_anteriores, fill_value=0)
        .reset_index()
    )
    anterior.columns = ["Data_Original", "Valor"]
    anterior["Posicao_Dia"] = range(1, len(anterior) + 1)
    anterior["Serie"] = "Período Anterior"

    df_cmp = pd.concat([atual, anterior], ignore_index=True)
    df_cmp["Posicao_Label"] = df_cmp["Posicao_Dia"].apply(lambda x: f"D{x:02d}")

    return df_cmp, ini_ant, fim_ant, dias_periodo


# ──────────────────────────────────────────────
# 5. CARGA E TRATAMENTO DOS DADOS
# ──────────────────────────────────────────────
try:
    df = conn.read(spreadsheet=url_planilha, ttl="0")
    df.columns = [str(c).strip() for c in df.columns]

    for col_orig, col_num in [
        ("Receita", "Receita_Num"),
        ("Liquido", "Liquido_Num"),
        ("Custo medio", "Custo_Num"),
    ]:
        df[col_num] = df[col_orig].apply(limpar_moeda) if col_orig in df.columns else 0.0

    df["Qtd_Num"] = pd.to_numeric(df.get("Quantidade vendida"), errors="coerce").fillna(0)

    df["Data_Emissao_Filtro"] = parse_data_coluna(df, "Data emissao")
    df["Data_Venda_Pura"] = parse_data_coluna(df, "Data da Venda")

    # Para gráfico comparativo
    df["Data_Venda_Analise"] = df["Data_Venda_Pura"].fillna(df["Data_Emissao_Filtro"])

    df["Eh_Devolucao"] = (
        df["Grupo de Marketplace"]
        .apply(normalizar_texto)
        .str.contains("DEVOLUCAO", na=False)
    )

    df["img_url"] = df.apply(build_img_url, axis=1)

    colunas_necessarias = ["Grupo de Marketplace", "Tipo pedido", "Data emissao"]
    if not all(col in df.columns for col in colunas_necessarias):
        st.error("Colunas obrigatórias não encontradas. Verifique a planilha.")
        st.write("Colunas detectadas:", df.columns.tolist())
        st.stop()

    # ──────────────────────────────────────────
    # 6. FILTROS LATERAIS
    # ──────────────────────────────────────────
    st.sidebar.header("Filtros")

    mkt_lista = sorted(
        df.loc[~df["Eh_Devolucao"], "Grupo de Marketplace"].dropna().unique()
    )
    mkt_sel = st.sidebar.multiselect("Marketplace", options=mkt_lista, default=mkt_lista)

    incluir_devolucao = st.sidebar.toggle("Incluir Devolução", value=False)

    if "Marca" in df.columns:
        marca_lista = sorted(df["Marca"].dropna().unique())
        marca_sel = st.sidebar.multiselect("Marca", options=marca_lista, default=marca_lista)
    else:
        marca_sel = None

    if "Categoria" in df.columns:
        categoria_lista = sorted(df["Categoria"].dropna().unique())
        categoria_sel = st.sidebar.multiselect("Categoria", options=categoria_lista, default=categoria_lista)
    else:
        categoria_sel = None

    datas_validas = df["Data_Emissao_Filtro"].dropna()

    hoje_sp = pd.Timestamp(datetime.now(ZoneInfo("America/Sao_Paulo")).date())
    ontem_sp = hoje_sp - pd.Timedelta(days=1)
    inicio_mes_atual = hoje_sp.replace(day=1)

    if not datas_validas.empty:
        data_min = datas_validas.min().date()
        data_max = datas_validas.max().date()

        default_ini = max(data_min, inicio_mes_atual.date())
        default_fim = min(data_max, ontem_sp.date())

        if default_ini > default_fim:
            default_ini = data_min
            default_fim = data_max

        periodo = st.sidebar.date_input(
            "Período de Venda",
            value=(default_ini, default_fim),
            min_value=data_min,
            max_value=data_max,
        )

        if isinstance(periodo, (list, tuple)) and len(periodo) == 2:
            data_ini = pd.Timestamp(periodo[0]).normalize()
            data_fim = pd.Timestamp(periodo[1]).normalize()
        else:
            data_ini = pd.Timestamp(default_ini).normalize()
            data_fim = pd.Timestamp(default_fim).normalize()
    else:
        data_ini, data_fim = None, None

    # ──────────────────────────────────────────
    # 7. BASE FILTRADA
    # ──────────────────────────────────────────
    df_dim = aplicar_filtros_dimensionais(
        df_base=df,
        marketplaces_sel=mkt_sel,
        marcas_sel=marca_sel,
        categorias_sel=categoria_sel,
        incluir_devolucao=incluir_devolucao,
    )

    # Resumo, projeção, ranking e detalhamento por Data emissao
    if data_ini is not None and data_fim is not None:
        df_f = filtrar_intervalo(df_dim, "Data_Emissao_Filtro", data_ini, data_fim)
        ini_ant, fim_ant, dias_periodo = periodo_anterior(data_ini, data_fim)
        df_prev = filtrar_intervalo(df_dim, "Data_Emissao_Filtro", ini_ant, fim_ant)
    else:
        df_f = df_dim.copy()
        df_prev = df_dim.iloc[0:0].copy()
        ini_ant = fim_ant = None
        dias_periodo = 0

    # Base exclusiva do gráfico por Data da Venda
    if data_ini is not None and data_fim is not None:
        df_grafico_base = df_dim.copy()
    else:
        df_grafico_base = df_dim.iloc[0:0].copy()

    # ──────────────────────────────────────────
    # 8. CABEÇALHO
    # ──────────────────────────────────────────
    st.title("Dashboard de Performance de Vendas")
    st.caption(
        f"{len(df_f):,} linhas no detalhamento filtradas por Data emissao | "
        f"Gráfico comparativo calculado por Data da Venda com fallback para Data emissao"
    )

    # ──────────────────────────────────────────
    # 9. CSS
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
    # 10. MÉTRICAS PRINCIPAIS
    # ──────────────────────────────────────────
    receita_total = df_f["Receita_Num"].sum()
    liquido_total = df_f["Liquido_Num"].sum()
    custo_medio = df_f["Custo_Num"].mean() if len(df_f) > 0 else 0.0
    qtd_total = int(df_f["Qtd_Num"].sum())
    total_pedidos = len(df_f)

    receita_anterior = df_prev["Receita_Num"].sum()
    liquido_anterior = df_prev["Liquido_Num"].sum()
    custo_anterior = df_prev["Custo_Num"].mean() if len(df_prev) > 0 else 0.0
    qtd_anterior = int(df_prev["Qtd_Num"].sum())
    pedidos_anterior = len(df_prev)

    info_proj = calcular_status_e_projecao(
        data_ini=data_ini,
        data_fim=data_fim,
        total_atual=receita_total
    )

    linha1 = st.columns(3)
    linha2 = st.columns(3)

    linha1[0].metric(
        "Receita Total",
        formatar_brl(receita_total),
        calcular_delta_percentual(receita_total, receita_anterior)
    )
    linha1[1].metric(
        "Líquido Total",
        formatar_brl(liquido_total),
        calcular_delta_percentual(liquido_total, liquido_anterior)
    )
    linha1[2].metric(
        "Custo Médio",
        formatar_brl(custo_medio),
        calcular_delta_percentual(custo_medio, custo_anterior)
    )

    linha2[0].metric(
        "Itens Vendidos",
        f"{qtd_total:,}",
        calcular_delta_percentual(qtd_total, qtd_anterior)
    )
    linha2[1].metric(
        "Total de Pedidos",
        f"{total_pedidos:,}",
        calcular_delta_percentual(total_pedidos, pedidos_anterior)
    )

    if info_proj["status"] == "em_andamento":
        linha2[2].metric("Projeção do Mês", formatar_brl(info_proj["projecao"]))
        st.caption(
            f"Período anterior para comparação: {ini_ant.strftime('%d/%m/%Y')} até {fim_ant.strftime('%d/%m/%Y')} | "
            f"Projeção mensal: {info_proj['dias_passados']} dias passados, "
            f"{info_proj['dias_restantes']} restantes, total de {info_proj['dias_mes']} dias."
        )
    elif info_proj["status"] == "finalizado":
        linha2[2].metric("Projeção do Mês", "Mês finalizado")
        st.caption(
            f"Período anterior para comparação: {ini_ant.strftime('%d/%m/%Y')} até {fim_ant.strftime('%d/%m/%Y')}"
        )
    elif info_proj["status"] == "intervalo_parcial":
        linha2[2].metric("Projeção do Mês", "N/D")
        st.caption(
            f"Período anterior para comparação: {ini_ant.strftime('%d/%m/%Y')} até {fim_ant.strftime('%d/%m/%Y')} | "
            f"Para projetar o mês atual, o filtro precisa cobrir o mês desde o dia 1 até ontem."
        )
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
    # 11. GRÁFICO: VENDAS POR DIA COM COMPARATIVO
    # ──────────────────────────────────────────
    st.subheader("Vendas por Dia com Comparativo do Período Anterior")

    if (
        data_ini is not None and
        data_fim is not None and
        not df_grafico_base.empty and
        "Data_Venda_Analise" in df_grafico_base.columns and
        df_grafico_base["Data_Venda_Analise"].notna().any()
    ):
        df_cmp, ini_ant_chart, fim_ant_chart, dias_periodo_chart = montar_df_comparativo(
            df_base=df_grafico_base,
            coluna_data="Data_Venda_Analise",
            coluna_valor="Receita_Num",
            data_ini=data_ini,
            data_fim=data_fim,
        )

        chart = (
            alt.Chart(df_cmp)
            .mark_line(point=True, strokeWidth=3)
            .encode(
                x=alt.X("Posicao_Label:O", title="Dia dentro do período"),
                y=alt.Y("Valor:Q", title="Receita (R$)"),
                color=alt.Color("Serie:N", title="Série"),
                tooltip=[
                    alt.Tooltip("Serie:N", title="Série"),
                    alt.Tooltip("Posicao_Dia:Q", title="Posição"),
                    alt.Tooltip("Data_Original:T", title="Data original", format="%d/%m/%Y"),
                    alt.Tooltip("Valor:Q", title="Receita", format=",.2f"),
                ],
            )
            .properties(height=320)
        )

        st.altair_chart(chart, use_container_width=True)

        st.caption(
            f"Período atual: {data_ini.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')} | "
            f"Período anterior: {ini_ant_chart.strftime('%d/%m/%Y')} até {fim_ant_chart.strftime('%d/%m/%Y')} | "
            f"Comparação alinhada pelo dia dentro do período"
        )
    else:
        st.info("Sem dados de Data da Venda disponíveis para o período selecionado.")

    st.divider()

    # ──────────────────────────────────────────
    # 12. GRÁFICO: MARKETPLACE × TIPO PEDIDO
    # ──────────────────────────────────────────
    st.subheader("Faturamento por Marketplace e Tipo de Pedido")

    if not df_f.empty:
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
    else:
        st.info("Sem dados para exibir o faturamento por marketplace e tipo de pedido.")

    st.divider()

    # ──────────────────────────────────────────
    # 13. RANKING DE PRODUTOS COM KPI DE PERÍODO
    # ──────────────────────────────────────────
    st.subheader("Ranking de Produtos")

    col_produto = "Produto" if "Produto" in df_f.columns else None

    if col_produto and not df_f.empty:
        tab_receita, tab_qtd = st.tabs(["Por Receita", "Por Quantidade Vendida"])

        df_rank_atual = (
            df_f.groupby(col_produto)
            .agg(
                Receita=("Receita_Num", "sum"),
                Quantidade=("Qtd_Num", "sum"),
                img_url=("img_url", primeiro_valor_nao_vazio),
            )
            .reset_index()
        )

        df_rank_anterior = (
            df_prev.groupby(col_produto)
            .agg(
                Receita_Anterior=("Receita_Num", "sum"),
                Quantidade_Anterior=("Qtd_Num", "sum"),
            )
            .reset_index()
        )

        df_rank_base = df_rank_atual.merge(
            df_rank_anterior,
            on=col_produto,
            how="left"
        )

        df_rank_base["Receita_Anterior"] = df_rank_base["Receita_Anterior"].fillna(0)
        df_rank_base["Quantidade_Anterior"] = df_rank_base["Quantidade_Anterior"].fillna(0)

        TOP_N = st.slider("Número de produtos no ranking", 5, 30, 10, key="top_n")

        def render_ranking(df_rank: pd.DataFrame, col_valor: str, col_anterior: str, fmt_fn=None):
            df_top = df_rank.nlargest(TOP_N, col_valor).reset_index(drop=True)
            df_top.index += 1

            for pos, row in df_top.iterrows():
                cols = st.columns([0.7, 1.3, 6, 2.4])

                cols[0].markdown(str(pos))

                if row["img_url"]:
                    cols[1].image(row["img_url"], width=60)
                else:
                    cols[1].markdown("—")

                cols[2].markdown(str(row[col_produto]))

                valor = row[col_valor]
                valor_ant = row[col_anterior]
                texto = fmt_fn(valor) if fmt_fn else f"{int(valor):,}"
                chip = formatar_chip_delta(valor, valor_ant)

                cols[3].markdown(
                    f"""
                    <div style="display:flex; flex-direction:column; gap:8px; align-items:flex-start;">
                        <div style="font-size:1.05rem;">{texto}</div>
                        <div>{chip}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

        with tab_receita:
            st.caption(
                f"Comparação de receita contra o período anterior: "
                f"{ini_ant.strftime('%d/%m/%Y')} até {fim_ant.strftime('%d/%m/%Y')}"
                if ini_ant is not None and fim_ant is not None else
                "Comparação de receita contra o período anterior"
            )
            render_ranking(df_rank_base, "Receita", "Receita_Anterior", formatar_brl)

        with tab_qtd:
            st.caption(
                f"Comparação de quantidade contra o período anterior: "
                f"{ini_ant.strftime('%d/%m/%Y')} até {fim_ant.strftime('%d/%m/%Y')}"
                if ini_ant is not None and fim_ant is not None else
                "Comparação de quantidade contra o período anterior"
            )
            render_ranking(df_rank_base, "Quantidade", "Quantidade_Anterior")

    else:
        st.info("Sem dados de produtos para montar o ranking.")

    st.divider()

    # ──────────────────────────────────────────
    # 14. TABELA DETALHADA
    # ──────────────────────────────────────────
    with st.expander("Ver Detalhamento dos Pedidos"):
        colunas_base = [
            "Data emissao",
            "Data da Venda",
            "Grupo de Marketplace",
            "Tipo pedido",
            "Categoria",
            "Marca",
            "Produto",
            "Receita",
            "Liquido",
            "Custo medio",
            "Quantidade vendida",
            "Status do pedido",
        ]

        colunas_exibir = [c for c in colunas_base if c in df_f.columns]
        st.dataframe(df_f[colunas_exibir], use_container_width=True)

except Exception as e:
    st.error(f"Não foi possível carregar os dados: {e}")
    st.exception(e)
