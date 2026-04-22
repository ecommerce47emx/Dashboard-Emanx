import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
import html

import streamlit as st
import pandas as pd
import altair as alt
from streamlit_gsheets import GSheetsConnection

# ──────────────────────────────────────────────
# 1. CONFIGURAÇÃO DA PÁGINA
# ──────────────────────────────────────────────
st.set_page_config(page_title="EmanxTelecom - Dashboard de Vendas", layout="wide")

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
def formatar_int(valor):
    try:
        return f"{int(round(valor)):,}".replace(",", ".")
    except Exception:
        return "0"


def montar_ranking_produto(df_atual, df_anterior):
    if "Produto" not in df_atual.columns or df_atual.empty:
        return pd.DataFrame()

    base_atual = df_atual[
        df_atual["Produto"].notna() &
        (df_atual["Produto"].astype(str).str.strip() != "")
    ].copy()

    base_anterior = df_anterior[
        df_anterior["Produto"].notna() &
        (df_anterior["Produto"].astype(str).str.strip() != "")
    ].copy()

    rank_atual = (
        base_atual.groupby("Produto", as_index=False)
        .agg(
            Receita=("Receita_Num", "sum"),
            Quantidade=("Qtd_Num", "sum"),
            img_url=("img_url", primeiro_valor_nao_vazio),
        )
    )

    rank_anterior = (
        base_anterior.groupby("Produto", as_index=False)
        .agg(
            Receita_Anterior=("Receita_Num", "sum"),
            Quantidade_Anterior=("Qtd_Num", "sum"),
        )
    )

    df_rank = rank_atual.merge(rank_anterior, on="Produto", how="left")
    df_rank["Receita_Anterior"] = df_rank["Receita_Anterior"].fillna(0)
    df_rank["Quantidade_Anterior"] = df_rank["Quantidade_Anterior"].fillna(0)

    return df_rank


def montar_ranking_grupo(df_atual, df_anterior, campo_grupo, metrica_ordenacao):
    if campo_grupo not in df_atual.columns or df_atual.empty:
        return pd.DataFrame()

    base_atual = df_atual[
        df_atual[campo_grupo].notna() &
        (df_atual[campo_grupo].astype(str).str.strip() != "")
    ].copy()

    base_anterior = df_anterior[
        df_anterior[campo_grupo].notna() &
        (df_anterior[campo_grupo].astype(str).str.strip() != "")
    ].copy()

    if base_atual.empty:
        return pd.DataFrame()

    rank_atual = (
        base_atual.groupby(campo_grupo, as_index=False)
        .agg(
            Receita=("Receita_Num", "sum"),
            Quantidade=("Qtd_Num", "sum"),
        )
    )

    rank_anterior = (
        base_anterior.groupby(campo_grupo, as_index=False)
        .agg(
            Receita_Anterior=("Receita_Num", "sum"),
            Quantidade_Anterior=("Qtd_Num", "sum"),
        )
    )

    df_rank = rank_atual.merge(rank_anterior, on=campo_grupo, how="left")
    df_rank["Receita_Anterior"] = df_rank["Receita_Anterior"].fillna(0)
    df_rank["Quantidade_Anterior"] = df_rank["Quantidade_Anterior"].fillna(0)

    if "Produto" in base_atual.columns:
        destaque = (
            base_atual.groupby([campo_grupo, "Produto"], as_index=False)
            .agg(
                Receita=("Receita_Num", "sum"),
                Quantidade=("Qtd_Num", "sum"),
                img_url=("img_url", primeiro_valor_nao_vazio),
            )
            .sort_values(
                by=[campo_grupo, metrica_ordenacao, "Receita", "Quantidade"],
                ascending=[True, False, False, False]
            )
            .drop_duplicates(subset=[campo_grupo], keep="first")
            .rename(
                columns={
                    "Produto": "Produto_Destaque",
                    "img_url": "img_url_destaque",
                }
            )[[campo_grupo, "Produto_Destaque", "img_url_destaque"]]
        )

        df_rank = df_rank.merge(destaque, on=campo_grupo, how="left")
    else:
        df_rank["Produto_Destaque"] = ""
        df_rank["img_url_destaque"] = ""

    return df_rank


