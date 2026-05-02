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
url_planilha = st.secrets["GSHEET_URL"]
BASE_IMG_URL = "https://emanxtelecom.com.br/imagens/"
LOGO_PATH = "assets/LogoEmanx-BW.png"

MARKETPLACE_ORDEM_CORES = [
    "MERCADO LIVRE",
    "AMAZON",
    "SHOPEE",
    "CASAS BAHIA",
    "MAGALU",
    "TIKTOK",
    "MANUAL",
]

MARKETPLACE_CORES = [
    "#ffd100",  # MERCADO LIVRE
    "#ff9900",  # AMAZON
    "#ee4d2d",  # SHOPEE
    "#0033a0",  # CASAS BAHIA
    "#0086ff",  # MAGALU
    "#010101",  # TIKTOK
    "#64748b",  # MANUAL
]

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

def formatar_pct(valor):
    try:
        if pd.isna(valor):
            return "0,0%"
        return f"{valor * 100:.1f}%".replace(".", ",")
    except Exception:
        return "0,0%"

def calcular_margem_pct(liquido, custo):
    try:
        liquido = float(liquido or 0)
        custo = float(custo or 0)
        if liquido == 0:
            return 0.0
        return 1 - (custo / liquido)
    except Exception:
        return 0.0

def calcular_taxa_devolucao_pct(qtd_devolvida, qtd_vendida_60d):
    try:
        qtd_devolvida = float(qtd_devolvida or 0)
        qtd_vendida_60d = float(qtd_vendida_60d or 0)
        if qtd_vendida_60d <= 0:
            return 0.0
        return qtd_devolvida / qtd_vendida_60d
    except Exception:
        return 0.0


def filtrar_base_vendas_60d(
    df_base,
    data_fim,
    filiais_sel,
    tipos_pedido_sel,
    marcas_sel,
    categorias_sel,
    fornecedores_sel,
    somente_fulfillment
):
    if data_fim is None or "Data_Emissao_Filtro" not in df_base.columns:
        return df_base.iloc[0:0].copy()

    fim_60d = pd.Timestamp(data_fim).normalize()
    ini_60d = fim_60d - pd.Timedelta(days=59)

    df_vendas_60d = df_base[~df_base["Eh_Devolucao"]].copy()

    if filiais_sel and "Filial_Filtro" in df_vendas_60d.columns:
        df_vendas_60d = df_vendas_60d[df_vendas_60d["Filial_Filtro"].isin(filiais_sel)]

    if somente_fulfillment and "Tipo pedido" in df_vendas_60d.columns:
        df_vendas_60d = df_vendas_60d[
            df_vendas_60d["Tipo pedido"]
            .apply(normalizar_texto)
            .str.contains("FULL", na=False)
        ]
    elif tipos_pedido_sel and "Tipo pedido" in df_vendas_60d.columns:
        df_vendas_60d = df_vendas_60d[df_vendas_60d["Tipo pedido"].isin(tipos_pedido_sel)]

    if marcas_sel and "Marca" in df_vendas_60d.columns:
        df_vendas_60d = df_vendas_60d[df_vendas_60d["Marca"].isin(marcas_sel)]

    if categorias_sel and "Categoria" in df_vendas_60d.columns:
        df_vendas_60d = df_vendas_60d[df_vendas_60d["Categoria"].isin(categorias_sel)]

    if fornecedores_sel and "Fornecedor" in df_vendas_60d.columns:
        df_vendas_60d = df_vendas_60d[df_vendas_60d["Fornecedor"].isin(fornecedores_sel)]

    df_vendas_60d = filtrar_intervalo(
        df_vendas_60d,
        "Data_Emissao_Filtro",
        ini_60d,
        fim_60d
    )

    return df_vendas_60d

def filtrar_ranking_margem_negativa(df_rank, somente_margem_negativa):
    if not somente_margem_negativa:
        return df_rank
    if df_rank.empty or "Margem_Pct" not in df_rank.columns:
        return df_rank.iloc[0:0].copy()
    return df_rank[df_rank["Margem_Pct"] < 0].copy()

def montar_ranking_produto(df_atual, df_anterior, df_vendas_60d=None, incluir_devolucao=False):
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

    if base_atual.empty:
        return pd.DataFrame()

    if "SKU" in base_atual.columns:
        rank_atual = (
            base_atual.groupby("Produto", as_index=False)
            .agg(
                Receita=("Receita_Num", "sum"),
                Liquido=("Liquido_Num", "sum"),
                Custo=("Custo_Num", "sum"),
                Quantidade=("Qtd_Num", "sum"),
                img_url=("img_url", primeiro_valor_nao_vazio),
                SKU=("SKU", primeiro_valor_nao_vazio),
            )
        )
    else:
        rank_atual = (
            base_atual.groupby("Produto", as_index=False)
            .agg(
                Receita=("Receita_Num", "sum"),
                Liquido=("Liquido_Num", "sum"),
                Custo=("Custo_Num", "sum"),
                Quantidade=("Qtd_Num", "sum"),
                img_url=("img_url", primeiro_valor_nao_vazio),
            )
        )
        rank_atual["SKU"] = ""

    rank_atual["Margem_Pct"] = rank_atual.apply(
        lambda row: calcular_margem_pct(row["Liquido"], row["Custo"]),
        axis=1
    )

    if incluir_devolucao:
        if df_vendas_60d is not None and not df_vendas_60d.empty and "Produto" in df_vendas_60d.columns:
            base_vendas_60d = df_vendas_60d[
                df_vendas_60d["Produto"].notna() &
                (df_vendas_60d["Produto"].astype(str).str.strip() != "")
            ].copy()

            vendas_60d = (
                base_vendas_60d.groupby("Produto", as_index=False)
                .agg(Quantidade_Vendida_60d=("Qtd_Num", "sum"))
            )
        else:
            vendas_60d = pd.DataFrame(columns=["Produto", "Quantidade_Vendida_60d"])

        rank_atual = rank_atual.merge(vendas_60d, on="Produto", how="left")
        rank_atual["Quantidade_Vendida_60d"] = rank_atual["Quantidade_Vendida_60d"].fillna(0)

        rank_atual["Taxa_Devolucao_Pct"] = rank_atual.apply(
            lambda row: calcular_taxa_devolucao_pct(
                row["Quantidade"],
                row["Quantidade_Vendida_60d"]
            ),
            axis=1
        )
    else:
        rank_atual["Quantidade_Vendida_60d"] = 0
        rank_atual["Taxa_Devolucao_Pct"] = 0.0

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

def montar_ranking_grupo(df_atual, df_anterior, campo_grupo, metrica_ordenacao, df_vendas_60d=None, incluir_devolucao=False):
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
            Liquido=("Liquido_Num", "sum"),
            Custo=("Custo_Num", "sum"),
            Quantidade=("Qtd_Num", "sum"),
        )
    )

    rank_atual["Margem_Pct"] = rank_atual.apply(
        lambda row: calcular_margem_pct(row["Liquido"], row["Custo"]),
        axis=1
    )

    if incluir_devolucao:
        if df_vendas_60d is not None and not df_vendas_60d.empty and campo_grupo in df_vendas_60d.columns:
            base_vendas_60d = df_vendas_60d[
                df_vendas_60d[campo_grupo].notna() &
                (df_vendas_60d[campo_grupo].astype(str).str.strip() != "")
            ].copy()

            vendas_60d = (
                base_vendas_60d.groupby(campo_grupo, as_index=False)
                .agg(Quantidade_Vendida_60d=("Qtd_Num", "sum"))
            )
        else:
            vendas_60d = pd.DataFrame(columns=[campo_grupo, "Quantidade_Vendida_60d"])

        rank_atual = rank_atual.merge(vendas_60d, on=campo_grupo, how="left")
        rank_atual["Quantidade_Vendida_60d"] = rank_atual["Quantidade_Vendida_60d"].fillna(0)

        rank_atual["Taxa_Devolucao_Pct"] = rank_atual.apply(
            lambda row: calcular_taxa_devolucao_pct(
                row["Quantidade"],
                row["Quantidade_Vendida_60d"]
            ),
            axis=1
        )
    else:
        rank_atual["Quantidade_Vendida_60d"] = 0
        rank_atual["Taxa_Devolucao_Pct"] = 0.0

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

def render_ranking_produto(df_rank, metrica_ordenacao, top_n, incluir_devolucao=False):
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
        produto = html.escape(truncar_texto(row["Produto"], 65))
        sku = html.escape(str(row.get("SKU", "") or ""))
        chip = formatar_chip_delta(row[metrica_ordenacao], row[coluna_anterior])

        if incluir_devolucao:
            chip_analise = formatar_chip_taxa_devolucao(
                row.get("Taxa_Devolucao_Pct", 0),
                row.get("Quantidade_Vendida_60d", 0)
            )
            rotulo_quantidade = "Devolvidos"
            linha_vendas_60d = (
                f'<div><strong>Vendidos 60D:</strong> '
                f'{formatar_int(row.get("Quantidade_Vendida_60d", 0))}</div>'
            )
        else:
            chip_analise = formatar_chip_margem(row.get("Margem_Pct", 0))
            rotulo_quantidade = "Quantidade"
            linha_vendas_60d = ""

        img_html = (
            f'<img src="{row["img_url"]}" alt="{produto}">'
            if row.get("img_url")
            else '<span style="font-size:0.9rem;color:#64748b;">—</span>'
        )

        subtitle_html = (
            f'<div class="ranking-subtitle">SKU: {sku}</div>'
            if sku else ""
        )

        card_html = "".join([
            '<div class="ranking-card">',
                '<div class="ranking-card-grid">',
                    f'<div class="ranking-pos">{pos}</div>',
                    f'<div class="ranking-img-wrap">{img_html}</div>',
                    '<div>',
                        f'<div class="ranking-title">{produto}</div>',
                        subtitle_html,
                    '</div>',
                    '<div class="ranking-metrics">',
                        f'<div><strong>Receita:</strong> {formatar_brl(row["Receita"])}</div>',
                        f'<div><strong>{rotulo_quantidade}:</strong> {formatar_int(row["Quantidade"])}</div>',
                        linha_vendas_60d,
                        '<div class="ranking-chips-row">',
                            chip_analise,
                            chip,
                        '</div>',
                    '</div>',
                '</div>',
            '</div>',
        ])

        st.markdown(card_html, unsafe_allow_html=True)

def render_ranking_grupo(df_rank, campo_grupo, metrica_ordenacao, top_n, incluir_devolucao=False):
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
        produto_destaque = html.escape(truncar_texto(row.get("Produto_Destaque", "") or "", 65))
        chip = formatar_chip_delta(row[metrica_ordenacao], row[coluna_anterior])

        if incluir_devolucao:
            chip_analise = formatar_chip_taxa_devolucao(
                row.get("Taxa_Devolucao_Pct", 0),
                row.get("Quantidade_Vendida_60d", 0)
            )
            rotulo_quantidade = "Devolvidos"
            linha_vendas_60d = (
                f'<div><strong>Vendidos 60D:</strong> '
                f'{formatar_int(row.get("Quantidade_Vendida_60d", 0))}</div>'
            )
        else:
            chip_analise = formatar_chip_margem(row.get("Margem_Pct", 0))
            rotulo_quantidade = "Quantidade"
            linha_vendas_60d = ""

        img_html = (
            f'<img src="{row["img_url_destaque"]}" alt="{nome_grupo}">'
            if row.get("img_url_destaque")
            else '<span style="font-size:0.9rem;color:#64748b;">—</span>'
        )

        subtitle_html = (
            f'<div class="ranking-subtitle">Produto destaque: {produto_destaque}</div>'
            if produto_destaque else ""
        )

        card_html = "".join([
            '<div class="ranking-card">',
                '<div class="ranking-card-grid">',
                    f'<div class="ranking-pos">{pos}</div>',
                    f'<div class="ranking-img-wrap">{img_html}</div>',
                    '<div>',
                        f'<div class="ranking-title">{nome_grupo}</div>',
                        subtitle_html,
                    '</div>',
                    '<div class="ranking-metrics">',
                        f'<div><strong>Receita:</strong> {formatar_brl(row["Receita"])}</div>',
                        f'<div><strong>{rotulo_quantidade}:</strong> {formatar_int(row["Quantidade"])}</div>',
                        linha_vendas_60d,
                        '<div class="ranking-chips-row">',
                            chip_analise,
                            chip,
                        '</div>',
                    '</div>',
                '</div>',
            '</div>',
        ])

        st.markdown(card_html, unsafe_allow_html=True)

def limpar_moeda(valor):
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
    s = s.replace(".", "").replace(",", ".")
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

def truncar_texto(texto, limite=65):
    if pd.isna(texto):
        return ""
    texto = str(texto).strip()
    return texto if len(texto) <= limite else texto[:limite].rstrip() + "..."