def render_ranking_produto(df_rank, metrica_ordenacao, top_n):
    if df_rank.empty:
        st.info("Sem dados para montar este ranking.")
        return

    coluna_anterior = "Receita_Anterior" if metrica_ordenacao == "Receita" else "Quantidade_Anterior"

    df_top = (
        df_rank.sort_values(
            by=[metrica_ordenacao, "Receita", "Quantidade"],
            ascending=[False, False, False]
        )
        .head(top_n)
        .reset_index(drop=True)
    )

    for i, row in df_top.iterrows():
        pos = i + 1
        produto = html.escape(str(row["Produto"]))
        chip = formatar_chip_delta(row[metrica_ordenacao], row[coluna_anterior])

        cols = st.columns([0.7, 1.3, 6.0, 2.7])

        cols[0].markdown(str(pos))

        if row.get("img_url"):
            cols[1].image(row["img_url"], width=60)
        else:
            cols[1].markdown("—")

        cols[2].markdown(produto)

        cols[3].markdown(
            f"""
            <div style="display:flex; flex-direction:column; gap:6px; align-items:flex-start;">
                <div>Receita: {formatar_brl(row["Receita"])}</div>
                <div>Quantidade: {formatar_int(row["Quantidade"])}</div>
                <div>{chip}</div>
            </div>
            """,
            unsafe_allow_html=True
        )


def render_ranking_grupo(df_rank, campo_grupo, metrica_ordenacao, top_n):
    if df_rank.empty:
        st.info("Sem dados para montar este ranking.")
        return

    coluna_anterior = "Receita_Anterior" if metrica_ordenacao == "Receita" else "Quantidade_Anterior"

    df_top = (
        df_rank.sort_values(
            by=[metrica_ordenacao, "Receita", "Quantidade"],
            ascending=[False, False, False]
        )
        .head(top_n)
        .reset_index(drop=True)
    )

    for i, row in df_top.iterrows():
        pos = i + 1
        nome_grupo = html.escape(str(row[campo_grupo]))
        produto_destaque = html.escape(str(row.get("Produto_Destaque", "") or ""))
        chip = formatar_chip_delta(row[metrica_ordenacao], row[coluna_anterior])

        cols = st.columns([0.7, 1.3, 6.0, 2.9])

        cols[0].markdown(str(pos))

        if row.get("img_url_destaque"):
            cols[1].image(row["img_url_destaque"], width=60)
        else:
            cols[1].markdown("—")

        if produto_destaque:
            cols[2].markdown(
                f"""
                <div style="display:flex; flex-direction:column; gap:6px;">
                    <div style="font-size:1.08rem;">{nome_grupo}</div>
                    <div style="font-size:0.9rem; color:#64748b;">
                        Produto destaque: {produto_destaque}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            cols[2].markdown(nome_grupo)

        cols[3].markdown(
            f"""
            <div style="display:flex; flex-direction:column; gap:6px; align-items:flex-start;">
                <div>Receita: {formatar_brl(row["Receita"])}</div>
                <div>Quantidade: {formatar_int(row["Quantidade"])}</div>
                <div>{chip}</div>
            </div>
            """,
            unsafe_allow_html=True
        )


def limpar_moeda(valor):
    """
    Converte moeda BRL para float, incluindo casos de devolução:
    - R$ -123,45
    - -R$ 123,45
    - (123,45)
    - 123,45-
    - espaços extras
    """
    if pd.isna(valor):
        return 0.0

    s = str(valor).strip()

    if s == "":
        return 0.0

    negativo = False

    if "(" in s and ")" in s:
        negativo = True

    s = s.replace("R$", "").replace("r$", "").strip()

    if s.startswith("-"):
        negativo = True
    if s.endswith("-"):
        negativo = True

    s = s.replace("(", "").replace(")", "")
    s = s.replace("-", "")
    s = s.replace(" ", "")

    # remove separador de milhar e normaliza decimal
    s = s.replace(".", "").replace(",", ".")

    # mantém apenas dígitos e ponto
    s = re.sub(r"[^0-9.]", "", s)

    if s == "":
        return 0.0

    try:
        numero = float(s)
        return -numero if negativo else numero
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
    Parse estrito para datas.
    Prioriza formato brasileiro.
    Também suporta ISO e serial do Excel.
    """
    if series is None:
        return pd.Series(dtype="datetime64[ns]")

    s = series.copy()

    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, errors="coerce").dt.normalize()

    raw = s.astype("string").str.strip()
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")

    invalidas = raw.isna() | (raw == "") | (raw.str.lower() == "nan")

    faltando = ~invalidas

    formatos_br = [
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
    ]

    for fmt in formatos_br:
        if not faltando.any():
            break
        tentativa = pd.to_datetime(raw[faltando], format=fmt, errors="coerce")
        ok = tentativa.notna()
        if ok.any():
            parsed.loc[tentativa[ok].index] = tentativa[ok]
        faltando = parsed.isna() & (~invalidas)

    formatos_iso = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ]

    for fmt in formatos_iso:
        if not faltando.any():
            break
        tentativa = pd.to_datetime(raw[faltando], format=fmt, errors="coerce")
        ok = tentativa.notna()
        if ok.any():
            parsed.loc[tentativa[ok].index] = tentativa[ok]
        faltando = parsed.isna() & (~invalidas)

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

    faltando = parsed.isna() & (~invalidas)
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

def ao_mudar_periodo_manual():
    st.session_state["periodo_rapido"] = "Personalizado"
    
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


def periodo_anterior(data_ini, data_fim, modo_periodo="Personalizado"):
    data_ini = pd.Timestamp(data_ini).normalize()
    data_fim = pd.Timestamp(data_fim).normalize()

    dias_periodo = (data_fim - data_ini).days + 1

    # Para atalhos rápidos, mantém comparação por janela imediatamente anterior
    if modo_periodo in ["Últimos 7 dias", "Últimos 15 dias", "Últimos 30 dias"]:
        fim_anterior = data_ini - pd.Timedelta(days=1)
        ini_anterior = fim_anterior - pd.Timedelta(days=dias_periodo - 1)
        return ini_anterior.normalize(), fim_anterior.normalize(), dias_periodo

    # Para períodos dentro de um único mês, compara com os mesmos dias do mês anterior
    if data_ini.year == data_fim.year and data_ini.month == data_fim.month:
        primeiro_dia_mes_atual = data_ini.replace(day=1)
        ultimo_dia_mes_anterior = primeiro_dia_mes_atual - pd.Timedelta(days=1)
        primeiro_dia_mes_anterior = ultimo_dia_mes_anterior.replace(day=1)

        dia_inicio_anterior = min(data_ini.day, ultimo_dia_mes_anterior.day)
        dia_fim_anterior = min(data_fim.day, ultimo_dia_mes_anterior.day)

        ini_anterior = primeiro_dia_mes_anterior + pd.Timedelta(days=dia_inicio_anterior - 1)
        fim_anterior = primeiro_dia_mes_anterior + pd.Timedelta(days=dia_fim_anterior - 1)

        dias_comparacao = (fim_anterior - ini_anterior).days + 1
        return ini_anterior.normalize(), fim_anterior.normalize(), dias_comparacao

    # Fallback para períodos personalizados maiores ou cruzando meses
    fim_anterior = data_ini - pd.Timedelta(days=1)
    ini_anterior = fim_anterior - pd.Timedelta(days=dias_periodo - 1)

    return ini_anterior.normalize(), fim_anterior.normalize(), dias_periodo