def parse_data_serie(series: pd.Series) -> pd.Series:
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
        "%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
        "%d-%m-%Y", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
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
        "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%Y/%m/%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
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
                numericos[ok], unit="D", origin="1899-12-30", errors="coerce"
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

def normalizar_sku(valor):
    if pd.isna(valor):
        return ""
    txt = str(valor).strip()
    if txt.endswith(".0"):
        txt = txt[:-2]
    return txt

def normalizar_filial(valor):
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
    return txt.zfill(5)

def obter_coluna_descricao_produto(df_base):
    if "Descrição" in df_base.columns:
        return "Descrição"
    if "Descricao" in df_base.columns:
        return "Descricao"
    if "Produto" in df_base.columns:
        return "Produto"
    return None


def montar_label_produto_filtro(row):
    codigo = normalizar_codigo(row.get("Código", ""), tamanho_min=6)
    sku = normalizar_sku(row.get("SKU", ""))

    descricao = ""
    for col in ["Descrição", "Descricao", "Produto"]:
        if col in row.index:
            descricao = str(row.get(col, "") or "").strip()
            break

    partes = []

    if codigo:
        partes.append(codigo)

    if descricao:
        if partes:
            texto = f"{partes[0]} - {descricao}"
        else:
            texto = descricao
    else:
        texto = codigo or sku or "Produto não identificado"

    if sku:
        texto = f"{texto} | SKU: {sku}"

    return texto


def montar_key_produto_filtro(row):
    sku = normalizar_sku(row.get("SKU", ""))
    codigo = normalizar_codigo(row.get("Código", ""), tamanho_min=6)

    descricao = ""
    for col in ["Descrição", "Descricao", "Produto"]:
        if col in row.index:
            descricao = str(row.get(col, "") or "").strip()
            break

    if sku:
        return f"SKU::{sku}"

    if codigo:
        return f"CODIGO::{codigo}"

    return f"PRODUTO::{normalizar_texto(descricao)}"


def montar_opcoes_produto_filtro(df_base):
    if df_base.empty or "Produto_Filtro_Key" not in df_base.columns or "Produto_Filtro_Label" not in df_base.columns:
        return [], {}

    base = df_base[
        df_base["Produto_Filtro_Key"].notna() &
        (df_base["Produto_Filtro_Key"].astype(str).str.strip() != "") &
        df_base["Produto_Filtro_Label"].notna() &
        (df_base["Produto_Filtro_Label"].astype(str).str.strip() != "")
    ].copy()

    if base.empty:
        return [], {}

    opcoes = (
        base[["Produto_Filtro_Key", "Produto_Filtro_Label"]]
        .drop_duplicates(subset=["Produto_Filtro_Key"])
        .sort_values("Produto_Filtro_Label")
    )

    keys = opcoes["Produto_Filtro_Key"].tolist()
    labels = dict(zip(opcoes["Produto_Filtro_Key"], opcoes["Produto_Filtro_Label"]))

    return keys, labels

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

def calcular_delta_pontos_percentuais(atual, anterior):
    try:
        atual = float(atual or 0)
        anterior = float(anterior or 0)
        delta_pct = (atual - anterior) * 100
        if delta_pct > 0:
            return f"+{delta_pct:.1f}%".replace(".", ",")
        elif delta_pct < 0:
            return f"{delta_pct:.1f}%".replace(".", ",")
        else:
            return "0,0%"
    except Exception:
        return "0,0%"

def formatar_chip_delta(atual, anterior):
    texto, classe = obter_delta_info(atual, anterior)
    mapa = {"up": "#15803d", "down": "#dc2626", "neutral": "#475569"}
    fundo = {
        "up": "rgba(34,197,94,0.12)",
        "down": "rgba(239,68,68,0.12)",
        "neutral": "rgba(100,116,139,0.12)",
    }
    return (
        f'<span class="ranking-chip" '
        f'style="color:{mapa[classe]}; background:{fundo[classe]};">'
        f'Variação: {texto}'
        f'</span>'
    )

def formatar_chip_margem(margem):
    try:
        margem = float(margem or 0)
    except Exception:
        margem = 0.0
    texto = formatar_pct(margem)
    if margem > 0:
        cor = "#15803d"
        fundo = "rgba(34,197,94,0.12)"
    else:
        cor = "#dc2626"
        fundo = "rgba(239,68,68,0.12)"
    return (
        f'<span class="ranking-chip" '
        f'style="color:{cor}; background:{fundo};">'
        f'Margem: {texto}'
        f'</span>'
    )

def formatar_chip_taxa_devolucao(taxa_devolucao, qtd_vendida_60d):
    try:
        taxa_devolucao = float(taxa_devolucao or 0)
        qtd_vendida_60d = float(qtd_vendida_60d or 0)
    except Exception:
        taxa_devolucao = 0.0
        qtd_vendida_60d = 0.0
    if qtd_vendida_60d <= 0:
        return (
            f'<span class="ranking-chip" '
            f'style="color:#475569; background:rgba(100,116,139,0.12);">'
            f'Devolução: N/D'
            f'</span>'
        )
    texto = formatar_pct(taxa_devolucao)
    if taxa_devolucao > 0:
        cor = "#dc2626"
        fundo = "rgba(239,68,68,0.12)"
    else:
        cor = "#475569"
        fundo = "rgba(100,116,139,0.12)"
    return (
        f'<span class="ranking-chip" '
        f'style="color:{cor}; background:{fundo};">'
        f'Devolução: {texto}'
        f'</span>'
    )

def periodo_anterior(data_ini, data_fim, modo_periodo="Personalizado"):
    data_ini = pd.Timestamp(data_ini).normalize()
    data_fim = pd.Timestamp(data_fim).normalize()
    dias_periodo = (data_fim - data_ini).days + 1
    if modo_periodo in ["Últimos 7 dias", "Últimos 15 dias", "Últimos 30 dias"]:
        fim_anterior = data_ini - pd.Timedelta(days=1)
        ini_anterior = fim_anterior - pd.Timedelta(days=dias_periodo - 1)
        return ini_anterior.normalize(), fim_anterior.normalize(), dias_periodo
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
    fim_anterior = data_ini - pd.Timedelta(days=1)
    ini_anterior = fim_anterior - pd.Timedelta(days=dias_periodo - 1)
    return ini_anterior.normalize(), fim_anterior.normalize(), dias_periodo

def calcular_dominio_y_grafico(df_plot, coluna_valor="Valor"):
    if df_plot.empty or coluna_valor not in df_plot.columns:
        return [0, 1]
    valores = pd.to_numeric(df_plot[coluna_valor], errors="coerce").dropna()
    valores_positivos = valores[valores > 0]
    if valores_positivos.empty:
        return [0, 1]
    valor_min = float(valores_positivos.min())
    valor_max = float(valores_positivos.max())
    if valor_min == valor_max:
        margem = valor_max * 0.10 if valor_max > 0 else 1
        return [max(0, valor_min - margem), valor_max + margem]
    amplitude = valor_max - valor_min
    if valor_max >= 100000:
        passo = 10000
    elif valor_max >= 50000:
        passo = 5000
    elif valor_max >= 10000:
        passo = 1000
    elif valor_max >= 1000:
        passo = 500
    else:
        passo = 100
    y_min = max(0, (valor_min // passo) * passo)
    y_max = ((valor_max // passo) + 1) * passo
    if y_max <= valor_max:
        y_max = valor_max + amplitude * 0.10
    return [y_min, y_max]

# ──────────────────────────────────────────────
# HELPERS DE EIXO — elimina títulos verbosos no mobile
# ──────────────────────────────────────────────
def _eixo_x_dias(angulo=0):
    """Eixo X padrão para séries de dias (posição relativa D01, D02…)."""
    cinza_eixo = "#64748b"
    cinza_grade = "#CBD5E1"
    return alt.Axis(
        labelColor=cinza_eixo,
        titleColor=cinza_eixo,
        domainColor=cinza_grade,
        tickColor=cinza_grade,
        labelAngle=angulo,
        labelPadding=8,
        titlePadding=10,
        labelOverlap=True,
    )

def _eixo_y_receita():
    """Eixo Y sem título longo — economiza espaço horizontal no mobile."""
    cinza_eixo = "#64748b"
    cinza_grade = "#CBD5E1"
    return alt.Axis(
        title=None,               # REMOVIDO: libera ~40 px no mobile
        labelColor=cinza_eixo,
        domainColor=cinza_grade,
        tickColor=cinza_grade,
        gridColor="rgba(148,163,184,0.18)",
        labelPadding=6,
        format="~s",              # 1k, 10k, 1M — mais curto no eixo
    )

def _eixo_x_data(angulo=0):
    """Eixo X padrão para datas reais."""
    cinza_eixo = "#64748b"
    cinza_grade = "#CBD5E1"
    return alt.Axis(
        format="%d/%m",
        labelColor=cinza_eixo,
        titleColor=cinza_eixo,
        domainColor=cinza_grade,
        tickColor=cinza_grade,
        labelAngle=angulo,
        labelPadding=8,
        titlePadding=10,
        labelOverlap=True,
    )

# ──────────────────────────────────────────────
# GRÁFICO: COMPARATIVO PERÍODO ATUAL x ANTERIOR
# ──────────────────────────────────────────────
def criar_grafico_comparativo(df_cmp: pd.DataFrame):
    df_plot = df_cmp.copy()

    ordem_series = ["Período Atual", "Período Anterior"]
    cor_linha_atual   = "#4aa065"
    cor_area_atual    = "#4aa065"
    cor_linha_anterior = "#dfaf24"
    cor_area_anterior  = "#ffffe7"

    df_plot["Serie"] = pd.Categorical(df_plot["Serie"], categories=ordem_series, ordered=True)
    df_plot["Ordem_Serie"] = df_plot["Serie"].cat.codes

    dominio_y = calcular_dominio_y_grafico(df_plot, "Valor")
    df_plot["Baseline_Y"] = dominio_y[0]

    qtd_dias  = df_plot["Posicao_Label"].nunique()
    angulo_x  = -35 if qtd_dias > 22 else 0

    escala_cores = alt.Scale(domain=ordem_series, range=[cor_linha_atual, cor_linha_anterior])
    legenda      = alt.Legend(orient="top", direction="horizontal", title=None)

    base = (
        alt.Chart(df_plot)
        .encode(
            x=alt.X("Posicao_Label:O", title=None, axis=_eixo_x_dias(angulo_x)),
            y=alt.Y(
                "Valor:Q",
                scale=alt.Scale(domain=dominio_y, zero=False, nice=False),
                axis=_eixo_y_receita(),
            ),
            tooltip=[
                alt.Tooltip("Serie:N",          title="Série"),
                alt.Tooltip("Posicao_Dia:Q",    title="Posição"),
                alt.Tooltip("Data_Original:T",  title="Data",    format="%d/%m/%Y"),
                alt.Tooltip("Valor:Q",          title="R$",      format=",.2f"),
            ],
        )
    )

    area_ant  = base.transform_filter(alt.datum.Serie == "Período Anterior").mark_area(color=cor_area_anterior, opacity=0.14, interpolate="monotone").encode(y2=alt.Y2("Baseline_Y:Q"))
    area_at   = base.transform_filter(alt.datum.Serie == "Período Atual").mark_area(color=cor_area_atual, opacity=0.14, interpolate="monotone").encode(y2=alt.Y2("Baseline_Y:Q"))
    linha_ant = base.transform_filter(alt.datum.Serie == "Período Anterior").mark_line(strokeWidth=2.6, interpolate="monotone").encode(color=alt.Color("Serie:N", scale=escala_cores, legend=legenda))
    pts_ant   = base.transform_filter(alt.datum.Serie == "Período Anterior").mark_circle(size=42, opacity=0.95, stroke="white", strokeWidth=1).encode(color=alt.Color("Serie:N", scale=escala_cores, legend=legenda))
    linha_at  = base.transform_filter(alt.datum.Serie == "Período Atual").mark_line(strokeWidth=3.3, interpolate="monotone").encode(color=alt.Color("Serie:N", scale=escala_cores, legend=legenda))
    pts_at    = base.transform_filter(alt.datum.Serie == "Período Atual").mark_circle(size=52, opacity=0.95, stroke="white", strokeWidth=1).encode(color=alt.Color("Serie:N", scale=escala_cores, legend=legenda))

    return (
        alt.layer(area_ant, area_at, linha_ant, pts_ant, linha_at, pts_at)
        .resolve_scale(color="shared")
        .properties(height=340, padding={"top": 8, "right": 8, "bottom": 24, "left": 4})
        .configure_view(strokeWidth=0)
    )

# ──────────────────────────────────────────────
# GRÁFICO: LOTES X NOVOS
# ──────────────────────────────────────────────
def montar_df_lotes_complementar(df_base, data_ini, data_fim):
    base_valida  = df_base[df_base["Dia_Grafico"].notna()].copy()
    base_periodo = filtrar_intervalo(base_valida, "Dia_Grafico", data_ini, data_fim)
    if base_periodo.empty:
        return pd.DataFrame()

    datas_periodo = pd.date_range(
        pd.Timestamp(data_ini).normalize(),
        pd.Timestamp(data_fim).normalize(),
        freq="D"
    )

    total_dia = (
        base_periodo.groupby("Dia_Grafico", as_index=True)["Receita_Num"]
        .sum()
        .reindex(datas_periodo, fill_value=0)
    )

    if "Fornecedor" in base_periodo.columns:
        lotes_dia = (
            base_periodo[base_periodo["Fornecedor"].apply(normalizar_texto) == "LOTES"]
            .groupby("Dia_Grafico", as_index=True)["Receita_Num"]
            .sum()
            .reindex(datas_periodo, fill_value=0)
        )
    else:
        lotes_dia = pd.Series(0, index=datas_periodo, dtype="float64")

    complementar_dia = total_dia - lotes_dia

    df_lotes = pd.DataFrame({"Data_Original": datas_periodo, "Valor": lotes_dia.values,        "Serie": "Receita Lotes"})
    df_comp  = pd.DataFrame({"Data_Original": datas_periodo, "Valor": complementar_dia.values, "Serie": "Receita Novos"})

    df_plot = pd.concat([df_lotes, df_comp], ignore_index=True)
    df_plot["Posicao_Dia"]   = df_plot.groupby("Serie").cumcount() + 1
    df_plot["Posicao_Label"] = df_plot["Posicao_Dia"].apply(lambda x: f"D{x:02d}")
    return df_plot


def criar_grafico_lotes_complementar(df_plot: pd.DataFrame):
    ordem_series = ["Receita Novos", "Receita Lotes"]
    cor_novos = "#4aa065"
    cor_lotes = "#94a3b8"

    df_plot = df_plot.copy()
    df_plot["Serie"] = pd.Categorical(df_plot["Serie"], categories=ordem_series, ordered=True)
    df_plot["Ordem_Serie"] = df_plot["Serie"].cat.codes

    dominio_y = calcular_dominio_y_grafico(df_plot, "Valor")
    df_plot["Baseline_Y"] = dominio_y[0]

    qtd_dias = df_plot["Posicao_Label"].nunique()
    angulo_x = -35 if qtd_dias > 22 else 0

    escala_cores = alt.Scale(domain=ordem_series, range=[cor_novos, cor_lotes])
    legenda      = alt.Legend(orient="top", direction="horizontal", title=None)

    base = (
        alt.Chart(df_plot)
        .encode(
            x=alt.X("Posicao_Label:O", title=None, axis=_eixo_x_dias(angulo_x)),
            y=alt.Y(
                "Valor:Q",
                scale=alt.Scale(domain=dominio_y, zero=False, nice=False),
                axis=_eixo_y_receita(),
            ),
            tooltip=[
                alt.Tooltip("Serie:N",         title="Série"),
                alt.Tooltip("Posicao_Dia:Q",   title="Posição"),
                alt.Tooltip("Data_Original:T", title="Data", format="%d/%m/%Y"),
                alt.Tooltip("Valor:Q",         title="R$",   format=",.2f"),
            ],
        )
    )

    area_l  = base.transform_filter(alt.datum.Serie == "Receita Lotes").mark_area(color=cor_lotes, opacity=0.14, interpolate="monotone").encode(y2=alt.Y2("Baseline_Y:Q"))
    area_n  = base.transform_filter(alt.datum.Serie == "Receita Novos").mark_area(color=cor_novos, opacity=0.14, interpolate="monotone").encode(y2=alt.Y2("Baseline_Y:Q"))
    linha_l = base.transform_filter(alt.datum.Serie == "Receita Lotes").mark_line(strokeWidth=2.6, interpolate="monotone").encode(color=alt.Color("Serie:N", scale=escala_cores, legend=legenda))
    pts_l   = base.transform_filter(alt.datum.Serie == "Receita Lotes").mark_circle(size=42, opacity=0.95, stroke="white", strokeWidth=1).encode(color=alt.Color("Serie:N", scale=escala_cores, legend=legenda))
    linha_n = base.transform_filter(alt.datum.Serie == "Receita Novos").mark_line(strokeWidth=3.3, interpolate="monotone").encode(color=alt.Color("Serie:N", scale=escala_cores, legend=legenda))
    pts_n   = base.transform_filter(alt.datum.Serie == "Receita Novos").mark_circle(size=52, opacity=0.95, stroke="white", strokeWidth=1).encode(color=alt.Color("Serie:N", scale=escala_cores, legend=legenda))

    return (
        alt.layer(area_l, area_n, linha_l, pts_l, linha_n, pts_n)
        .resolve_scale(color="shared")
        .properties(height=340, padding={"top": 8, "right": 8, "bottom": 24, "left": 4})
        .configure_view(strokeWidth=0)
    )

def montar_resumo_lotes_novos_grafico(df_base, data_ini, data_fim):
    if df_base.empty:
        return pd.DataFrame()

    base = df_base.copy()

    if "Dia_Grafico" not in base.columns:
        return pd.DataFrame()

    base = base[base["Dia_Grafico"].notna()].copy()
    base = filtrar_intervalo(base, "Dia_Grafico", data_ini, data_fim)

    if base.empty:
        return pd.DataFrame()

    if "Fornecedor" in base.columns:
        base["Serie_Resumo"] = base["Fornecedor"].apply(
            lambda x: "Lotes" if normalizar_texto(x) == "LOTES" else "Novos"
        )
    else:
        base["Serie_Resumo"] = "Novos"

    resumo = (
        base.groupby("Serie_Resumo", as_index=False)
        .agg(
            Receita=("Receita_Num", "sum"),
            Liquido=("Liquido_Num", "sum"),
            Custo=("Custo_Num", "sum"),
            Quantidade=("Qtd_Num", "sum"),
        )
    )

    if resumo.empty:
        return pd.DataFrame()

    total_receita = float(resumo["Receita"].sum())

    resumo["Margem_Pct"] = resumo.apply(
        lambda row: calcular_margem_pct(row["Liquido"], row["Custo"]),
        axis=1
    )

    resumo["Ticket_Medio"] = resumo.apply(
        lambda row: (row["Receita"] / row["Quantidade"]) if row["Quantidade"] > 0 else 0.0,
        axis=1
    )

    resumo["Percentual_Total"] = resumo["Receita"].apply(
        lambda x: (x / total_receita) if total_receita > 0 else 0.0
    )

    ordem = ["Novos", "Lotes"]
    resumo["Serie_Resumo"] = pd.Categorical(
        resumo["Serie_Resumo"],
        categories=ordem,
        ordered=True
    )
    resumo = resumo.sort_values("Serie_Resumo").reset_index(drop=True)

    resumo["Série"] = resumo["Serie_Resumo"]
    resumo["% do Total"] = resumo["Percentual_Total"].apply(formatar_pct)
    resumo["Receita Bruta"] = resumo["Receita"].apply(formatar_brl)
    resumo["Líquido"] = resumo["Liquido"].apply(formatar_brl)
    resumo["Custo"] = resumo["Custo"].apply(formatar_brl)
    resumo["Quantidade"] = resumo["Quantidade"].apply(formatar_int)
    resumo["Margem"] = resumo["Margem_Pct"].apply(formatar_pct)
    resumo["Ticket Médio"] = resumo["Ticket_Medio"].apply(formatar_brl)

    return resumo[
        [
            "Série",
            "% do Total",
            "Receita Bruta",
            "Líquido",
            "Custo",
            "Quantidade",
            "Margem",
            "Ticket Médio",
        ]
    ]


def preparar_tabela_resumo_lotes_novos(df_resumo):
    df_tabela = df_resumo.copy()

    if df_tabela.empty or "Série" not in df_tabela.columns:
        return df_tabela

    def fmt_serie(valor):
        txt = str(valor).strip()

        if txt == "Novos":
            return ":material/new_releases: Novos"

        if txt == "Lotes":
            return ":material/inventory_2: Lotes"

        return txt

    df_tabela["Série"] = df_tabela["Série"].apply(fmt_serie)

    return df_tabela

# ──────────────────────────────────────────────
# GRÁFICO: RECEITA POR MARKETPLACE POR DIA
# ──────────────────────────────────────────────
def montar_df_marketplace_por_dia(df_base, data_ini, data_fim):
    colunas_necessarias = ["Data_Emissao_Filtro", "Grupo de Marketplace", "Receita_Num"]
    if df_base.empty or not all(col in df_base.columns for col in colunas_necessarias):
        return pd.DataFrame(), []

    base = df_base[
        df_base["Data_Emissao_Filtro"].notna() &
        df_base["Grupo de Marketplace"].notna() &
        (df_base["Grupo de Marketplace"].astype(str).str.strip() != "")
    ].copy()

    if base.empty:
        return pd.DataFrame(), []

    base_periodo = filtrar_intervalo(base, "Data_Emissao_Filtro", data_ini, data_fim)
    if base_periodo.empty:
        return pd.DataFrame(), []

    ordem_marketplace = (
        base_periodo.groupby("Grupo de Marketplace", as_index=False)
        .agg(Receita_Total=("Receita_Num", "sum"))
        .sort_values("Receita_Total", ascending=False)
        ["Grupo de Marketplace"].tolist()
    )

    datas_periodo = pd.date_range(
        pd.Timestamp(data_ini).normalize(),
        pd.Timestamp(data_fim).normalize(),
        freq="D"
    )

    df_dia = (
        base_periodo
        .groupby(["Data_Emissao_Filtro", "Grupo de Marketplace"], as_index=False)
        .agg(Receita=("Receita_Num", "sum"))
    )

    idx = pd.MultiIndex.from_product(
        [datas_periodo, ordem_marketplace],
        names=["Data_Emissao_Filtro", "Grupo de Marketplace"]
    )

    df_plot = (
        df_dia
        .set_index(["Data_Emissao_Filtro", "Grupo de Marketplace"])
        .reindex(idx, fill_value=0)
        .reset_index()
    )
    df_plot["Receita_Total_Marketplace"] = df_plot.groupby("Grupo de Marketplace")["Receita"].transform("sum")
    df_plot["Ordem_Marketplace"] = df_plot["Grupo de Marketplace"].map({mkt: i for i, mkt in enumerate(ordem_marketplace)})

    return df_plot, ordem_marketplace


def _escala_cores_marketplace(ordem_marketplace):
    extras = [mkt for mkt in ordem_marketplace if mkt not in MARKETPLACE_ORDEM_CORES]
    cores_extras = ["#0f766e","#a16207","#be123c","#4338ca","#0369a1","#7c2d12"]
    return (
        MARKETPLACE_ORDEM_CORES + extras,
        MARKETPLACE_CORES + cores_extras
    )


def criar_grafico_marketplace_por_dia(df_plot: pd.DataFrame, ordem_marketplace):
    if df_plot.empty:
        return None

    dominio_cores, faixa_cores = _escala_cores_marketplace(ordem_marketplace)

    qtd_dias = df_plot["Data_Emissao_Filtro"].nunique()
    angulo_x = -35 if qtd_dias > 22 else 0

    dominio_y = calcular_dominio_y_grafico(df_plot, "Receita")

    base = (
        alt.Chart(df_plot)
        .encode(
            x=alt.X("Data_Emissao_Filtro:T", title=None, axis=_eixo_x_data(angulo_x)),
            y=alt.Y(
                "Receita:Q",
                scale=alt.Scale(domain=dominio_y, zero=False, nice=False),
                axis=_eixo_y_receita(),
            ),
            color=alt.Color(
                "Grupo de Marketplace:N",
                title="Marketplace",
                scale=alt.Scale(domain=dominio_cores, range=faixa_cores),
                legend=alt.Legend(orient="top", direction="horizontal", title=None),
                sort=ordem_marketplace,
            ),
            detail="Grupo de Marketplace:N",
            tooltip=[
                alt.Tooltip("Grupo de Marketplace:N",       title="Marketplace"),
                alt.Tooltip("Data_Emissao_Filtro:T",        title="Data",     format="%d/%m/%Y"),
                alt.Tooltip("Receita:Q",                    title="R$",       format=",.2f"),
                alt.Tooltip("Receita_Total_Marketplace:Q",  title="Total MKT",format=",.2f"),
            ],
        )
    )

    linhas = base.mark_line(strokeWidth=2.7, interpolate="monotone", opacity=0.92)
    pontos = base.mark_circle(size=38, opacity=0.88, stroke="white", strokeWidth=1)

    return (
        alt.layer(linhas, pontos)
        .properties(height=340, padding={"top": 8, "right": 8, "bottom": 24, "left": 4})
        .configure_view(strokeWidth=0)
    )


# ──────────────────────────────────────────────
# GRÁFICO: FACETAS POR MARKETPLACE
# CORREÇÃO MOBILE: columns=1, width responsivo
# ──────────────────────────────────────────────
def criar_grafico_marketplace_por_dia_facetas(df_plot: pd.DataFrame, ordem_marketplace):
    """
    Visão individual por marketplace.

    Mudanças para mobile:
    • columns=1  → sem overflow horizontal
    • width="container" (Altair >= 5) → preenche o contêiner Streamlit
    • height por faceta reduzido para 160 px
    • eixo Y sem título (usa _eixo_y_receita)
    • y independente por faceta (scale resolve)
    """
    if df_plot.empty:
        return None

    dominio_cores, faixa_cores = _escala_cores_marketplace(ordem_marketplace)

    qtd_dias = df_plot["Data_Emissao_Filtro"].nunique()
    angulo_x = -35 if qtd_dias > 22 else 0

    cinza_eixo  = "#64748b"
    cinza_grade = "#CBD5E1"

    base = (
        alt.Chart(df_plot)
        .mark_line(point=True, strokeWidth=2.4, interpolate="monotone")
        .encode(
            x=alt.X("Data_Emissao_Filtro:T", title=None, axis=_eixo_x_data(angulo_x)),
            y=alt.Y(
                "Receita:Q",
                scale=alt.Scale(zero=False, nice=True),
                axis=_eixo_y_receita(),
            ),
            color=alt.Color(
                "Grupo de Marketplace:N",
                scale=alt.Scale(domain=dominio_cores, range=faixa_cores),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("Grupo de Marketplace:N",      title="Marketplace"),
                alt.Tooltip("Data_Emissao_Filtro:T",       title="Data",      format="%d/%m/%Y"),
                alt.Tooltip("Receita:Q",                   title="R$",        format=",.2f"),
                alt.Tooltip("Receita_Total_Marketplace:Q", title="Total MKT", format=",.2f"),
            ],
        )
        # ── CORREÇÃO PRINCIPAL ──────────────────────────
        # width="container" faz cada faceta usar 100% da
        # largura disponível; height menor economiza scroll.
        .properties(width="container", height=160)
        # ────────────────────────────────────────────────
        .facet(
            facet=alt.Facet(
                "Grupo de Marketplace:N",
                title=None,
                sort=ordem_marketplace,
                header=alt.Header(
                    labelColor=cinza_eixo,
                    labelFontSize=13,
                    labelFontWeight="bold",
                ),
            ),
            columns=1,   # ← ERA 2, AGORA 1: elimina overflow lateral
        )
        .resolve_scale(y="independent")
        .configure_view(strokeWidth=0)
    )
    return base


def filtrar_intervalo(df_base: pd.DataFrame, coluna_data: str, ini, fim) -> pd.DataFrame:
    if coluna_data not in df_base.columns:
        return df_base.iloc[0:0].copy()
    ini = pd.Timestamp(ini).normalize()
    fim = pd.Timestamp(fim).normalize()
    return df_base[(df_base[coluna_data] >= ini) & (df_base[coluna_data] <= fim)].copy()


def calcular_status_e_projecao(data_ini, data_fim, total_atual):
    if data_ini is None or data_fim is None:
        return {"status": "sem_periodo"}
    data_ini = pd.Timestamp(data_ini).normalize()
    data_fim = pd.Timestamp(data_fim).normalize()
    if data_ini.year != data_fim.year or data_ini.month != data_fim.month:
        return {"status": "multiplos_meses"}
    hoje_sp   = pd.Timestamp(datetime.now(ZoneInfo("America/Sao_Paulo")).date())
    ontem_sp  = hoje_sp - pd.Timedelta(days=1)
    inicio_mes_filtro = data_ini.replace(day=1)
    fim_mes_filtro    = inicio_mes_filtro + pd.offsets.MonthEnd(1)
    inicio_mes_atual  = hoje_sp.replace(day=1)
    if inicio_mes_filtro < inicio_mes_atual:
        return {"status": "finalizado"}
    if inicio_mes_filtro > inicio_mes_atual:
        return {"status": "futuro"}
    if data_ini != inicio_mes_filtro:
        return {"status": "intervalo_parcial"}
    if data_fim < ontem_sp:
        return {"status": "intervalo_parcial"}
    dias_passados  = ontem_sp.day
    dias_mes       = fim_mes_filtro.day
    dias_restantes = dias_mes - dias_passados
    if dias_passados <= 0:
        return {"status": "sem_base"}
    projecao = (total_atual / dias_passados) * dias_mes
    return {
        "status": "em_andamento",
        "dias_passados":  dias_passados,
        "dias_restantes": dias_restantes,
        "dias_mes":       dias_mes,
        "projecao":       projecao,
    }


def aplicar_filtros_dimensionais(
    df_base, marketplaces_sel, filiais_sel, tipos_pedido_sel,
    marcas_sel, categorias_sel, produtos_sel, fornecedores_sel,
    incluir_devolucao, somente_fulfillment
):
    if incluir_devolucao:
        df_out = df_base[df_base["Eh_Devolucao"]].copy()
    else:
        df_out = df_base[~df_base["Eh_Devolucao"]].copy()
        if marketplaces_sel:
            df_out = df_out[df_out["Grupo de Marketplace"].isin(marketplaces_sel)]

    if filiais_sel and "Filial_Filtro" in df_out.columns:
        df_out = df_out[df_out["Filial_Filtro"].isin(filiais_sel)]

    if somente_fulfillment and "Tipo pedido" in df_out.columns:
        df_out = df_out[df_out["Tipo pedido"].apply(normalizar_texto).str.contains("FULL", na=False)]
    elif tipos_pedido_sel and "Tipo pedido" in df_out.columns:
        df_out = df_out[df_out["Tipo pedido"].isin(tipos_pedido_sel)]

    if marcas_sel and "Marca" in df_out.columns:
        df_out = df_out[df_out["Marca"].isin(marcas_sel)]
    if categorias_sel and "Categoria" in df_out.columns:
        df_out = df_out[df_out["Categoria"].isin(categorias_sel)]
    if produtos_sel and "Produto_Filtro_Key" in df_out.columns:
        df_out = df_out[df_out["Produto_Filtro_Key"].isin(produtos_sel)]
    if fornecedores_sel and "Fornecedor" in df_out.columns:
        df_out = df_out[df_out["Fornecedor"].isin(fornecedores_sel)]

    return df_out

def montar_df_comparativo(df_base, coluna_data, coluna_valor, data_ini, data_fim, modo_periodo="Personalizado"):
    data_ini = pd.Timestamp(data_ini).normalize()
    data_fim = pd.Timestamp(data_fim).normalize()
    ini_ant, fim_ant, dias_periodo = periodo_anterior(data_ini, data_fim, modo_periodo)

    base_valida   = df_base[df_base[coluna_data].notna()].copy()
    atual_base    = filtrar_intervalo(base_valida, coluna_data, data_ini, data_fim)
    anterior_base = filtrar_intervalo(base_valida, coluna_data, ini_ant, fim_ant)

    datas_atuais    = pd.date_range(data_ini, data_fim, freq="D")
    datas_anteriores = pd.date_range(ini_ant,  fim_ant,  freq="D")

    def _agregar(base, datas, serie):
        s = (
            base.groupby(coluna_data, as_index=True)[coluna_valor]
            .sum()
            .reindex(datas, fill_value=0)
            .rename("Valor")
            .reset_index()
            .rename(columns={"index": "Data_Original"})
        )
        s["Posicao_Dia"]   = range(1, len(s) + 1)
        s["Posicao_Label"] = s["Posicao_Dia"].apply(lambda x: f"D{x:02d}")
        s["Serie"]         = serie
        return s

    atual    = _agregar(atual_base,    datas_atuais,    "Período Atual")
    anterior = _agregar(anterior_base, datas_anteriores, "Período Anterior")

    df_cmp = pd.concat([atual, anterior], ignore_index=True)
    return df_cmp, ini_ant, fim_ant, dias_periodo

def opcoes_unicas(df_base, coluna):
    if coluna not in df_base.columns or df_base.empty:
        return []
    serie = df_base[coluna].dropna()
    serie = serie[serie.astype(str).str.strip() != ""]
    if serie.empty:
        return []
    return sorted(serie.drop_duplicates().tolist(), key=lambda x: str(x))


def limpar_multiselect_invalido(chave, opcoes):
    if chave not in st.session_state:
        return
    opcoes_validas  = set(opcoes)
    valores_atuais  = st.session_state.get(chave, [])
    if not isinstance(valores_atuais, list):
        valores_atuais = []
    st.session_state[chave] = [v for v in valores_atuais if v in opcoes_validas]


def multiselect_dinamico(label, options, key, placeholder):
    limpar_multiselect_invalido(key, options)
    return st.sidebar.multiselect(label, options=options, key=key, placeholder=placeholder)


def aplicar_filtros_para_opcoes(
    df_base, data_ini=None, data_fim=None,
    marketplaces_sel=None, filiais_sel=None, tipos_pedido_sel=None,
    marcas_sel=None, categorias_sel=None, produtos_sel=None, fornecedores_sel=None,
    incluir_devolucao=False, somente_fulfillment=False, ignorar=None,
):
    ignorar = set(ignorar or [])
    marketplaces_sel  = marketplaces_sel  or []
    filiais_sel       = filiais_sel       or []
    tipos_pedido_sel  = tipos_pedido_sel  or []
    marcas_sel        = marcas_sel        or []
    categorias_sel    = categorias_sel    or []
    produtos_sel      = produtos_sel      or []
    fornecedores_sel  = fornecedores_sel  or []

    df_out = df_base.copy()

    if "periodo" not in ignorar and data_ini is not None and data_fim is not None and "Data_Emissao_Filtro" in df_out.columns:
        df_out = filtrar_intervalo(df_out, "Data_Emissao_Filtro", data_ini, data_fim)

    if "devolucao" not in ignorar and "Eh_Devolucao" in df_out.columns:
        if incluir_devolucao:
            df_out = df_out[df_out["Eh_Devolucao"]].copy()
        else:
            df_out = df_out[~df_out["Eh_Devolucao"]].copy()

    if "marketplace" not in ignorar and marketplaces_sel and not incluir_devolucao and "Grupo de Marketplace" in df_out.columns:
        df_out = df_out[df_out["Grupo de Marketplace"].isin(marketplaces_sel)]

    if "filial" not in ignorar and filiais_sel and "Filial_Filtro" in df_out.columns:
        df_out = df_out[df_out["Filial_Filtro"].isin(filiais_sel)]

    if "fulfillment" not in ignorar and somente_fulfillment and "Tipo pedido" in df_out.columns:
        df_out = df_out[df_out["Tipo pedido"].apply(normalizar_texto).str.contains("FULL", na=False)]

    if "tipo_pedido" not in ignorar and not somente_fulfillment and tipos_pedido_sel and "Tipo pedido" in df_out.columns:
        df_out = df_out[df_out["Tipo pedido"].isin(tipos_pedido_sel)]

    if "marca" not in ignorar and marcas_sel and "Marca" in df_out.columns:
        df_out = df_out[df_out["Marca"].isin(marcas_sel)]

    if "categoria" not in ignorar and categorias_sel and "Categoria" in df_out.columns:
        df_out = df_out[df_out["Categoria"].isin(categorias_sel)]
        
    if "produto" not in ignorar and produtos_sel and "Produto_Filtro_Key" in df_out.columns:
        df_out = df_out[df_out["Produto_Filtro_Key"].isin(produtos_sel)]
        
    if "fornecedor" not in ignorar and fornecedores_sel and "Fornecedor" in df_out.columns:
        df_out = df_out[df_out["Fornecedor"].isin(fornecedores_sel)]

    return df_out

@st.cache_data(ttl=1800, show_spinner="Carregando e tratando dados do Google Sheets...")
def carregar_e_tratar_dados(_conn, url_planilha):
    df_base = _conn.read(spreadsheet=url_planilha, ttl=0).copy()
    df_base.columns = [str(c).strip() for c in df_base.columns]

    if "SKU" in df_base.columns:
        df_base["SKU"] = df_base["SKU"].apply(normalizar_sku)

    if "Código" in df_base.columns or "Produto" in df_base.columns or "Descrição" in df_base.columns or "Descricao" in df_base.columns or "SKU" in df_base.columns:
        df_base["Produto_Filtro_Key"] = df_base.apply(montar_key_produto_filtro, axis=1)
        df_base["Produto_Filtro_Label"] = df_base.apply(montar_label_produto_filtro, axis=1)
    else:
        df_base["Produto_Filtro_Key"] = ""
        df_base["Produto_Filtro_Label"] = ""

    if "Filial" in df_base.columns:
        df_base["Filial_Filtro"] = df_base["Filial"].apply(normalizar_filial)
    else:
        df_base["Filial_Filtro"] = ""

    for col_orig, col_num in [
        ("Receita",     "Receita_Num"),
        ("Liquido",     "Liquido_Num"),
        ("Custo medio", "Custo_Num"),
    ]:
        df_base[col_num] = df_base[col_orig].apply(limpar_moeda) if col_orig in df_base.columns else 0.0

    df_base["Qtd_Num"] = pd.to_numeric(df_base.get("Quantidade vendida"), errors="coerce").fillna(0)

    df_base["Data_Emissao_Filtro"] = parse_data_coluna(df_base, "Data emissao")
    df_base["Data_Venda_Pura"]     = parse_data_coluna(df_base, "Data da Venda")

    df_base["Data_Grafico"] = df_base["Data_Venda_Pura"].where(
        df_base["Data_Venda_Pura"].notna(), df_base["Data_Emissao_Filtro"]
    )
    df_base["Dia_Grafico"] = pd.to_datetime(df_base["Data_Grafico"], errors="coerce").dt.normalize()

    df_base["Eh_Devolucao"] = (
        df_base["Grupo de Marketplace"].apply(normalizar_texto).str.contains("DEVOLUCAO", na=False)
        if "Grupo de Marketplace" in df_base.columns else False
    )

    for col_num in ["Receita_Num", "Liquido_Num", "Custo_Num", "Qtd_Num"]:
        df_base.loc[df_base["Eh_Devolucao"], col_num] = df_base.loc[df_base["Eh_Devolucao"], col_num].abs()

    df_base["img_url"] = df_base.apply(build_img_url, axis=1)
    return df_base

def montar_resumo_periodos_grafico(df_atual, df_anterior, data_ini, data_fim, ini_ant, fim_ant):
    def calcular_numeros(df_periodo):
        receita   = df_periodo["Receita_Num"].sum()   if "Receita_Num"   in df_periodo.columns else 0.0
        liquido   = df_periodo["Liquido_Num"].sum()   if "Liquido_Num"   in df_periodo.columns else 0.0
        custo     = df_periodo["Custo_Num"].sum()     if "Custo_Num"     in df_periodo.columns else 0.0
        quantidade = df_periodo["Qtd_Num"].sum()      if "Qtd_Num"       in df_periodo.columns else 0.0
        margem    = calcular_margem_pct(liquido, custo)
        ticket    = receita / quantidade if quantidade > 0 else 0.0
        return {"receita": receita, "liquido": liquido, "custo": custo, "quantidade": quantidade, "margem": margem, "ticket_medio": ticket}

    def var(a, b):
        a, b = float(a or 0), float(b or 0)
        if b == 0:
            return "0,0%" if a == 0 else "Novo"
        v = ((a - b) / abs(b)) * 100
        return f"{v:+.1f}%".replace(".", ",")

    def var_pct(a, b):
        a, b = float(a or 0), float(b or 0)
        d = (a - b) * 100
        if d > 0:   return f"+{d:.1f}%".replace(".", ",")
        if d < 0:   return f"{d:.1f}%".replace(".", ",")
        return "0,0%"

    at  = calcular_numeros(df_atual)
    ant = calcular_numeros(df_anterior)

    return pd.DataFrame([
        {"Período": "Período Atual",    "Intervalo": f"{pd.Timestamp(data_ini).strftime('%d/%m/%Y')} até {pd.Timestamp(data_fim).strftime('%d/%m/%Y')}", "Receita Bruta": formatar_brl(at["receita"]),  "Líquido": formatar_brl(at["liquido"]),  "Custo": formatar_brl(at["custo"]),  "Quantidade": formatar_int(at["quantidade"]),  "Margem": formatar_pct(at["margem"]),  "Ticket Médio": formatar_brl(at["ticket_medio"])},
        {"Período": "Período Anterior", "Intervalo": f"{pd.Timestamp(ini_ant).strftime('%d/%m/%Y')} até {pd.Timestamp(fim_ant).strftime('%d/%m/%Y')}",   "Receita Bruta": formatar_brl(ant["receita"]), "Líquido": formatar_brl(ant["liquido"]), "Custo": formatar_brl(ant["custo"]), "Quantidade": formatar_int(ant["quantidade"]), "Margem": formatar_pct(ant["margem"]), "Ticket Médio": formatar_brl(ant["ticket_medio"])},
        {"Período": "Variação",         "Intervalo": "Atual x Anterior",                                                                                  "Receita Bruta": var(at["receita"], ant["receita"]), "Líquido": var(at["liquido"], ant["liquido"]), "Custo": var(at["custo"], ant["custo"]), "Quantidade": var(at["quantidade"], ant["quantidade"]), "Margem": var_pct(at["margem"], ant["margem"]), "Ticket Médio": var(at["ticket_medio"], ant["ticket_medio"])},
    ])

def preparar_tabela_resumo_periodos(df_resumo):
    df_tabela = df_resumo.drop(columns=["Intervalo"], errors="ignore").copy()
    if df_tabela.empty or "Período" not in df_tabela.columns:
        return df_tabela

    def fmt_variacao(valor):
        t = str(valor).strip()
        if t == "Novo":     return f":green[▲ {t}]"
        if t.startswith("+"): return f":green[▲ {t}]"
        if t.startswith("-"): return f":red[▼ {t}]"
        return f":gray[▬ {t}]"

    def fmt_periodo(valor):
        t = str(valor).strip()
        if t == "Período Atual":    return ":material/trending_up: **Período Atual**"
        if t == "Período Anterior": return ":material/history: Período Anterior"
        if t == "Variação":         return ":material/percent: Variação"
        return t

    df_tabela["Período"] = df_tabela["Período"].apply(fmt_periodo)
    mask = df_resumo["Período"].astype(str).str.strip().eq("Variação")

    for col in df_tabela.columns:
        if col == "Período":
            continue
        df_tabela.loc[mask, col] = df_tabela.loc[mask, col].apply(fmt_variacao)

    return df_tabela

def montar_resumo_marketplace_tipo_pedido(df_base, filtro_mkt_ativo=False):
    if df_base.empty:
        return pd.DataFrame()

    colunas_necessarias = [
        "Grupo de Marketplace",
        "Receita_Num",
        "Liquido_Num",
        "Custo_Num",
        "Qtd_Num",
    ]

    if not all(col in df_base.columns for col in colunas_necessarias):
        return pd.DataFrame()

    base = df_base[
        df_base["Grupo de Marketplace"].notna() &
        (df_base["Grupo de Marketplace"].astype(str).str.strip() != "")
    ].copy()

    if base.empty:
        return pd.DataFrame()

    detalhar_tipo_pedido = (
        filtro_mkt_ativo and
        "Tipo pedido" in base.columns
    )

    if detalhar_tipo_pedido:
        base["Tipo pedido"] = base["Tipo pedido"].fillna("").astype(str).str.strip()
        base.loc[base["Tipo pedido"] == "", "Tipo pedido"] = "Não informado"

        campos_grupo = ["Grupo de Marketplace", "Tipo pedido"]
    else:
        campos_grupo = ["Grupo de Marketplace"]

    resumo = (
        base.groupby(campos_grupo, as_index=False)
        .agg(
            Receita=("Receita_Num", "sum"),
            Liquido=("Liquido_Num", "sum"),
            Custo=("Custo_Num", "sum"),
            Quantidade=("Qtd_Num", "sum"),
        )
    )

    if resumo.empty:
        return pd.DataFrame()

    total_receita = float(resumo["Receita"].sum())

    resumo["Margem_Pct"] = resumo.apply(
        lambda row: calcular_margem_pct(row["Liquido"], row["Custo"]),
        axis=1
    )

    resumo["Ticket_Medio"] = resumo.apply(
        lambda row: (row["Receita"] / row["Quantidade"]) if row["Quantidade"] > 0 else 0.0,
        axis=1
    )

    resumo["Percentual_Total"] = resumo["Receita"].apply(
        lambda x: (x / total_receita) if total_receita > 0 else 0.0
    )

    if detalhar_tipo_pedido:
        resumo["Receita_Total_Marketplace"] = resumo.groupby("Grupo de Marketplace")["Receita"].transform("sum")

        resumo = resumo.sort_values(
            by=["Receita_Total_Marketplace", "Grupo de Marketplace", "Receita"],
            ascending=[False, True, False]
        ).reset_index(drop=True)
    else:
        resumo = resumo.sort_values(
            by="Receita",
            ascending=False
        ).reset_index(drop=True)

    resumo["Marketplace"] = resumo["Grupo de Marketplace"]
    resumo["% do Total"] = resumo["Percentual_Total"].apply(formatar_pct)
    resumo["Receita Bruta"] = resumo["Receita"].apply(formatar_brl)
    resumo["Líquido"] = resumo["Liquido"].apply(formatar_brl)
    resumo["Custo"] = resumo["Custo"].apply(formatar_brl)
    resumo["Quantidade"] = resumo["Quantidade"].apply(formatar_int)
    resumo["Margem"] = resumo["Margem_Pct"].apply(formatar_pct)
    resumo["Ticket Médio"] = resumo["Ticket_Medio"].apply(formatar_brl)

    if detalhar_tipo_pedido:
        resumo["Tipo de Pedido"] = resumo["Tipo pedido"]

        return resumo[
            [
                "Marketplace",
                "Tipo de Pedido",
                "% do Total",
                "Receita Bruta",
                "Líquido",
                "Custo",
                "Quantidade",
                "Margem",
                "Ticket Médio",
            ]
        ]

    return resumo[
        [
            "Marketplace",
            "% do Total",
            "Receita Bruta",
            "Líquido",
            "Custo",
            "Quantidade",
            "Margem",
            "Ticket Médio",
        ]
    ]


def preparar_tabela_resumo_marketplace_tipo_pedido(df_resumo, filtro_mkt_ativo=False):
    df_tabela = df_resumo.copy()

    if df_tabela.empty:
        return df_tabela

    if "Marketplace" in df_tabela.columns:
        df_tabela["Marketplace"] = df_tabela["Marketplace"].apply(
            lambda x: f":material/storefront: {x}"
        )

    if filtro_mkt_ativo and "Tipo de Pedido" in df_tabela.columns:
        df_tabela["Tipo de Pedido"] = df_tabela["Tipo de Pedido"].apply(
            lambda x: f":material/receipt_long: {x}"
        )

    return df_tabela

def montar_resumo_fornecedor(df_base):
    if df_base.empty:
        return pd.DataFrame()

    colunas_necessarias = [
        "Fornecedor",
        "Receita_Num",
        "Liquido_Num",
        "Custo_Num",
        "Qtd_Num",
    ]

    if not all(col in df_base.columns for col in colunas_necessarias):
        return pd.DataFrame()

    base = df_base[
        df_base["Fornecedor"].notna() &
        (df_base["Fornecedor"].astype(str).str.strip() != "")
    ].copy()

    if base.empty:
        return pd.DataFrame()

    resumo = (
        base.groupby("Fornecedor", as_index=False)
        .agg(
            Receita=("Receita_Num", "sum"),
            Liquido=("Liquido_Num", "sum"),
            Custo=("Custo_Num", "sum"),
            Quantidade=("Qtd_Num", "sum"),
        )
    )

    if resumo.empty:
        return pd.DataFrame()

    total_receita = float(resumo["Receita"].sum())

    resumo["Margem_Pct"] = resumo.apply(
        lambda row: calcular_margem_pct(row["Liquido"], row["Custo"]),
        axis=1
    )

    resumo["Ticket_Medio"] = resumo.apply(
        lambda row: (row["Receita"] / row["Quantidade"]) if row["Quantidade"] > 0 else 0.0,
        axis=1
    )

    resumo["Percentual_Total"] = resumo["Receita"].apply(
        lambda x: (x / total_receita) if total_receita > 0 else 0.0
    )

    resumo = resumo.sort_values(
        by="Receita",
        ascending=False
    ).reset_index(drop=True)

    resumo["% do Total"] = resumo["Percentual_Total"].apply(formatar_pct)
    resumo["Receita Bruta"] = resumo["Receita"].apply(formatar_brl)
    resumo["Líquido"] = resumo["Liquido"].apply(formatar_brl)
    resumo["Custo"] = resumo["Custo"].apply(formatar_brl)
    resumo["Quantidade"] = resumo["Quantidade"].apply(formatar_int)
    resumo["Margem"] = resumo["Margem_Pct"].apply(formatar_pct)
    resumo["Ticket Médio"] = resumo["Ticket_Medio"].apply(formatar_brl)

    return resumo[
        [
            "Fornecedor",
            "% do Total",
            "Receita Bruta",
            "Líquido",
            "Custo",
            "Quantidade",
            "Margem",
            "Ticket Médio",
        ]
    ]


def preparar_tabela_resumo_fornecedor(df_resumo):
    df_tabela = df_resumo.copy()

    if df_tabela.empty:
        return df_tabela

    if "Fornecedor" in df_tabela.columns:
        df_tabela["Fornecedor"] = df_tabela["Fornecedor"].apply(
            lambda x: f":material/warehouse: {truncar_texto(x, 23)}"
        )

    return df_tabela


# ──────────────────────────────────────────────
# 5. CARGA E TRATAMENTO DOS DADOS
# ──────────────────────────────────────────────
try:
    df = carregar_e_tratar_dados(conn, url_planilha).copy()

    colunas_necessarias = ["Grupo de Marketplace", "Tipo pedido", "Data emissao"]
    if not all(col in df.columns for col in colunas_necessarias):
        st.error("Colunas obrigatórias não encontradas. Verifique a planilha.")
        st.write("Colunas detectadas:", df.columns.tolist())
        st.stop()

    # ──────────────────────────────────────────
    # 6. FILTROS LATERAIS
    # ──────────────────────────────────────────
    st.sidebar.header("Filtros")

    if st.sidebar.button("Atualizar dados"):
        carregar_e_tratar_dados.clear()
        for chave in ["periodo_datas", "periodo_rapido"]:
            if chave in st.session_state:
                del st.session_state[chave]
        st.rerun()

    # 6.1 PREPARO DO PERÍODO
    data_ini = None
    data_fim = None
    periodo_rapido = "Personalizado"

    datas_validas = df["Data_Emissao_Filtro"].dropna()

    if not datas_validas.empty:
        data_min = datas_validas.min().date()
        data_max = datas_validas.max().date()
        data_ref = data_max
        inicio_mes_ref = pd.Timestamp(data_ref).replace(day=1).date()
        default_ini = max(data_min, inicio_mes_ref)
        default_fim = data_ref
        if default_ini > default_fim:
            default_ini = data_min
            default_fim = data_max

        if "periodo_rapido" not in st.session_state:
            st.session_state["periodo_rapido"] = "Mês Atual"
        if "periodo_datas" not in st.session_state:
            st.session_state["periodo_datas"] = (default_ini, default_fim)

        periodo_estado = st.session_state.get("periodo_datas", (default_ini, default_fim))
        if isinstance(periodo_estado, (list, tuple)) and len(periodo_estado) == 2:
            data_ini_opcoes = pd.Timestamp(periodo_estado[0]).normalize()
            data_fim_opcoes = pd.Timestamp(periodo_estado[1]).normalize()
        else:
            data_ini_opcoes = pd.Timestamp(default_ini).normalize()
            data_fim_opcoes = pd.Timestamp(default_fim).normalize()
    else:
        data_min = data_max = data_ref = None
        data_ini_opcoes = data_fim_opcoes = None

    # 6.2 ESTADO ATUAL DOS FILTROS
    mkt_atual              = st.session_state.get("filtro_marketplace",          [])
    filial_atual           = st.session_state.get("filtro_filial",               [])
    tipo_pedido_atual      = st.session_state.get("filtro_tipo_pedido",          [])
    marca_atual            = st.session_state.get("filtro_marca",                [])
    categoria_atual        = st.session_state.get("filtro_categoria",            [])
    produto_atual          = st.session_state.get("filtro_produto",              [])
    fornecedor_atual       = st.session_state.get("filtro_fornecedor",           [])
    somente_fulfillment_atual = bool(st.session_state.get("filtro_somente_fulfillment", False))
    incluir_devolucao_atual   = bool(st.session_state.get("filtro_somente_devolucao",  False))

    # 6.3 BASE PARA OPÇÕES DINÂMICAS
    def base_para_opcoes(ignorar):
        return aplicar_filtros_para_opcoes(
            df_base=df,
            data_ini=data_ini_opcoes,
            data_fim=data_fim_opcoes,
            marketplaces_sel=mkt_atual,
            filiais_sel=filial_atual,
            tipos_pedido_sel=tipo_pedido_atual,
            marcas_sel=marca_atual,
            categorias_sel=categoria_atual,
            produtos_sel=produto_atual,
            fornecedores_sel=fornecedor_atual,
            incluir_devolucao=incluir_devolucao_atual,
            somente_fulfillment=somente_fulfillment_atual,
            ignorar=ignorar,
        )

    # 6.4 FILTROS DINÂMICOS

    # Marketplace não será exibido como filtro lateral nesta nova organização.
    # Mantém a variável definida para não quebrar os blocos que ainda usam mkt_sel.
    mkt_sel = []

    somente_fulfillment = st.sidebar.toggle(
        "Somente Fulfillment",
        value=False,
        key="filtro_somente_fulfillment"
    )

    incluir_devolucao = st.sidebar.toggle(
        "Somente Devolução",
        value=False,
        key="filtro_somente_devolucao"
    )

    somente_margem_negativa = st.sidebar.toggle(
        "Somente Margem Negativa",
        value=False,
        key="filtro_somente_margem_negativa"
    )

    filiais_validas_base = opcoes_unicas(
        base_para_opcoes(["filial"]),
        "Filial_Filtro"
    )

    filiais_lista_base = ["00001", "00008", "00016", "20301"]

    filiais_lista = [
        f for f in filiais_lista_base
        if f in filiais_validas_base
    ]

    filial_sel = multiselect_dinamico(
        "Filial",
        options=filiais_lista,
        key="filtro_filial",
        placeholder="Todas as filiais"
    )

    fornecedor_lista = opcoes_unicas(
        base_para_opcoes(["fornecedor"]),
        "Fornecedor"
    )

    fornecedor_sel = multiselect_dinamico(
        "Fornecedor",
        options=fornecedor_lista,
        key="filtro_fornecedor",
        placeholder="Todos os fornecedores"
    )

    mkt_lista = opcoes_unicas(
        base_para_opcoes(["marketplace"]),
        "Grupo de Marketplace"
    )

    mkt_sel = multiselect_dinamico(
        "Marketplace",
        options=mkt_lista,
        key="filtro_marketplace",
        placeholder="Todos os marketplaces"
    )

    tipo_pedido_lista = opcoes_unicas(
        base_para_opcoes(["tipo_pedido"]),
        "Tipo pedido"
    )

    tipo_pedido_sel = multiselect_dinamico(
        "Tipo de Pedido",
        options=tipo_pedido_lista,
        key="filtro_tipo_pedido",
        placeholder="Todos os tipos de pedido"
    )

    marca_lista = opcoes_unicas(
        base_para_opcoes(["marca"]),
        "Marca"
    )

    marca_sel = multiselect_dinamico(
        "Marca",
        options=marca_lista,
        key="filtro_marca",
        placeholder="Todas as marcas"
    )

    categoria_lista = opcoes_unicas(
        base_para_opcoes(["categoria"]),
        "Categoria"
    )

    categoria_sel = multiselect_dinamico(
        "Categoria",
        options=categoria_lista,
        key="filtro_categoria",
        placeholder="Todas as categorias"
    )

    produto_keys, produto_labels = montar_opcoes_produto_filtro(
        base_para_opcoes(["produto"])
    )

    limpar_multiselect_invalido(
        "filtro_produto",
        produto_keys
    )

    produto_sel = st.sidebar.multiselect(
        "Produto",
        options=produto_keys,
        key="filtro_produto",
        placeholder="Todos os produtos",
        format_func=lambda key: produto_labels.get(key, key),
    )
    
    # 6.5 FILTRO DE PERÍODO
    if not datas_validas.empty:
        st.sidebar.markdown("**Período Rápido**")

        periodo_rapido = st.sidebar.radio(
            "Selecione um atalho",
            options=["Mês Atual", "Últimos 7 dias", "Últimos 15 dias", "Últimos 30 dias", "Personalizado"],
            key="periodo_rapido",
            label_visibility="collapsed",
            horizontal=False,
        )

        if periodo_rapido == "Mês Atual":
            st.session_state["periodo_datas"] = (default_ini, default_fim)
        elif periodo_rapido == "Últimos 7 dias":
            _i = max((pd.Timestamp(data_ref) - pd.Timedelta(days=6)).date(), data_min)
            st.session_state["periodo_datas"] = (_i, data_ref)
        elif periodo_rapido == "Últimos 15 dias":
            _i = max((pd.Timestamp(data_ref) - pd.Timedelta(days=14)).date(), data_min)
            st.session_state["periodo_datas"] = (_i, data_ref)
        elif periodo_rapido == "Últimos 30 dias":
            _i = max((pd.Timestamp(data_ref) - pd.Timedelta(days=29)).date(), data_min)
            st.session_state["periodo_datas"] = (_i, data_ref)

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

        st.sidebar.caption(f"Última data na base: {pd.Timestamp(data_ref).strftime('%d/%m/%Y')}")
    else:
        data_ini = data_fim = None

    # ──────────────────────────────────────────
    # 7. BASE FILTRADA
    # ──────────────────────────────────────────
    df_dim = aplicar_filtros_dimensionais(
        df_base=df,
        marketplaces_sel=mkt_sel,
        filiais_sel=filial_sel,
        tipos_pedido_sel=tipo_pedido_sel,
        marcas_sel=marca_sel,
        categorias_sel=categoria_sel,
        produtos_sel=produto_sel,
        fornecedores_sel=fornecedor_sel,
        incluir_devolucao=incluir_devolucao,
        somente_fulfillment=somente_fulfillment,
    )

    if data_ini is not None and data_fim is not None:
        df_f     = filtrar_intervalo(df_dim, "Data_Emissao_Filtro", data_ini, data_fim)
        ini_ant, fim_ant, dias_periodo = periodo_anterior(data_ini, data_fim, periodo_rapido)
        df_prev  = filtrar_intervalo(df_dim, "Data_Emissao_Filtro", ini_ant, fim_ant)
    else:
        df_f    = df_dim.copy()
        df_prev = df_dim.iloc[0:0].copy()
        ini_ant = fim_ant = None
        dias_periodo = 0

    if incluir_devolucao and data_fim is not None:
        df_vendas_60d = filtrar_base_vendas_60d(
            df_base=df, data_fim=data_fim,
            filiais_sel=filial_sel, tipos_pedido_sel=tipo_pedido_sel,
            marcas_sel=marca_sel, categorias_sel=categoria_sel,
            fornecedores_sel=fornecedor_sel, somente_fulfillment=somente_fulfillment,
        )
    else:
        df_vendas_60d = df.iloc[0:0].copy()

    df_grafico_base = df_dim.copy() if (data_ini is not None and data_fim is not None) else df_dim.iloc[0:0].copy()

    # ──────────────────────────────────────────
    # 8. CABEÇALHO
    # ──────────────────────────────────────────
    col_logo, col_titulo = st.columns([0.8, 4.2])
    with col_logo:
        st.image(LOGO_PATH, width=180)
    with col_titulo:
        st.title("Dashboard de Performance de Vendas")
        st.caption(
            f"{len(df_f):,} linhas no detalhamento filtradas por Data emissao | "
            f"Gráfico comparativo calculado por Data da Venda com fallback para Data emissao"
        )

    # ──────────────────────────────────────────
    # 9. CSS  (mobile-first)
    # ──────────────────────────────────────────
    st.markdown(
        """
        <style>
        /* ── MÉTRICAS ──────────────────────────────── */
        div[data-testid="stMetric"] {
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(128,128,128,0.18);
            border-radius: 12px;
            padding: 14px 16px;
        }
        div[data-testid="stMetricLabel"] { font-size: 0.95rem; }
        div[data-testid="stMetricValue"] { font-size: 1.45rem; line-height: 1.15; }

        /* ── CONTÊINER DOS GRÁFICOS ALTAIR ────────── */
        /*
         * Permite scroll horizontal nos gráficos de barras fixas
         * (chart_bar, chart_fornecedor) sem quebrar os responsivos.
         * O wrapper é adicionado via st.markdown nos pontos de renderização.
         */
        .chart-scroll-wrapper {
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            width: 100%;
        }

        /* ── RANKING CARDS ─────────────────────────── */
        .ranking-card {
            border: 1px solid rgba(128,128,128,0.18);
            border-radius: 16px;
            padding: 12px 14px;
            margin-bottom: 12px;
            background: transparent;
        }
        .ranking-card-grid {
            display: grid;
            grid-template-columns: 44px 72px minmax(0, 1fr) 227px;
            gap: 12px;
            align-items: center;
        }
        .ranking-pos { font-size: 1rem; font-weight: 700; color: #334155; text-align: center; }
        .ranking-img-wrap {
            width: 72px; height: 72px;
            border-radius: 12px;
            border: 1px solid rgba(128,128,128,0.16);
            display: flex; align-items: center; justify-content: center;
            overflow: hidden; background: rgba(255,255,255,0.02);
        }
        .ranking-img-wrap img { width: 100%; height: 100%; object-fit: contain; display: block; }
        .ranking-title    { font-size: 1rem; font-weight: 700; line-height: 1.25; word-break: break-word; }
        .ranking-subtitle { font-size: 0.88rem; color: #64748b; margin-top: 4px; word-break: break-word; }

        .ranking-metrics {
            display: flex; flex-direction: column; gap: 8px;
            align-items: flex-end; text-align: right; white-space: nowrap;
            padding: 10px 12px; border-radius: 12px;
            border: 1px solid rgba(128,128,128,0.14);
            width: 227px; max-width: 227px; justify-self: end;
            min-width: 0; box-sizing: border-box;
        }
        .ranking-metrics > div:not(.ranking-chips-row) { width: 100%; text-align: right; }
        .ranking-metrics strong { font-weight: 700; }

        .ranking-chips-row {
            display: flex; flex-direction: row; gap: 6px;
            justify-content: space-between; align-items: center;
            flex-wrap: nowrap; white-space: nowrap;
            width: 100%; text-align: center; align-self: center;
        }
        .ranking-chip {
            display: inline-flex; align-items: center; justify-content: center;
            padding: 4px 7px; border-radius: 999px;
            font-size: 0.74rem; line-height: 1.2; white-space: nowrap; box-sizing: border-box;
        }

        /* ── RESPONSIVO ──────────────────────────────── */
        @media (max-width: 1100px) {
            .ranking-card-grid { grid-template-columns: 44px 72px minmax(0, 1fr) 227px; }
            .ranking-chip { font-size: 0.72rem; padding: 4px 6px; }
        }

        @media (max-width: 900px) {
            /* Ranking: colapsa métricas para linha extra */
            .ranking-card-grid { grid-template-columns: 40px 64px minmax(0, 1fr); }
            .ranking-img-wrap  { width: 64px; height: 64px; }
            .ranking-metrics {
                grid-column: 1 / -1; margin-top: 8px;
                width: 100%; max-width: 100%; justify-self: stretch;
                align-items: flex-end; text-align: right; white-space: normal;
            }
            .ranking-metrics > div:not(.ranking-chips-row) { text-align: left; }
            .ranking-chips-row { justify-content: left; flex-wrap: wrap; white-space: normal; }
        }

        @media (max-width: 480px) {
            .ranking-card { padding: 10px 12px; }
            .ranking-card-grid { grid-template-columns: 34px 56px minmax(0, 1fr); gap: 10px; }
            .ranking-pos  { font-size: 0.9rem; }
            .ranking-img-wrap  { width: 56px; height: 56px; border-radius: 10px; }
            .ranking-title     { font-size: 0.95rem; }
            .ranking-subtitle  { font-size: 0.82rem; }
            .ranking-metrics   { padding: 10px; gap: 7px; align-items: flex-end; text-align: right; }
            .ranking-metrics > div:not(.ranking-chips-row) { text-align: left; }
            .ranking-chips-row { justify-content: left; flex-wrap: wrap; }
            .ranking-chip { font-size: 0.72rem; padding: 4px 6px; }

            /* Métricas principais: reduz fonte no mobile */
            div[data-testid="stMetricValue"] { font-size: 1.15rem; }
            div[data-testid="stMetricLabel"] { font-size: 0.82rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ──────────────────────────────────────────
    # 10. MÉTRICAS PRINCIPAIS
    # ──────────────────────────────────────────
    receita_total   = df_f["Receita_Num"].sum()
    liquido_total   = df_f["Liquido_Num"].sum()
    custo_total     = df_f["Custo_Num"].sum()
    qtd_total       = int(df_f["Qtd_Num"].sum())
    total_pedidos   = len(df_f)

    receita_anterior  = df_prev["Receita_Num"].sum()
    liquido_anterior  = df_prev["Liquido_Num"].sum()
    custo_anterior    = df_prev["Custo_Num"].sum()
    qtd_anterior      = int(df_prev["Qtd_Num"].sum())
    pedidos_anterior  = len(df_prev)

    margem_total    = calcular_margem_pct(liquido_total,    custo_total)
    margem_anterior = calcular_margem_pct(liquido_anterior, custo_anterior)

    ticket_medio          = (receita_total   / qtd_total)   if qtd_total   > 0 else 0.0
    ticket_medio_anterior = (receita_anterior / qtd_anterior) if qtd_anterior > 0 else 0.0

    if "Fornecedor" in df_f.columns:
        receita_lotes = df_f.loc[df_f["Fornecedor"].apply(normalizar_texto) == "LOTES", "Receita_Num"].sum()
    else:
        receita_lotes = 0.0

    pct_receita_lotes        = (receita_lotes / receita_total)     if receita_total > 0 else 0.0
    pct_receita_complementar = 1 - pct_receita_lotes               if receita_total > 0 else 0.0

    info_proj      = calcular_status_e_projecao(data_ini=data_ini, data_fim=data_fim, total_atual=receita_total)
    rotulo_itens   = "Itens Devolvidos" if incluir_devolucao else "Itens Vendidos"

    linha1 = st.columns(5)
    linha2 = st.columns(5)

    linha1[0].metric("Receita Total",  formatar_brl(receita_total),  calcular_delta_percentual(receita_total, receita_anterior))
    linha1[1].metric("Líquido Total",  formatar_brl(liquido_total),  calcular_delta_percentual(liquido_total, liquido_anterior))
    linha1[2].metric("Custo Total",    formatar_brl(custo_total),    calcular_delta_percentual(custo_total, custo_anterior))
    linha1[3].metric("Margem",         formatar_pct(margem_total),   calcular_delta_pontos_percentuais(margem_total, margem_anterior))
    linha1[4].metric("Ticket Médio",   formatar_brl(ticket_medio),   calcular_delta_percentual(ticket_medio, ticket_medio_anterior))

    linha2[0].metric(rotulo_itens,     formatar_int(qtd_total),      calcular_delta_percentual(qtd_total, qtd_anterior))
    linha2[1].metric("Total de Pedidos", formatar_int(total_pedidos), calcular_delta_percentual(total_pedidos, pedidos_anterior))

    if info_proj["status"] == "em_andamento":
        linha2[2].metric("Projeção do Mês", formatar_brl(info_proj["projecao"]))
    elif info_proj["status"] == "finalizado":
        linha2[2].metric("Projeção do Mês", "Mês finalizado")
    else:
        linha2[2].metric("Projeção do Mês", "N/D")

    linha2[3].metric("Receita Novos", formatar_pct(pct_receita_complementar))
    linha2[4].metric("Receita Lotes", formatar_pct(pct_receita_lotes))

    if info_proj["status"] == "em_andamento":
        st.caption(
            f"Período anterior: {ini_ant.strftime('%d/%m/%Y')} até {fim_ant.strftime('%d/%m/%Y')} | "
            f"Projeção: {info_proj['dias_passados']} dias passados, {info_proj['dias_restantes']} restantes, {info_proj['dias_mes']} no mês."
        )
    elif info_proj["status"] == "finalizado":
        st.caption(f"Período anterior: {ini_ant.strftime('%d/%m/%Y')} até {fim_ant.strftime('%d/%m/%Y')}")
    elif info_proj["status"] == "intervalo_parcial":
        st.caption(
            f"Período anterior: {ini_ant.strftime('%d/%m/%Y')} até {fim_ant.strftime('%d/%m/%Y')} | "
            f"Para projetar o mês atual, o filtro precisa cobrir o mês desde o dia 1 até ontem."
        )
    elif info_proj["status"] == "multiplos_meses":
        st.caption("A projeção mensal funciona apenas quando o filtro está dentro de um único mês.")
    elif info_proj["status"] == "futuro":
        st.caption("O período selecionado está em um mês futuro.")

    # ──────────────────────────────────────────
    # 11. GRÁFICO: VENDAS POR DIA COM COMPARATIVO
    # ──────────────────────────────────────────
    st.subheader("Vendas por Dia com Comparativo do Período Anterior")

    if (
        data_ini is not None and data_fim is not None and
        not df_grafico_base.empty and
        "Dia_Grafico" in df_grafico_base.columns and
        df_grafico_base["Dia_Grafico"].notna().any()
    ):
        df_cmp, ini_ant_chart, fim_ant_chart, _ = montar_df_comparativo(
            df_base=df_grafico_base,
            coluna_data="Dia_Grafico",
            coluna_valor="Receita_Num",
            data_ini=data_ini,
            data_fim=data_fim,
            modo_periodo=periodo_rapido,
        )

        df_resumo_periodos = montar_resumo_periodos_grafico(
            df_f,
            df_prev,
            data_ini,
            data_fim,
            ini_ant,
            fim_ant
        )

        df_resumo_periodos_tabela = preparar_tabela_resumo_periodos(
            df_resumo_periodos
        )

        aba_grafico, aba_detalhamento = st.tabs(["Gráfico", "Detalhamento"])

        with aba_grafico:
            st.altair_chart(
                criar_grafico_comparativo(df_cmp),
                use_container_width=True
            )

            st.caption(
                f"Período atual: {data_ini.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')} | "
                f"Período anterior: {ini_ant_chart.strftime('%d/%m/%Y')} até {fim_ant_chart.strftime('%d/%m/%Y')} | "
                f"Comparação alinhada pelo dia dentro do período"
            )

        with aba_detalhamento:
            st.caption(
                "Resumo comparativo entre o período atual e o período anterior usado no gráfico."
            )

            st.table(
                df_resumo_periodos_tabela,
                border="horizontal",
                hide_index=True
            )

            with st.expander("Ver intervalos comparados"):
                st.dataframe(
                    df_resumo_periodos[["Período", "Intervalo"]],
                    use_container_width=True,
                    hide_index=True
                )

    else:
        st.info("Sem dados de Data da Venda disponíveis para o período selecionado.")

    st.divider()

    # ──────────────────────────────────────────
    # 11.1 GRÁFICO: LOTES X NOVOS
    # ──────────────────────────────────────────
    st.subheader("Receita Lotes x Receita Novos por Dia")

    if (
        data_ini is not None and data_fim is not None and
        not df_grafico_base.empty and
        "Dia_Grafico" in df_grafico_base.columns and
        df_grafico_base["Dia_Grafico"].notna().any()
    ):
        df_lotes_comp = montar_df_lotes_complementar(df_grafico_base, data_ini, data_fim)

        if not df_lotes_comp.empty:
            aba_grafico_lotes, aba_detalhamento_lotes = st.tabs(
                ["Gráfico", "Detalhamento"]
            )

            with aba_grafico_lotes:
                st.altair_chart(
                    criar_grafico_lotes_complementar(df_lotes_comp),
                    use_container_width=True
                )

                st.caption(
                    f"Período: {data_ini.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')} | "
                    f"Comparação diária entre Receita Novos e Receita Lotes"
                )

            with aba_detalhamento_lotes:
                df_resumo_lotes_novos = montar_resumo_lotes_novos_grafico(
                    df_grafico_base,
                    data_ini,
                    data_fim
                )

                df_resumo_lotes_novos_tabela = preparar_tabela_resumo_lotes_novos(
                    df_resumo_lotes_novos
                )

                st.caption(
                    "Resumo comparativo entre Novos e Lotes no período selecionado."
                )

                st.table(
                    df_resumo_lotes_novos_tabela,
                    border="horizontal",
                    hide_index=True
                )

                with st.expander("Ver detalhamento diário"):
                    df_diario_lotes_novos = (
                        df_lotes_comp
                        .pivot_table(
                            index="Data_Original",
                            columns="Serie",
                            values="Valor",
                            aggfunc="sum",
                            fill_value=0
                        )
                        .reset_index()
                    )

                    df_diario_lotes_novos["Data"] = df_diario_lotes_novos["Data_Original"].apply(
                        lambda x: pd.Timestamp(x).strftime("%d/%m/%Y")
                    )

                    for col in ["Receita Novos", "Receita Lotes"]:
                        if col not in df_diario_lotes_novos.columns:
                            df_diario_lotes_novos[col] = 0.0

                        df_diario_lotes_novos[col] = df_diario_lotes_novos[col].apply(
                            formatar_brl
                        )

                    df_diario_lotes_novos = df_diario_lotes_novos[
                        [
                            "Data",
                            "Receita Novos",
                            "Receita Lotes",
                        ]
                    ]

                    st.dataframe(
                        df_diario_lotes_novos,
                        use_container_width=True,
                        hide_index=True
                    )

        else:
            st.info("Sem dados para exibir o gráfico de Lotes x Novos no período selecionado.")

    else:
        st.info("Sem dados válidos para exibir o gráfico de Lotes x Novos.")

    # ──────────────────────────────────────────
    # 12. GRÁFICO: RECEITA POR MARKETPLACE POR DIA
    # ──────────────────────────────────────────
    st.subheader("Receita por Marketplace por Dia")

    if (
        data_ini is not None and data_fim is not None and
        not df_f.empty and
        "Data_Emissao_Filtro" in df_f.columns and
        "Grupo de Marketplace" in df_f.columns
    ):
        df_mkt_dia, ordem_mkt_dia = montar_df_marketplace_por_dia(df_f, data_ini, data_fim)

        if not df_mkt_dia.empty:
            chart_mkt_dia = criar_grafico_marketplace_por_dia(df_mkt_dia, ordem_mkt_dia)

            if chart_mkt_dia is not None:
                aba_geral, aba_individual = st.tabs(["Visão geral", "Visão por marketplace"])

                with aba_geral:
                    # ── use_container_width=True ──────────────────────
                    st.altair_chart(chart_mkt_dia, use_container_width=True)
                    st.caption(
                        f"Receita diária por marketplace entre "
                        f"{data_ini.strftime('%d/%m/%Y')} e {data_fim.strftime('%d/%m/%Y')}. "
                        f"Esta visão preserva a comparação absoluta entre marketplaces."
                    )

                with aba_individual:
                    chart_mkt_facetas = criar_grafico_marketplace_por_dia_facetas(df_mkt_dia, ordem_mkt_dia)
                    if chart_mkt_facetas is not None:
                        # ── use_container_width=True ──────────────────
                        st.altair_chart(chart_mkt_facetas, use_container_width=True)
                        st.caption(
                            "Cada marketplace usa escala própria no eixo Y. "
                            "Ideal para enxergar variação diária dos marketplaces menores — "
                            "não comparar volumes absolutos entre eles."
                        )
        else:
            st.info("Sem dados para exibir a receita por marketplace por dia.")
    else:
        st.info("Sem dados válidos para exibir a receita por marketplace por dia.")

    # ──────────────────────────────────────────
    # 12.1 GRÁFICO: MARKETPLACE × TIPO PEDIDO
    # ──────────────────────────────────────────
    st.subheader("Faturamento por Marketplace e Tipo de Pedido")

    if not df_f.empty:
        filtro_mkt_ativo = bool(mkt_sel) and (not incluir_devolucao)

        if filtro_mkt_ativo:
            df_mkt = (
                df_f.groupby(["Grupo de Marketplace", "Tipo pedido"], as_index=False)
                .agg(Receita=("Receita_Num", "sum"))
            )

            df_mkt["Receita_Total_Marketplace"] = df_mkt.groupby("Grupo de Marketplace")["Receita"].transform("sum")

            df_mkt = df_mkt.sort_values(
                by=["Receita_Total_Marketplace", "Receita"],
                ascending=[False, False]
            )

            ordem_marketplace = (
                df_mkt[["Grupo de Marketplace", "Receita_Total_Marketplace"]]
                .drop_duplicates()
                .sort_values("Receita_Total_Marketplace", ascending=False)
                ["Grupo de Marketplace"]
                .tolist()
            )

            ordem_tipo_pedido = (
                df_mkt.groupby("Tipo pedido", as_index=False)
                .agg(Receita_Total_Tipo=("Receita", "sum"))
                .sort_values("Receita_Total_Tipo", ascending=False)
                ["Tipo pedido"]
                .tolist()
            )

            df_mkt["Ordem_Tipo_Pedido"] = df_mkt.groupby("Grupo de Marketplace")["Receita"].rank(
                method="first",
                ascending=False
            )

            chart_bar = (
                alt.Chart(df_mkt).mark_bar()
                .encode(
                    y=alt.Y(
                        "Grupo de Marketplace:N",
                        title="Marketplace",
                        sort=ordem_marketplace
                    ),
                    x=alt.X(
                        "Receita:Q",
                        title="R$",
                        stack="zero"
                    ),
                    color=alt.Color(
                        "Tipo pedido:N",
                        title="Tipo de Pedido",
                        scale=alt.Scale(domain=ordem_tipo_pedido)
                    ),
                    order=alt.Order(
                        "Ordem_Tipo_Pedido:Q",
                        sort="ascending"
                    ),
                    tooltip=[
                        alt.Tooltip("Grupo de Marketplace:N", title="Marketplace"),
                        alt.Tooltip("Tipo pedido:N", title="Tipo de Pedido"),
                        alt.Tooltip("Receita:Q", title="R$", format=",.2f"),
                        alt.Tooltip("Receita_Total_Marketplace:Q", title="Total MKT", format=",.2f"),
                    ],
                )
                .properties(height=380)
            )

        else:
            df_mkt = (
                df_f.groupby("Grupo de Marketplace", as_index=False)
                .agg(Receita=("Receita_Num", "sum"))
                .sort_values("Receita", ascending=False)
            )

            ordem_marketplace = df_mkt["Grupo de Marketplace"].tolist()

            chart_bar = (
                alt.Chart(df_mkt).mark_bar()
                .encode(
                    y=alt.Y(
                        "Grupo de Marketplace:N",
                        title="Marketplace",
                        sort=ordem_marketplace
                    ),
                    x=alt.X(
                        "Receita:Q",
                        title="R$"
                    ),
                    color=alt.Color(
                        "Grupo de Marketplace:N",
                        title="Marketplace",
                        scale=alt.Scale(
                            domain=MARKETPLACE_ORDEM_CORES,
                            range=MARKETPLACE_CORES
                        ),
                        legend=alt.Legend(
                            orient="top",
                            direction="horizontal"
                        ),
                    ),
                    tooltip=[
                        alt.Tooltip("Grupo de Marketplace:N", title="Marketplace"),
                        alt.Tooltip("Receita:Q", title="R$", format=",.2f"),
                    ],
                )
                .properties(height=380)
            )

        aba_grafico_mkt, aba_detalhamento_mkt = st.tabs(
            ["Gráfico", "Detalhamento"]
        )

        with aba_grafico_mkt:
            st.altair_chart(
                chart_bar,
                use_container_width=True
            )

            if incluir_devolucao:
                st.caption("Exibindo apenas pedidos de devolução.")
            elif filtro_mkt_ativo:
                st.caption("Detalhado por Tipo de Pedido porque há filtro de marketplace ativo.")
            else:
                st.caption("Total por grupo de marketplace. Selecione marketplaces para detalhar por tipo de pedido.")

        with aba_detalhamento_mkt:
            df_resumo_mkt_tipo = montar_resumo_marketplace_tipo_pedido(
                df_f,
                filtro_mkt_ativo=filtro_mkt_ativo
            )

            df_resumo_mkt_tipo_tabela = preparar_tabela_resumo_marketplace_tipo_pedido(
                df_resumo_mkt_tipo,
                filtro_mkt_ativo=filtro_mkt_ativo
            )

            if df_resumo_mkt_tipo_tabela.empty:
                st.info("Sem dados para montar o detalhamento.")
            else:
                if incluir_devolucao:
                    st.caption("Detalhamento consolidado dos pedidos de devolução por marketplace.")
                elif filtro_mkt_ativo:
                    st.caption("Detalhamento por marketplace e tipo de pedido, seguindo a mesma abertura do gráfico.")
                else:
                    st.caption("Detalhamento consolidado por marketplace. Selecione um marketplace para abrir por tipo de pedido.")

                st.table(
                    df_resumo_mkt_tipo_tabela,
                    border="horizontal",
                    hide_index=True
                )

    else:
        st.info("Sem dados para exibir o faturamento por marketplace e tipo de pedido.")
        
    # ──────────────────────────────────────────
    # 12.2 GRÁFICO: FATURAMENTO POR FORNECEDOR
    # ──────────────────────────────────────────
    st.subheader("Faturamento por Fornecedor")

    if "Fornecedor" not in df_f.columns:
        st.info("Coluna 'Fornecedor' não encontrada.")

    elif df_f.empty:
        st.info("Sem dados para exibir o faturamento por fornecedor.")

    else:
        df_fornecedor_base = df_f[
            df_f["Fornecedor"].notna() &
            (df_f["Fornecedor"].astype(str).str.strip() != "")
        ].copy()

        if df_fornecedor_base.empty:
            st.info("Sem dados válidos de fornecedor.")

        else:
            df_fornecedor = (
                df_fornecedor_base
                .groupby("Fornecedor", as_index=False)
                .agg(Receita=("Receita_Num", "sum"))
                .sort_values("Receita", ascending=False)
                .head(20)
            )

            chart_fornecedor = (
                alt.Chart(df_fornecedor).mark_bar()
                .encode(
                    y=alt.Y(
                        "Fornecedor:N",
                        title="Fornecedor",
                        sort="-x"
                    ),
                    x=alt.X(
                        "Receita:Q",
                        title="R$"
                    ),
                    tooltip=[
                        alt.Tooltip("Fornecedor:N", title="Fornecedor"),
                        alt.Tooltip("Receita:Q", title="R$", format=",.2f"),
                    ],
                )
                .properties(
                    height=max(320, min(900, len(df_fornecedor) * 28))
                )
            )

            aba_grafico_fornecedor, aba_detalhamento_fornecedor = st.tabs(
                ["Gráfico", "Detalhamento"]
            )

            with aba_grafico_fornecedor:
                st.altair_chart(
                    chart_fornecedor,
                    use_container_width=True
                )

                st.caption(
                    "Top 20 fornecedores por receita no período selecionado."
                )

            with aba_detalhamento_fornecedor:
                df_resumo_fornecedor = montar_resumo_fornecedor(df_fornecedor_base)

                df_resumo_fornecedor_tabela = preparar_tabela_resumo_fornecedor(
                    df_resumo_fornecedor
                )

                if df_resumo_fornecedor_tabela.empty:
                    st.info("Sem dados para montar o detalhamento por fornecedor.")

                else:
                    st.caption(
                        "Detalhamento por fornecedor, respeitando os filtros aplicados no dashboard."
                    )

                    st.table(
                        df_resumo_fornecedor_tabela,
                        border="horizontal",
                        hide_index=True
                    )
    # ──────────────────────────────────────────
    # 13. RANKINGS
    # ──────────────────────────────────────────
    st.subheader("Rankings")

    abas_ranking = [
        ("Produtos",    "Produto"),
        ("Categorias",  "Categoria"),
        ("Marcas",      "Marca"),
    ]
    if "Fornecedor" in df_f.columns:
        abas_ranking.append(("Fornecedores", "Fornecedor"))

    tabs_principais = st.tabs([titulo for titulo, _ in abas_ranking])

    for (titulo_aba, campo), tab_principal in zip(abas_ranking, tabs_principais):
        with tab_principal:
            if campo not in df_f.columns:
                st.info(f"Coluna '{campo}' não encontrada.")
                continue

            top_n = st.slider("Número de itens no ranking", 5, 35, 20, key=f"top_n_{campo}")

            rotulo_qtd = "Por Quantidade Devolvida" if incluir_devolucao else "Por Quantidade Vendida"
            subtab_receita, subtab_qtd = st.tabs(["Por Receita", rotulo_qtd])

            for subtab, metrica in [(subtab_receita, "Receita"), (subtab_qtd, "Quantidade")]:
                with subtab:
                    if campo == "Produto":
                        df_rank = montar_ranking_produto(df_f, df_prev, df_vendas_60d=df_vendas_60d, incluir_devolucao=incluir_devolucao)
                        if not incluir_devolucao:
                            df_rank = filtrar_ranking_margem_negativa(df_rank, somente_margem_negativa)

                        st.caption(
                            f"Comparação por {metrica.lower()} contra o período anterior: "
                            f"{ini_ant.strftime('%d/%m/%Y')} até {fim_ant.strftime('%d/%m/%Y')}"
                            if ini_ant is not None and fim_ant is not None else
                            f"Comparação por {metrica.lower()} contra o período anterior"
                        )
                        if incluir_devolucao:
                            if metrica == "Receita":
                                st.caption("Exibindo taxa de devolução com base nos últimos 60 dias.")
                            else:
                                st.caption("Exibindo quantidade devolvida e taxa de devolução com base nos últimos 60 dias.")
                        elif somente_margem_negativa:
                            st.caption("Exibindo somente produtos com margem negativa.")

                        render_ranking_produto(df_rank, metrica, top_n, incluir_devolucao=incluir_devolucao)

                    else:
                        df_rank = montar_ranking_grupo(df_f, df_prev, campo, metrica, df_vendas_60d=df_vendas_60d, incluir_devolucao=incluir_devolucao)
                        if not incluir_devolucao:
                            df_rank = filtrar_ranking_margem_negativa(df_rank, somente_margem_negativa)

                        if metrica == "Receita":
                            st.caption(f"A imagem exibida é do produto com maior receita dentro de cada {campo.lower()}.")
                        else:
                            st.caption(f"A imagem exibida é do produto com maior quantidade dentro de cada {campo.lower()}.")

                        if incluir_devolucao:
                            st.caption(f"Exibindo taxa de devolução por {campo.lower()} com base nos últimos 60 dias.")
                        elif somente_margem_negativa:
                            st.caption(f"Exibindo somente {campo.lower()}s com margem negativa.")

                        render_ranking_grupo(df_rank, campo, metrica, top_n, incluir_devolucao=incluir_devolucao)

    st.divider()

    # ──────────────────────────────────────────
    # 14. TABELA DETALHADA
    # ──────────────────────────────────────────
    with st.expander("Ver Detalhamento dos Pedidos"):
        colunas_base = [
            "Data emissao", "Data da Venda", "Grupo de Marketplace", "Tipo pedido",
            "Categoria", "Marca", "Fornecedor", "Produto",
            "Receita", "Liquido", "Custo medio", "Quantidade vendida", "Status do pedido",
        ]
        colunas_exibir = [c for c in colunas_base if c in df_f.columns]
        st.dataframe(df_f[colunas_exibir], use_container_width=True)

except Exception as e:
    st.error(f"Não foi possível carregar os dados: {e}")
    st.exception(e)