def criar_grafico_comparativo(df_cmp: pd.DataFrame):
    df_plot = df_cmp.copy()

    ordem_series = ["Período Atual", "Período Anterior"]
    df_plot["Serie"] = pd.Categorical(
        df_plot["Serie"],
        categories=ordem_series,
        ordered=True
    )
    df_plot["Ordem_Serie"] = df_plot["Serie"].cat.codes

    return (
        alt.Chart(df_plot)
        .mark_line(point=True, strokeWidth=3)
        .encode(
            x=alt.X("Posicao_Label:O", title="Dia dentro do período"),
            y=alt.Y("Valor:Q", title="Receita (R$)"),
            color=alt.Color(
                "Serie:N",
                title="Série",
                scale=alt.Scale(
                    domain=ordem_series,
                    range=["#4aa065", "#96cfa8"]
                ),
                legend=alt.Legend(
                    orient="top",
                    direction="horizontal"
                )
            ),
            order=alt.Order("Ordem_Serie:Q", sort="ascending"),
            detail="Serie:N",
            tooltip=[
                alt.Tooltip("Serie:N", title="Série"),
                alt.Tooltip("Posicao_Dia:Q", title="Posição"),
                alt.Tooltip("Data_Original:T", title="Data original", format="%d/%m/%Y"),
                alt.Tooltip("Valor:Q", title="Receita", format=",.2f"),
            ],
        )
        .properties(height=320)
    )

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


# ── CHANGE 1: empty filter = select all ──────────────────────────────────────
def aplicar_filtros_dimensionais(
    df_base,
    marketplaces_sel,
    marcas_sel,
    categorias_sel,
    fornecedores_sel,
    incluir_devolucao
):
    """
    Regras:
    - toggle desligado: traz somente não devolução
    - toggle ligado: traz somente devolução
    - marketplace vazio: equivale a todos
    - quando toggle ligado, ignora filtro de marketplace
    """
    if incluir_devolucao:
        df_out = df_base[df_base["Eh_Devolucao"]].copy()
    else:
        df_out = df_base[~df_base["Eh_Devolucao"]].copy()

        if marketplaces_sel:
            df_out = df_out[df_out["Grupo de Marketplace"].isin(marketplaces_sel)]

    if marcas_sel:
        df_out = df_out[df_out["Marca"].isin(marcas_sel)]

    if categorias_sel:
        df_out = df_out[df_out["Categoria"].isin(categorias_sel)]

    if fornecedores_sel:
        df_out = df_out[df_out["Fornecedor"].isin(fornecedores_sel)]

    return df_out

def montar_df_comparativo(df_base, coluna_data, coluna_valor, data_ini, data_fim, modo_periodo="Personalizado"):
    data_ini = pd.Timestamp(data_ini).normalize()
    data_fim = pd.Timestamp(data_fim).normalize()

    ini_ant, fim_ant, dias_periodo = periodo_anterior(data_ini, data_fim, modo_periodo)

    base_valida = df_base[df_base[coluna_data].notna()].copy()

    atual_base = filtrar_intervalo(base_valida, coluna_data, data_ini, data_fim)
    anterior_base = filtrar_intervalo(base_valida, coluna_data, ini_ant, fim_ant)

    datas_atuais = pd.date_range(data_ini, data_fim, freq="D")
    datas_anteriores = pd.date_range(ini_ant, fim_ant, freq="D")

    atual = (
        atual_base.groupby(coluna_data, as_index=True)[coluna_valor]
        .sum()
        .reindex(datas_atuais, fill_value=0)
        .rename("Valor")
        .reset_index()
        .rename(columns={"index": "Data_Original"})
    )
    atual["Posicao_Dia"] = range(1, len(atual) + 1)
    atual["Posicao_Label"] = atual["Posicao_Dia"].apply(lambda x: f"D{x:02d}")
    atual["Serie"] = "Período Atual"

    anterior = (
        anterior_base.groupby(coluna_data, as_index=True)[coluna_valor]
        .sum()
        .reindex(datas_anteriores, fill_value=0)
        .rename("Valor")
        .reset_index()
        .rename(columns={"index": "Data_Original"})
    )
    anterior["Posicao_Dia"] = range(1, len(anterior) + 1)
    anterior["Posicao_Label"] = anterior["Posicao_Dia"].apply(lambda x: f"D{x:02d}")
    anterior["Serie"] = "Período Anterior"

    df_cmp = pd.concat([atual, anterior], ignore_index=True)

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

    df["Data_Grafico"] = df["Data_Venda_Pura"].where(
        df["Data_Venda_Pura"].notna(),
        df["Data_Emissao_Filtro"]
    )

    df["Dia_Grafico"] = pd.to_datetime(df["Data_Grafico"], errors="coerce").dt.normalize()

    df["Eh_Devolucao"] = (
        df["Grupo de Marketplace"]
        .apply(normalizar_texto)
        .str.contains("DEVOLUCAO", na=False)
    )

    # ── CHANGE 4: devoluções exibidas em valor absoluto ───────────────────────
    for col_num in ["Receita_Num", "Liquido_Num", "Custo_Num", "Qtd_Num"]:
        df.loc[df["Eh_Devolucao"], col_num] = df.loc[df["Eh_Devolucao"], col_num].abs()

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
    # CHANGE 1: default vazio = todos
    mkt_sel = st.sidebar.multiselect(
        "Marketplace",
        options=mkt_lista,
        default=[],
        placeholder="Todos os marketplaces",
    )

    incluir_devolucao = st.sidebar.toggle("Somente Devolução", value=False)

    if "Marca" in df.columns:
        marca_lista = sorted(df["Marca"].dropna().unique())
        marca_sel = st.sidebar.multiselect(
            "Marca",
            options=marca_lista,
            default=[],
            placeholder="Todas as marcas",
        )
    else:
        marca_sel = []

    if "Categoria" in df.columns:
        categoria_lista = sorted(df["Categoria"].dropna().unique())
        categoria_sel = st.sidebar.multiselect(
            "Categoria",
            options=categoria_lista,
            default=[],
            placeholder="Todas as categorias",
        )
    else:
        categoria_sel = []
        
    if "Fornecedor" in df.columns:
        fornecedor_lista = sorted(df["Fornecedor"].dropna().unique())
        fornecedor_sel = st.sidebar.multiselect(
            "Fornecedor",
            options=fornecedor_lista,
            default=[],
            placeholder="Todos os fornecedores",
        )
    else:
        fornecedor_sel = []
    
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
    
        st.sidebar.markdown("**Período Rápido**")
    
        if "periodo_rapido" not in st.session_state:
            st.session_state["periodo_rapido"] = "Mês Atual"
    
        if "ultimo_periodo_rapido_aplicado" not in st.session_state:
            st.session_state["ultimo_periodo_rapido_aplicado"] = None
    
        if "periodo_datas" not in st.session_state:
            st.session_state["periodo_datas"] = (default_ini, default_fim)
    
        periodo_rapido = st.sidebar.radio(
            "Selecione um atalho",
            options=["Mês Atual", "Últimos 7 dias", "Últimos 15 dias", "Últimos 30 dias", "Personalizado"],
            key="periodo_rapido",
            label_visibility="collapsed",
            horizontal=False,
        )
    
        if periodo_rapido == "Mês Atual":
            periodo_value = (default_ini, default_fim)
        elif periodo_rapido == "Últimos 7 dias":
            _ini_rapido = (ontem_sp - pd.Timedelta(days=6)).date()
            _fim_rapido = ontem_sp.date()
            _ini_rapido = max(_ini_rapido, data_min)
            _fim_rapido = min(_fim_rapido, data_max)
            periodo_value = (_ini_rapido, _fim_rapido)
        elif periodo_rapido == "Últimos 15 dias":
            _ini_rapido = (ontem_sp - pd.Timedelta(days=14)).date()
            _fim_rapido = ontem_sp.date()
            _ini_rapido = max(_ini_rapido, data_min)
            _fim_rapido = min(_fim_rapido, data_max)
            periodo_value = (_ini_rapido, _fim_rapido)
        elif periodo_rapido == "Últimos 30 dias":
            _ini_rapido = (ontem_sp - pd.Timedelta(days=29)).date()
            _fim_rapido = ontem_sp.date()
            _ini_rapido = max(_ini_rapido, data_min)
            _fim_rapido = min(_fim_rapido, data_max)
            periodo_value = (_ini_rapido, _fim_rapido)
        else:
            periodo_value = st.session_state["periodo_datas"]
    
        if periodo_rapido != "Personalizado":
            if st.session_state["ultimo_periodo_rapido_aplicado"] != periodo_rapido:
                st.session_state["periodo_datas"] = periodo_value
                st.session_state["ultimo_periodo_rapido_aplicado"] = periodo_rapido
    
        periodo = st.sidebar.date_input(
            "Período de Venda",
            value=st.session_state["periodo_datas"],
            min_value=data_min,
            max_value=data_max,
            key="periodo_datas",
            on_change=ao_mudar_periodo_manual,
        )
    
        if isinstance(periodo, (list, tuple)) and len(periodo) == 2:
            data_ini = pd.Timestamp(periodo[0]).normalize()
            data_fim = pd.Timestamp(periodo[1]).normalize()
        else:
            data_ini = pd.Timestamp(st.session_state["periodo_datas"][0]).normalize()
            data_fim = pd.Timestamp(st.session_state["periodo_datas"][1]).normalize()
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
        fornecedores_sel=fornecedor_sel,
        incluir_devolucao=incluir_devolucao,
    )

    if data_ini is not None and data_fim is not None:
        df_f = filtrar_intervalo(df_dim, "Data_Emissao_Filtro", data_ini, data_fim)
        ini_ant, fim_ant, dias_periodo = periodo_anterior(data_ini, data_fim, periodo_rapido)
        df_prev = filtrar_intervalo(df_dim, "Data_Emissao_Filtro", ini_ant, fim_ant)
    else:
        df_f = df_dim.copy()
        df_prev = df_dim.iloc[0:0].copy()
        ini_ant = fim_ant = None
        dias_periodo = 0

    if data_ini is not None and data_fim is not None:
        df_grafico_base = df_dim.copy()
    else:
        df_grafico_base = df_dim.iloc[0:0].copy()

    # ──────────────────────────────────────────
    # 8. CABEÇALHO
    # ──────────────────────────────────────────
    st.title("EmanxTelecom - Dashboard de Performance de Vendas")
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
    # ── CHANGE 5: custo médio → soma do custo total ───────────────────────────
    custo_total = df_f["Custo_Num"].sum()
    qtd_total = int(df_f["Qtd_Num"].sum())
    total_pedidos = len(df_f)

    receita_anterior = df_prev["Receita_Num"].sum()
    liquido_anterior = df_prev["Liquido_Num"].sum()
    custo_anterior = df_prev["Custo_Num"].sum()
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
    # Label atualizado para refletir a soma
    linha1[2].metric(
        "Custo Total",
        formatar_brl(custo_total),
        calcular_delta_percentual(custo_total, custo_anterior)
    )

    rotulo_itens = "Itens Devolvidos" if incluir_devolucao else "Itens Vendidos"
    
    linha2[0].metric(
        rotulo_itens,
        formatar_int(qtd_total),
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
        "Dia_Grafico" in df_grafico_base.columns and
        df_grafico_base["Dia_Grafico"].notna().any()
    ):
        df_cmp, ini_ant_chart, fim_ant_chart, dias_periodo_chart = montar_df_comparativo(
            df_base=df_grafico_base,
            coluna_data="Dia_Grafico",
            coluna_valor="Receita_Num",
            data_ini=data_ini,
            data_fim=data_fim,
            modo_periodo=periodo_rapido,
        )
    
        chart = criar_grafico_comparativo(df_cmp)
    
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
        filtro_mkt_ativo = bool(mkt_sel) and (not incluir_devolucao)
    
        if filtro_mkt_ativo:
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
                    y=alt.Y("Grupo de Marketplace:N", title="Marketplace", sort="-x"),
                    x=alt.X("Receita:Q", title="Receita (R$)"),
                    color=alt.Color("Tipo pedido:N", title="Tipo"),
                    tooltip=[
                        "Grupo de Marketplace:N",
                        "Tipo pedido:N",
                        alt.Tooltip("Receita:Q", format=",.2f"),
                    ],
                )
                .properties(height=380)
            )
        else:
            df_mkt = (
                df_f.groupby("Grupo de Marketplace")["Receita_Num"]
                .sum()
                .reset_index()
                .rename(columns={"Receita_Num": "Receita"})
            )
    
            chart_bar = (
                alt.Chart(df_mkt)
                .mark_bar()
                .encode(
                    y=alt.Y("Grupo de Marketplace:N", title="Marketplace", sort="-x"),
                    x=alt.X("Receita:Q", title="Receita (R$)"),
                    tooltip=[
                        "Grupo de Marketplace:N",
                        alt.Tooltip("Receita:Q", format=",.2f"),
                    ],
                )
                .properties(height=380)
            )
    
        st.altair_chart(chart_bar, use_container_width=True)
    
        if incluir_devolucao:
            st.caption("Exibindo apenas pedidos de devolução.")
        elif filtro_mkt_ativo:
            st.caption("Detalhado por Tipo de Pedido porque há filtro de marketplace ativo.")
        else:
            st.caption("Total por grupo de marketplace. Selecione marketplaces específicos para detalhar por tipo de pedido.")
    else:
        st.info("Sem dados para exibir o faturamento por marketplace e tipo de pedido.")

    # ──────────────────────────────────────────
    # 13. RANKINGS
    # ──────────────────────────────────────────
    st.subheader("Rankings")

    abas_ranking = [
        ("Produtos", "Produto"),
        ("Categorias", "Categoria"),
        ("Marcas", "Marca"),
    ]

    if "Fornecedor" in df_f.columns:
        abas_ranking.append(("Fornecedores", "Fornecedor"))

    tabs_principais = st.tabs([titulo for titulo, _ in abas_ranking])

    for (titulo_aba, campo), tab_principal in zip(abas_ranking, tabs_principais):
        with tab_principal:
            if campo not in df_f.columns:
                st.info(f"Coluna '{campo}' não encontrada.")
                continue

            top_n = st.slider(
                "Número de itens no ranking",
                5,
                30,
                10,
                key=f"top_n_{campo}"
            )

            subtab_receita, subtab_qtd = st.tabs(["Por Receita", "Por Quantidade Vendida"])

            with subtab_receita:
                if campo == "Produto":
                    df_rank = montar_ranking_produto(df_f, df_prev)
                    st.caption(
                        f"Comparação por receita contra o período anterior: "
                        f"{ini_ant.strftime('%d/%m/%Y')} até {fim_ant.strftime('%d/%m/%Y')}"
                        if ini_ant is not None and fim_ant is not None else
                        "Comparação por receita contra o período anterior"
                    )
                    render_ranking_produto(df_rank, "Receita", top_n)
                else:
                    df_rank = montar_ranking_grupo(df_f, df_prev, campo, "Receita")
                    st.caption(
                        f"A imagem exibida é do produto com maior receita dentro de cada {campo.lower()}."
                    )
                    render_ranking_grupo(df_rank, campo, "Receita", top_n)

            with subtab_qtd:
                if campo == "Produto":
                    df_rank = montar_ranking_produto(df_f, df_prev)
                    st.caption(
                        f"Comparação por quantidade contra o período anterior: "
                        f"{ini_ant.strftime('%d/%m/%Y')} até {fim_ant.strftime('%d/%m/%Y')}"
                        if ini_ant is not None and fim_ant is not None else
                        "Comparação por quantidade contra o período anterior"
                    )
                    render_ranking_produto(df_rank, "Quantidade", top_n)
                else:
                    df_rank = montar_ranking_grupo(df_f, df_prev, campo, "Quantidade")
                    st.caption(
                        f"A imagem exibida é do produto com maior quantidade dentro de cada {campo.lower()}."
                    )
                    render_ranking_grupo(df_rank, campo, "Quantidade", top_n)

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
            "Fornecedor",
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
