import sys
import re
import base64
import warnings
from pathlib import Path
from collections import defaultdict

import streamlit as st
import geopandas as gpd
import folium
from branca.element import MacroElement
from jinja2 import Template
from streamlit_folium import st_folium
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import pandas as pd
import openpyxl
import asyncio
import unicodedata
import concurrent.futures
import branca.colormap as bcm

warnings.filterwarnings("ignore")

# ── Importar funções do projeto SAF ──────────────────────────────────────────
from src.graficos import (
    _carregar_df,
    criar_grafico_barras_bolhas_saf,
    criar_grafico_barras_saf,
    criar_grafico_timeline_saf,
    criar_grafico_rosca_saf,
    criar_grafico_acumulado_saf,
)

# ── agrobr (dados agrícolas brasileiros) ──────────────────────────────────────
try:
    from agrobr.datasets import producao_anual        as _agrobr_producao
    from agrobr.datasets import serie_historica_safra as _agrobr_serie
    _AGROBR_OK = True
except ImportError:
    _AGROBR_OK = False

# ── Configuração da página ────────────────────────────────────────────────────
st.set_page_config(
    page_title="SIEV | Mapa Territorial",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Paleta ────────────────────────────────────────────────────────────────────
NAVY  = "#1e2878"
TEAL    = "#4dbfc2"
TEAL_SB = "#68c2c5"   # sidebar secondary accent
GREEN = "#9ebf1a"
LIGHT = "#eef2fa"
WHITE = "#FFFFFF"
DARK  = "#141a5c"
NAVY2 = "#252e7e"
TEXT  = "#e7f0fa"

# Cores por rota tecnológica (consistente com graficos.py)
PALETA_ROTA = {
    "Coprocessamento": "#1B4F8A",
    "HEFA":            "#2980B9",
    "ATJ":             "#E67E22",
    "FT":              "#1A7F4B",
}

MUN_SHP = Path(__file__).parent / "data" / "municipios.geojson"

def cor_rota(rota: str) -> str:
    for k, v in PALETA_ROTA.items():
        if k.lower() in str(rota).lower():
            return v
    return "#607D8B"

def norm_rota(rota: str) -> str:
    r = str(rota)
    if "Copro" in r: return "Coprocessamento HEFA"
    if "ATJ"   in r: return "ATJ"
    if "HEFA"  in r: return "HEFA Dedicado"
    if "FT"    in r: return "FT"
    return "Outros"

def _run_async(coro):
    """Run async coroutine safely from sync context (works inside Streamlit)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()

def _strip_accents(s: str) -> str:
    n = unicodedata.normalize('NFKD', str(s))
    return ''.join(c for c in n if not unicodedata.combining(c)).upper().strip()

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
  .stApp {{ background: {LIGHT}; }}
  #MainMenu, footer {{ visibility: hidden; }}

  [data-testid="stHeader"] {{
      background: transparent !important;
      border-bottom: none !important;
  }}
  .block-container {{
      padding-top: 0.5rem !important;
      padding-left: 1.5rem  !important;
      padding-right: 1.5rem !important;
      padding-bottom: 1rem  !important;
      max-width: 100% !important;
  }}

  /* ════ SIDEBAR — base ════ */
  section[data-testid="stSidebar"],
  [data-testid="stSidebar"],
  [data-testid="stSidebar"] > div,
  [data-testid="stSidebar"] > div > div,
  [data-testid="stSidebar"] > div:first-child,
  [data-testid="stSidebarContent"],
  [data-testid="stSidebarContent"] > div {{
      background-color: #252e7e !important;
      background: #252e7e !important;
      box-shadow: none !important;
  }}
  [data-testid="stSidebar"] > div:first-child {{
      border-right: 2px solid {TEAL_SB};
  }}
  [data-testid="stSidebar"] *,
  [data-testid="stSidebar"] p,
  [data-testid="stSidebar"] span,
  [data-testid="stSidebar"] div,
  [data-testid="stSidebar"] label {{
      color: {TEXT} !important;
  }}

  /* ── Compact vertical layout ── */
  [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
      gap: 0.18rem !important;
  }}
  [data-testid="stSidebar"] [data-testid="stElementContainer"] {{
      padding-top: 0 !important;
      padding-bottom: 0 !important;
      margin-top: 0 !important;
      margin-bottom: 0 !important;
  }}
  [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {{
      gap: 0.25rem !important;
  }}

  /* ── Section label ── */
  .sb-label {{
      display: flex !important;
      align-items: center;
      gap: 6px;
      font-size: 0.6rem !important;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      color: {TEAL_SB} !important;
      font-weight: 700;
      padding: 8px 2px 4px 2px;
      margin: 0 0 3px 0;
      border-bottom: 1px solid rgba(104,194,197,0.18);
  }}

  /* ── Divider ── */
  .sb-divider {{
      border: none;
      border-top: 1px solid rgba(104,194,197,0.15);
      margin: 7px 0 1px 0;
  }}

  /* ── Badge ── */
  .sb-badge {{
      display: inline-block;
      background: rgba(104,194,197,0.14);
      border: 1px solid rgba(104,194,197,0.3);
      color: {TEAL_SB} !important;
      font-size: 0.56rem !important;
      font-weight: 700;
      padding: 1px 5px;
      border-radius: 9px;
      letter-spacing: 0.04em;
      margin-left: 4px;
      vertical-align: middle;
  }}

  /* ── Selectbox ── */
  [data-testid="stSidebar"] [data-baseweb="select"] > div:first-child {{
      background: rgba(255,255,255,0.06) !important;
      border: 1px solid rgba(104,194,197,0.35) !important;
      border-radius: 6px !important;
      transition: border-color 0.15s;
  }}
  [data-testid="stSidebar"] [data-baseweb="select"] > div:first-child:hover {{
      border-color: rgba(104,194,197,0.65) !important;
  }}
  [data-testid="stSidebar"] [data-baseweb="select"] span {{
      color: {TEXT} !important;
      font-size: 0.9rem !important;
      font-weight: 500 !important;
  }}
  [data-testid="stSidebar"] [data-baseweb="select"] svg {{
      fill: {TEAL_SB} !important;
  }}

  /* ── Radio (nav items + feedstock picker) ── */
  [data-testid="stSidebar"] [data-testid="stRadio"] > div:first-child > label {{
      display: none !important;
  }}
  [data-testid="stSidebar"] [data-testid="stRadio"] > div {{
      gap: 0 !important;
  }}
  [data-testid="stSidebar"] [data-testid="stRadio"] label {{
      display: flex !important;
      align-items: center !important;
      padding: 5px 12px !important;
      border-left: 3px solid transparent !important;
      border-radius: 0 !important;
      color: {TEXT} !important;
      font-size: 0.82rem !important;
      font-weight: 400 !important;
      transition: background 0.15s, border-color 0.15s;
      cursor: pointer;
      margin: 0 !important;
  }}
  [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {{
      background: rgba(104,194,197,0.09) !important;
      border-left-color: rgba(104,194,197,0.45) !important;
  }}
  [data-testid="stSidebar"] [data-testid="stRadio"] label[data-checked="true"] {{
      background: rgba(104,194,197,0.15) !important;
      border-left-color: {TEAL_SB} !important;
      font-weight: 600 !important;
  }}
  [data-testid="stSidebar"] [data-testid="stRadio"] > div > label > div:first-child {{
      display: none !important;
  }}
  [data-testid="stSidebar"] [data-testid="stRadio"] [data-testid="stMarkdownContainer"] p {{
      color: {TEXT} !important;
      margin: 0 !important;
      font-size: 0.82rem !important;
  }}

  /* ── Toggle (st.toggle) ── */
  [data-testid="stSidebar"] [data-testid="stToggle"] {{
      padding: 1px 0 !important;
  }}
  [data-testid="stSidebar"] [data-testid="stToggle"] label {{
      font-size: 0.82rem !important;
      font-weight: 400 !important;
      padding: 2px 0 !important;
  }}
  [data-testid="stSidebar"] [data-testid="stToggle"] > label > span:first-child > div {{
      background-color: rgba(255,255,255,0.12) !important;
      border: 1px solid rgba(104,194,197,0.2) !important;
  }}
  [data-testid="stSidebar"] [data-testid="stToggle"] [aria-checked="true"] > div {{
      background-color: {TEAL_SB} !important;
      border-color: {TEAL_SB} !important;
  }}

  /* ── Shortcut buttons (Todos / Nenhum) ── */
  [data-testid="stSidebar"] [data-testid="stButton"] button {{
      background: rgba(255,255,255,0.05) !important;
      border: 1px solid rgba(104,194,197,0.28) !important;
      color: {TEXT} !important;
      font-size: 0.7rem !important;
      padding: 3px 8px !important;
      border-radius: 4px !important;
      font-weight: 500 !important;
      width: 100%;
      transition: background 0.15s, border-color 0.15s;
  }}
  [data-testid="stSidebar"] [data-testid="stButton"] button:hover {{
      background: rgba(104,194,197,0.12) !important;
      border-color: rgba(104,194,197,0.5) !important;
  }}

  /* ── Slider ── */
  [data-testid="stSidebar"] [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {{
      background: {TEAL_SB} !important;
      border-color: white !important;
      box-shadow: 0 0 5px rgba(104,194,197,0.5) !important;
  }}

  /* ─── TOPBAR ─── */
  .topbar {{
      background: linear-gradient(90deg, {DARK} 0%, {NAVY2} 100%);
      color: {WHITE};
      padding: 12px 22px;
      border-radius: 6px 6px 0 0;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 2px solid {TEAL};
      box-shadow: 0 2px 12px rgba(20,26,92,0.18);
  }}
  .topbar-left {{ display: flex; flex-direction: column; gap: 2px; }}
  .topbar-title {{
      font-size: 0.98rem; font-weight: 700;
      letter-spacing: 0.07em; text-transform: uppercase; color: {TEXT};
  }}
  .topbar-sub {{
      font-size: 0.67rem; color: {TEAL};
      letter-spacing: 0.06em; font-weight: 400;
  }}
  .topbar-badge {{
      background: rgba(77,191,194,0.15);
      border: 1px solid rgba(77,191,194,0.4);
      border-radius: 3px; padding: 3px 10px;
      font-size: 0.65rem; color: {TEAL};
      letter-spacing: 0.1em; text-transform: uppercase; font-weight: 600;
  }}

  /* ─── STAT CARDS ─── */
  .cards-row {{
      display: flex; gap: 0; background: {WHITE};
      border-left: 1px solid rgba(30,40,120,0.12);
      border-right: 1px solid rgba(30,40,120,0.12);
      border-bottom: 2px solid rgba(30,40,120,0.08);
      margin-bottom: 0;
  }}
  .stat-card {{
      flex: 1; padding: 10px 18px;
      border-right: 1px solid rgba(30,40,120,0.08);
      position: relative;
  }}
  .stat-card:last-child {{ border-right: none; }}
  .stat-card .s-label {{
      font-size: 0.62rem; letter-spacing: 0.12em;
      text-transform: uppercase; color: #5566aa;
      margin-bottom: 3px; font-weight: 600;
  }}
  .stat-card .s-value {{
      font-size: 1.4rem; font-weight: 700; color: {NAVY2}; line-height: 1;
  }}
  .stat-card .s-unit {{
      font-size: 0.68rem; color: {TEAL}; font-weight: 600;
      margin-left: 4px; vertical-align: middle;
  }}
  .stat-card .s-text {{
      font-size: 0.95rem; font-weight: 600; color: {NAVY2}; line-height: 1.1;
  }}

  /* ─── MAP + PANEL ─── */
  iframe {{
      border-radius: 0 0 6px 6px !important;
      border: 1px solid rgba(30,40,120,0.18) !important;
      border-top: none !important;
  }}

  /* ─── SECTION HEADER ─── */
  .section-header {{
      font-size: 0.65rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: {TEAL};
      font-weight: 700;
      padding: 20px 0 8px 0;
      margin: 0;
      border-bottom: 1px solid rgba(77,191,194,0.25);
      margin-bottom: 16px;
  }}

  /* ─── PANEL ─── */
  .panel-placeholder {{
      background: white;
      border-radius: 6px;
      border: 1.5px dashed #B0C4DE;
      display: flex; align-items: center; justify-content: center;
      flex-direction: column;
      color: #9AB; text-align: center; padding: 32px 20px;
      height: 100%;
      min-height: 500px;
  }}

  /* ─── TABS ─── */
  [data-testid="stTab"] {{
      font-size: 0.82rem !important;
      letter-spacing: 0.03em;
  }}

  /* ── Multiselect ── */
  [data-testid="stSidebar"] [data-testid="stMultiSelect"] [data-baseweb="select"] > div {{
      background: rgba(255,255,255,0.07) !important;
      border: 1px solid rgba(77,191,194,0.38) !important;
      border-radius: 6px !important;
      min-height: 38px !important;
      transition: border-color 0.15s;
  }}
  [data-testid="stSidebar"] [data-testid="stMultiSelect"] [data-baseweb="select"] > div:hover {{
      border-color: rgba(77,191,194,0.7) !important;
  }}
  [data-testid="stSidebar"] [data-baseweb="tag"] {{
      background: rgba(77,191,194,0.16) !important;
      border: 1px solid rgba(77,191,194,0.42) !important;
      border-radius: 4px !important;
  }}
  [data-testid="stSidebar"] [data-baseweb="tag"] span {{
      color: {TEXT} !important;
      font-size: 0.74rem !important;
  }}
  [data-testid="stSidebar"] [data-baseweb="tag"] [role="button"] svg {{
      fill: rgba(231,240,250,0.5) !important;
  }}
  [data-testid="stSidebar"] [data-testid="stMultiSelect"] input::placeholder {{
      color: rgba(231,240,250,0.38) !important;
  }}

  /* ─── EXPANDER DO PAINEL ─── */
  /* Remove padding extra acima do expander para alinhar com o topo do mapa */
  [data-testid="stExpander"] {{
      border: 1px solid rgba(30,40,120,0.15) !important;
      border-radius: 6px !important;
      background: white !important;
      margin-top: 0 !important;
  }}
  [data-testid="stExpander"] summary {{
      font-size: 0.82rem !important;
      font-weight: 700 !important;
      color: {NAVY2} !important;
      padding: 10px 14px !important;
      background: #F2F6FB !important;
      border-radius: 6px 6px 0 0 !important;
  }}
  [data-testid="stExpander"] summary:hover {{
      background: #E8EEF8 !important;
  }}
  [data-testid="stExpander"] > div[data-testid="stExpanderDetails"] {{
      padding: 0 !important;
  }}
</style>
""", unsafe_allow_html=True)


# ── Dados ─────────────────────────────────────────────────────────────────────
@st.cache_data
def load_geo():
    path = Path(__file__).parent / "data" / "estados.geojson"
    return gpd.read_file(path)

@st.cache_data
def load_saf():
    return _carregar_df()

@st.cache_data
def geojson(_gdf):
    return _gdf.__geo_interface__

@st.cache_data
def load_refinarias():
    path = Path(__file__).parent / "Dados" / "refinarias_petroleo.zip"
    gdf = gpd.read_file(f"zip://{path}")
    keep = ["sigla", "nome_inst", "razao_soci", "munic", "uf",
            "cap_aut", "Ano de Ina", "Fonte de d", "geometry"]
    return gdf[[c for c in keep if c in gdf.columns]].copy()

@st.cache_data
def load_usinas():
    path = Path(__file__).parent / "Dados" / "usina_etanol.zip"
    gdf = gpd.read_file(f"zip://{path}")
    keep = ["Nome", "Cidade", "UF", "Tipo", "Situacao",
            "Classecap", "Caprocmi", "Início da", "geometry"]
    return gdf[[c for c in keep if c in gdf.columns]].copy()

@st.cache_data
def load_rodovias_fed():
    path = Path(__file__).parent / "Dados" / "rodovia-federal.zip"
    gdf = gpd.read_file(f"zip://{path}")
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf["geometry"].simplify(0.05, preserve_topology=True)
    return gdf[["geometry"]].copy()

@st.cache_data
def load_rodovias_est():
    path = Path(__file__).parent / "Dados" / "rodovia-estadual.zip"
    gdf = gpd.read_file(f"zip://{path}")
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf["geometry"].simplify(0.05, preserve_topology=True)
    return gdf[["geometry"]].copy()

@st.cache_data
def load_municipios_shp():
    gdf = gpd.read_file(MUN_SHP)
    gdf["CD_MUN"]    = gdf["CD_MUN"].astype(str)
    gdf["nome_norm"] = gdf["NM_MUN"].apply(_strip_accents)
    return gdf[["CD_MUN", "NM_MUN", "SIGLA_UF", "nome_norm", "geometry"]]

@st.cache_data
def load_feedstock_municipio(produto: str, ano: int) -> pd.DataFrame:
    """agrobr producao_anual nível municipal → DataFrame com CD_MUN + producao."""
    if not _AGROBR_OK:
        return pd.DataFrame()
    try:
        df = _run_async(_agrobr_producao(produto, nivel='municipio', ano=ano))
    except Exception:
        return pd.DataFrame()
    split        = df['localidade'].str.rsplit(' - ', n=1, expand=True)
    df['mun_nome'] = split[0].str.strip()
    df['uf']       = split[1].str.strip() if split.shape[1] > 1 else ''
    df['mun_norm'] = df['mun_nome'].apply(_strip_accents)
    shp = load_municipios_shp()[['CD_MUN', 'nome_norm', 'SIGLA_UF']]
    merged = df.merge(shp, left_on=['mun_norm', 'uf'],
                      right_on=['nome_norm', 'SIGLA_UF'], how='left')
    result = merged[['CD_MUN', 'producao', 'mun_nome', 'uf']].dropna(
        subset=['CD_MUN', 'producao'])
    result = result.copy()
    result['producao'] = result['producao'].astype(float)
    return result

@st.cache_data
def load_feedstock_serie(produto: str) -> pd.DataFrame:
    """CONAB série histórica por UF (todos os anos de uma vez)."""
    if not _AGROBR_OK:
        return pd.DataFrame()
    try:
        return _run_async(_agrobr_serie(produto))
    except Exception:
        return pd.DataFrame()

def logo_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

gdf     = load_geo()
df_saf  = load_saf()


# ── Ícone SVG: pino de localização com silhueta de avião ─────────────────────
def saf_pin(idx: int, color: str) -> str:
    """
    Marcador circular com silhueta de indústria/fábrica para projetos SAF.
    """
    return (
        f'<div class="saf-icon" style="position:relative;width:20px;height:22px;cursor:pointer;">'
        f'<svg viewBox="0 0 46 50" xmlns="http://www.w3.org/2000/svg" width="20" height="22">'
        # Sombra
        f'<ellipse cx="23" cy="48" rx="8" ry="2.5" fill="rgba(0,0,0,0.22)"/>'
        # Círculo principal colorido
        f'<circle cx="23" cy="21" r="19" fill="{color}" stroke="white" stroke-width="2"/>'
        # Silhueta de indústria (branca)
        # Chaminé esquerda
        f'<rect x="11" y="9"  width="5"  height="13" rx="1.2" fill="white"/>'
        # Chaminé direita
        f'<rect x="20" y="12" width="4"  height="10" rx="1.2" fill="white"/>'
        # Corpo principal da fábrica
        f'<rect x="8"  y="22" width="30" height="10" rx="1.5" fill="white"/>'
        # Porta central
        f'<rect x="20" y="27" width="6"  height="5"  rx="1"   fill="{color}"/>'
        # Fumaça chaminé esquerda
        f'<circle cx="13.5" cy="7"   r="2.2" fill="white" opacity="0.75"/>'
        f'<circle cx="16"   cy="5.5" r="1.6" fill="white" opacity="0.50"/>'
        # Badge número (canto superior direito)
        f'<circle cx="38" cy="9" r="7.5" fill="white" stroke="{color}" stroke-width="1.8"/>'
        f'<text x="38" y="9" text-anchor="middle" dominant-baseline="central" '
        f'font-size="7.5" font-weight="700" fill="{color}" font-family="Arial,sans-serif">{idx}</text>'
        f'</svg>'
        f'</div>'
    )


# ── Construção do mapa ────────────────────────────────────────────────────────
def build_map(df: pd.DataFrame, gdf_uf, tile_choice: str, tile_url,
              gdf_ref=None, gdf_usi=None, gdf_fed=None, gdf_est=None,
              feed_gdf=None, feed_col='valor', feed_caption='Produção (t)',
              feed_name='Feedstock SAF', feed_id_col='CD_MUN', feed_label_col='NM_MUN',
              feed_tipo='Coroplético') -> folium.Map:
    # Instancia mapa
    if tile_url is None:
        m = folium.Map(location=[-15.5, -52.0], zoom_start=4, tiles=None)
        folium.TileLayer("", attr=" ", name="Sem fundo").add_to(m)
    elif isinstance(tile_url, str) and tile_url.startswith("http"):
        m = folium.Map(location=[-15.5, -52.0], zoom_start=4, tiles=None)
        folium.TileLayer(tile_url, attr="ESRI", name="Satélite").add_to(m)
    else:
        m = folium.Map(location=[-15.5, -52.0], zoom_start=4, tiles=tile_url)

    # Malha de estados
    folium.GeoJson(
        geojson(gdf_uf),
        name="Estados",
        style_function=lambda _: {
            "fillColor": LIGHT, "color": TEAL, "weight": 1.0, "fillOpacity": 0.15,
        },
        highlight_function=lambda _: {
            "fillColor": GREEN, "color": NAVY2, "weight": 2, "fillOpacity": 0.35,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["NM_UF", "SIGLA_UF", "NM_REGIAO"],
            aliases=["Estado:", "UF:", "Região:"],
            style=(
                f"background:{WHITE}; color:{NAVY2}; font-size:12px;"
                f"border:1px solid {TEAL}; border-radius:4px; padding:6px 10px;"
            ),
        ),
    ).add_to(m)

    # ── Camada de feedstocks (coroplético ou mapa de calor) ──────────────────
    # ADICIONADA ANTES DAS RODOVIAS E MARCADORES para ficar abaixo de tudo
    if feed_gdf is not None and not feed_gdf.empty and feed_col in feed_gdf.columns:
        _vals = feed_gdf[feed_col].dropna()
        if len(_vals) > 0:
            if feed_tipo == "Mapa de Calor":
                from folium.plugins import HeatMap
                _pts = []
                for _geom, _v in zip(feed_gdf.geometry, feed_gdf[feed_col]):
                    try:
                        _cx = _geom.centroid.x
                        _cy = _geom.centroid.y
                        _vf = float(_v)
                        if _vf > 0:
                            _pts.append([_cy, _cx, _vf])
                    except Exception:
                        continue
                if _pts:
                    _vmax_h = float(_vals.quantile(0.95))
                    HeatMap(
                        _pts,
                        name=feed_name + " (Calor)",
                        min_opacity=0.25,
                        max_val=_vmax_h,
                        radius=18,
                        blur=22,
                        gradient={
                            0.15: "#313695",
                            0.35: "#4575b4",
                            0.55: "#fee090",
                            0.75: "#f46d43",
                            1.00: "#a50026",
                        },
                    ).add_to(m)
            else:
                _vmin = float(_vals.quantile(0.02))
                _vmax = float(_vals.quantile(0.98))
                if _vmin >= _vmax:
                    _vmax = _vmin + 1
                _cmap = bcm.LinearColormap(
                    ['#ffffd4', '#fed98e', '#fe9929', '#d95f0e', '#993404'],
                    vmin=_vmin, vmax=_vmax, caption=feed_caption,
                )
                _fcol = feed_col
                def _feed_style(f, _col=_fcol, _cm=_cmap):
                    try:
                        v = float(f['properties'].get(_col) or 0)
                        if v <= 0:
                            return {'fillColor': '#eee', 'fillOpacity': 0.0,
                                    'color': '#999', 'weight': 0}
                        return {'fillColor': _cm(v), 'fillOpacity': 0.78,
                                'color': '#666', 'weight': 0.25}
                    except (TypeError, ValueError):
                        return {'fillColor': '#eee', 'fillOpacity': 0.0,
                                'color': '#999', 'weight': 0}
                _tip_fields  = [c for c in [feed_label_col, feed_col] if c in feed_gdf.columns]
                _tip_aliases = [feed_label_col + ':', feed_caption + ':'][:len(_tip_fields)]
                _geo_cols    = list({feed_col, feed_id_col, feed_label_col} & set(feed_gdf.columns))
                folium.GeoJson(
                    feed_gdf[['geometry'] + _geo_cols],
                    name=feed_name,
                    style_function=_feed_style,
                    tooltip=folium.GeoJsonTooltip(
                        fields=_tip_fields,
                        aliases=_tip_aliases,
                        style=(f"background:{WHITE};color:{NAVY2};font-size:11px;"
                               f"border:1px solid {TEAL};border-radius:4px;padding:5px 8px;"),
                        localize=True,
                    ),
                ).add_to(m)
                _cmap.add_to(m)

    # ── Rodovias Federais ────────────────────────────────────────────────────
    if gdf_fed is not None:
        # Halo (glow) + linha principal
        folium.GeoJson(
            gdf_fed,
            name="Rodovias Federais",
            style_function=lambda _: {"color": "#90CAF9", "weight": 5, "opacity": 0.25},
        ).add_to(m)
        folium.GeoJson(
            gdf_fed,
            style_function=lambda _: {"color": "#1565C0", "weight": 2.0, "opacity": 0.92},
        ).add_to(m)

    # ── Rodovias Estaduais ───────────────────────────────────────────────────
    if gdf_est is not None:
        folium.GeoJson(
            gdf_est,
            name="Rodovias Estaduais",
            style_function=lambda _: {"color": "#FFAB76", "weight": 4, "opacity": 0.22},
        ).add_to(m)
        folium.GeoJson(
            gdf_est,
            style_function=lambda _: {"color": "#E65100", "weight": 1.6, "opacity": 0.9},
        ).add_to(m)

    # ── Refinarias de Petróleo ───────────────────────────────────────────────
    if gdf_ref is not None:
        grupo_ref = folium.FeatureGroup(name="Refinarias de Petróleo", show=True)
        for _, row in gdf_ref.iterrows():
            nome = str(row.get("nome_inst", "Refinaria")).strip()
            tip = folium.Tooltip(nome, style="font-family:Arial,sans-serif;font-size:12px;font-weight:600;")
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=14, color="#FF6B6B", fill=True,
                fill_color="#FF6B6B", fill_opacity=0.18, weight=0,
            ).add_to(grupo_ref)
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=9, color="#FF2020", fill=True,
                fill_color="#CC0000", fill_opacity=0.92,
                weight=2.5, tooltip=tip,
            ).add_to(grupo_ref)
        m.add_child(grupo_ref)

    # ── Usinas de Etanol ─────────────────────────────────────────────────────
    if gdf_usi is not None:
        grupo_usi = folium.FeatureGroup(name="Usinas de Etanol", show=True)
        for _, row in gdf_usi.iterrows():
            nome = str(row.get("Nome", "Usina")).strip()
            tip = folium.Tooltip(nome, style="font-family:Arial,sans-serif;font-size:12px;font-weight:600;")
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=8, color="#00E676", fill=True,
                fill_color="#00E676", fill_opacity=0.18, weight=0,
            ).add_to(grupo_usi)
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=5, color="#FFFFFF", fill=True,
                fill_color="#00C853", fill_opacity=0.95,
                weight=1.8, tooltip=tip,
            ).add_to(grupo_usi)
        m.add_child(grupo_usi)

    # Marcadores dos projetos SAF
    grupo = folium.FeatureGroup(name="Projetos SAF", show=True)
    for i, (_, row) in enumerate(df.iterrows()):
        cor  = cor_rota(str(row.get("Rota", "")))
        nome = str(row.get("Projeto", f"Projeto {i+1}"))
        pin  = saf_pin(i + 1, cor)

        grupo.add_child(folium.Marker(
            location=[row["lat"], row["lon"]],
            tooltip=folium.Tooltip(nome, style="font-family:Arial,sans-serif;font-size:13px;font-weight:600;"),
            icon=folium.DivIcon(html=pin, icon_size=(20, 22), icon_anchor=(10, 11)),
        ))

    m.add_child(grupo)

    folium.LayerControl(collapsed=True).add_to(m)

    # Legenda de rotas (HTML flutuante no mapa)
    legenda_itens = [
        ("Coprocessamento HEFA", "#1B4F8A"),
        ("HEFA Dedicado",        "#2980B9"),
        ("ATJ (Alcohol-to-Jet)", "#E67E22"),
        ("FT (Fischer-Tropsch)", "#1A7F4B"),
        ("Outros",               "#607D8B"),
    ]
    legenda_html = """
<div style="position:fixed;bottom:24px;left:16px;background:white;padding:12px 16px;
     border-radius:7px;border:1px solid #D8E3EC;font-family:'Segoe UI',Arial,sans-serif;
     font-size:11.5px;box-shadow:0 3px 10px rgba(0,0,0,0.13);z-index:1000;min-width:190px;">
  <div style="font-weight:700;margin-bottom:9px;color:#0D2E57;font-size:11px;
       text-transform:uppercase;letter-spacing:.8px;">Rota Tecnológica</div>
"""
    for nome_r, cor_r in legenda_itens:
        # Pino SVG em miniatura para a legenda
        pin_mini = (
            f'<svg viewBox="0 0 38 46" width="14" height="17" style="vertical-align:middle;margin-right:7px;">'
            f'<path d="M19 2C10.72 2 4 8.72 4 17C4 28.5 19 44 19 44C19 44 34 28.5 34 17'
            f'C34 8.72 27.28 2 19 2Z" fill="{cor_r}"/>'
            f'<circle cx="19" cy="17" r="10" fill="white" opacity="0.5"/>'
            f'</svg>'
        )
        legenda_html += (
            f'<div style="display:flex;align-items:center;margin-bottom:6px;">'
            f'{pin_mini}'
            f'<span style="color:#333;">{nome_r}</span>'
            f'</div>'
        )
    legenda_html += "</div>"

    # Legenda de camadas extras (refinarias / usinas)
    extras = []
    if gdf_ref is not None:
        extras.append(("Refinarias de Petróleo", "#1a1a1a", "●"))
    if gdf_usi is not None:
        extras.append(("Usinas de Etanol", "#27AE60", "●"))
    if gdf_fed is not None:
        extras.append(("Rodovias Federais", "#1565C0", "—"))
    if gdf_est is not None:
        extras.append(("Rodovias Estaduais", "#E65100", "—"))
    if extras:
        legenda_extra = """
<div style="position:fixed;bottom:24px;left:220px;background:white;padding:10px 14px;
     border-radius:7px;border:1px solid #D8E3EC;font-family:'Segoe UI',Arial,sans-serif;
     font-size:11.5px;box-shadow:0 3px 10px rgba(0,0,0,0.13);z-index:1000;min-width:180px;">
  <div style="font-weight:700;margin-bottom:8px;color:#0D2E57;font-size:11px;
       text-transform:uppercase;letter-spacing:.8px;">Camadas Ativas</div>
"""
        for lbl, cor, sym in extras:
            legenda_extra += (
                f'<div style="display:flex;align-items:center;margin-bottom:5px;">'
                f'<span style="color:{cor};font-size:14px;margin-right:8px;line-height:1;">{sym}</span>'
                f'<span style="color:#333;">{lbl}</span>'
                f'</div>'
            )
        legenda_extra += "</div>"
        m.get_root().html.add_child(folium.Element(legenda_extra))

    m.get_root().html.add_child(folium.Element(legenda_html))

    # Escala dinâmica dos ícones conforme o nível de zoom
    zoom_scaler = MacroElement()
    zoom_scaler._template = Template("""
        {% macro script(this, kwargs) %}
        (function(){
            var mymap = {{this._parent.get_name()}};
            function _scaleIcons(){
                var z = mymap.getZoom();
                var s = Math.round(z * 5);
                var h = Math.round(s * 1.1);
                document.querySelectorAll('.saf-icon').forEach(function(el){
                    el.style.width  = s + 'px';
                    el.style.height = h + 'px';
                    var svg = el.querySelector('svg');
                    if(svg){ svg.setAttribute('width', s); svg.setAttribute('height', h); }
                });
            }
            mymap.on('zoomend', _scaleIcons);
            setTimeout(_scaleIcons, 200);
        })();
        {% endmacro %}
    """)
    zoom_scaler.add_to(m)

    return m


# ── Painel de detalhes do projeto ─────────────────────────────────────────────
def render_panel(row: dict):
    projeto      = str(row.get("Projeto", "—"))
    proponente   = str(row.get("Proponente", "—"))
    capacidade   = str(row.get("Capacidade", "—"))
    rota         = str(row.get("Rota", "—"))
    feedstock    = str(row.get("Feedstock", "—"))
    ano          = str(row.get("Ano", "—"))
    investimento = str(row.get("Investimento", "—"))
    municipio    = str(row.get("Municipio", "—"))
    estagio      = str(row.get("Estagio", "—"))
    base         = str(row.get("BaseEstagio", "—") or "—")
    if len(base) > 220:
        base = base[:217] + "..."
    url1  = str(row.get("URL Fonte 1",  "") or "")
    url2  = str(row.get("URL Fonte 2",  "") or "")
    nome1 = str(row.get("Fonte 1 (oficial)", "Fonte 1") or "Fonte 1")[:60]
    nome2 = str(row.get("Fonte 2", "Fonte 2") or "Fonte 2")[:60]

    cor  = cor_rota(rota)
    rota_norm = norm_rota(rota)

    def campo(label, valor):
        return (
            f'<div style="margin-bottom:11px;">'
            f'<div style="color:#8899bb;font-size:9.5px;text-transform:uppercase;'
            f'letter-spacing:.7px;font-weight:700;margin-bottom:3px;">{label}</div>'
            f'<div style="color:#1A2A3A;font-size:12.5px;font-weight:500;line-height:1.4;">{valor}</div>'
            f'</div>'
        )

    fontes_html = ""
    ref = 1
    if url1.startswith("http"):
        fontes_html += (
            f'<div style="margin-bottom:6px;">'
            f'[{ref}] <a href="{url1}" target="_blank" '
            f'style="color:#2C7BE5;text-decoration:none;font-size:11.5px;">{nome1} ↗</a>'
            f'</div>'
        )
        ref += 1
    if url2.startswith("http"):
        fontes_html += (
            f'<div>[{ref}] <a href="{url2}" target="_blank" '
            f'style="color:#2C7BE5;text-decoration:none;font-size:11.5px;">{nome2} ↗</a>'
            f'</div>'
        )

    html = f"""
<div style="background:white;border-radius:7px;border:1px solid #D8E3EC;
     box-shadow:0 3px 18px rgba(20,40,100,0.10);overflow:hidden;font-family:'Segoe UI',Arial,sans-serif;">

  <!-- Cabeçalho colorido -->
  <div style="background:linear-gradient(135deg,{DARK} 0%,{cor} 100%);padding:16px 18px 14px;">
    <div style="font-size:8.5px;color:rgba(255,255,255,0.65);text-transform:uppercase;
         letter-spacing:1.3px;font-weight:700;margin-bottom:7px;">Projeto SAF · Brasil</div>
    <div style="font-size:15px;font-weight:700;color:#FFF;margin-bottom:4px;
         line-height:1.3;">{projeto}</div>
    <div style="font-size:11.5px;color:rgba(255,255,255,0.8);margin-bottom:10px;">{proponente}</div>
    <span style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.35);
          border-radius:3px;padding:3px 9px;font-size:10px;color:white;font-weight:600;">
      {rota_norm}
    </span>
  </div>

  <!-- Métricas principais -->
  <div style="display:flex;background:#F2F6FB;border-bottom:1px solid #D8E3EC;">
    <div style="flex:1;padding:12px 16px;border-right:1px solid #D8E3EC;">
      <div style="color:#8899bb;font-size:9px;text-transform:uppercase;letter-spacing:.7px;
           font-weight:700;margin-bottom:4px;">Capacidade SAF</div>
      <div style="color:{DARK};font-size:20px;font-weight:700;">{capacidade}</div>
      <div style="color:#8899bb;font-size:9px;margin-top:1px;">m³/ano</div>
    </div>
    <div style="flex:1;padding:12px 16px;">
      <div style="color:#8899bb;font-size:9px;text-transform:uppercase;letter-spacing:.7px;
           font-weight:700;margin-bottom:4px;">Ano de Início</div>
      <div style="color:{DARK};font-size:20px;font-weight:700;">{ano}</div>
    </div>
  </div>

  <!-- Campos de detalhe -->
  <div style="padding:14px 18px 6px 18px;">
    {campo("Município / UF", municipio)}
    {campo("Feedstock Principal", feedstock)}
    {campo("Investimento", investimento)}
    {campo("Estágio do Projeto", estagio)}
    {campo("Descrição do Estágio", base)}
  </div>

  <!-- Fontes -->
  {"" if not fontes_html else f'''
  <div style="padding:10px 18px 14px 18px;border-top:1px solid #EEF2F7;margin-top:4px;">
    <div style="color:#8899bb;font-size:9px;text-transform:uppercase;letter-spacing:.7px;
         font-weight:700;margin-bottom:7px;">Fontes</div>
    {fontes_html}
  </div>'''}

</div>"""

    st.markdown(html, unsafe_allow_html=True)


def render_refinaria_panel(row: dict):
    def campo(label, valor):
        return (
            f'<div style="margin-bottom:10px;">'
            f'<div style="color:#8899bb;font-size:9.5px;text-transform:uppercase;'
            f'letter-spacing:.7px;font-weight:700;margin-bottom:3px;">{label}</div>'
            f'<div style="color:#1A2A3A;font-size:12.5px;font-weight:500;line-height:1.4;">{valor}</div>'
            f'</div>'
        )
    sigla     = str(row.get("sigla",      "—"))
    nome      = str(row.get("nome_inst",  "—"))
    empresa   = str(row.get("razao_soci", "—"))
    munic     = str(row.get("munic",      "—"))
    uf        = str(row.get("uf",         ""))
    cap       = str(row.get("cap_aut",    "—"))
    ano       = str(row.get("Ano de Ina", "—"))
    fonte     = str(row.get("Fonte de d", "—"))
    html = f"""
<div style="background:white;border-radius:7px;border:1px solid #D8E3EC;
     box-shadow:0 3px 18px rgba(20,40,100,0.10);overflow:hidden;
     font-family:'Segoe UI',Arial,sans-serif;">
  <div style="background:linear-gradient(135deg,#4A1500 0%,#C0392B 100%);
       padding:16px 18px 14px;">
    <div style="font-size:8.5px;color:rgba(255,255,255,0.65);text-transform:uppercase;
         letter-spacing:1.3px;font-weight:700;margin-bottom:7px;">Refinaria · Brasil</div>
    <div style="font-size:15px;font-weight:700;color:#FFF;margin-bottom:4px;">{nome}</div>
    <span style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.35);
          border-radius:3px;padding:3px 9px;font-size:10px;color:white;font-weight:600;">{sigla}</span>
  </div>
  <div style="padding:14px 18px 10px 18px;">
    {campo("Empresa / Razão Social", empresa)}
    {campo("Município / UF", f"{munic} — {uf}")}
    {campo("Capacidade Autorizada", cap)}
    {campo("Ano de Inauguração", ano)}
    {campo("Fonte dos Dados", fonte)}
  </div>
</div>"""
    st.markdown(html, unsafe_allow_html=True)


def render_usina_panel(row: dict):
    def campo(label, valor):
        return (
            f'<div style="margin-bottom:10px;">'
            f'<div style="color:#8899bb;font-size:9.5px;text-transform:uppercase;'
            f'letter-spacing:.7px;font-weight:700;margin-bottom:3px;">{label}</div>'
            f'<div style="color:#1A2A3A;font-size:12.5px;font-weight:500;line-height:1.4;">{valor}</div>'
            f'</div>'
        )
    nome      = str(row.get("Nome",      "—"))
    cidade    = str(row.get("Cidade",    "—"))
    uf        = str(row.get("UF",        ""))
    tipo      = str(row.get("Tipo",      "—"))
    situacao  = str(row.get("Situacao",  "—"))
    classe    = str(row.get("Classecap", "—"))
    cap       = str(row.get("Caprocmi",  "—"))
    inicio    = str(row.get("Início da", "—"))
    html = f"""
<div style="background:white;border-radius:7px;border:1px solid #D8E3EC;
     box-shadow:0 3px 18px rgba(20,40,100,0.10);overflow:hidden;
     font-family:'Segoe UI',Arial,sans-serif;">
  <div style="background:linear-gradient(135deg,#0A3D1F 0%,#27AE60 100%);
       padding:16px 18px 14px;">
    <div style="font-size:8.5px;color:rgba(255,255,255,0.65);text-transform:uppercase;
         letter-spacing:1.3px;font-weight:700;margin-bottom:7px;">Usina de Etanol · Brasil</div>
    <div style="font-size:15px;font-weight:700;color:#FFF;margin-bottom:4px;">{nome}</div>
    <span style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.35);
          border-radius:3px;padding:3px 9px;font-size:10px;color:white;font-weight:600;">{tipo}</span>
  </div>
  <div style="display:flex;background:#F2F6FB;border-bottom:1px solid #D8E3EC;">
    <div style="flex:1;padding:12px 16px;border-right:1px solid #D8E3EC;">
      <div style="color:#8899bb;font-size:9px;text-transform:uppercase;letter-spacing:.7px;
           font-weight:700;margin-bottom:4px;">Capacidade</div>
      <div style="color:#0A3D1F;font-size:17px;font-weight:700;">{cap}</div>
      <div style="color:#8899bb;font-size:9px;">m³/dia</div>
    </div>
    <div style="flex:1;padding:12px 16px;">
      <div style="color:#8899bb;font-size:9px;text-transform:uppercase;letter-spacing:.7px;
           font-weight:700;margin-bottom:4px;">Início</div>
      <div style="color:#0A3D1F;font-size:17px;font-weight:700;">{inicio}</div>
    </div>
  </div>
  <div style="padding:14px 18px 10px 18px;">
    {campo("Município / UF", f"{cidade} — {uf}")}
    {campo("Situação Operacional", situacao)}
    {campo("Classe de Capacidade", classe)}
  </div>
</div>"""
    st.markdown(html, unsafe_allow_html=True)


def render_panel_placeholder():
    st.markdown("""
<div style="background:white;border-radius:7px;border:1.5px dashed #B8CDE0;
     display:flex;align-items:center;justify-content:center;flex-direction:column;
     padding:48px 24px;text-align:center;min-height:460px;">
  <svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="#B0C4DE"
       stroke-width="1.2" style="margin-bottom:16px;">
    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
    <circle cx="12" cy="10" r="3"/>
  </svg>
  <div style="font-size:14px;font-weight:700;color:#6B7A8D;margin-bottom:6px;">
    Selecione um projeto
  </div>
  <div style="font-size:12px;color:#9AABBE;line-height:1.6;max-width:200px;">
    Clique em um marcador<br>no mapa para ver os<br>detalhes do projeto
  </div>
</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    logo_path = Path(__file__).parent / "cehtes_azul_vertical.png"
    if logo_path.exists():
        b64 = logo_b64(logo_path)
        st.markdown(
            f'<div style="text-align:center;padding:6px 12px 8px 12px;'
            f'border-bottom:1px solid rgba(104,194,197,0.18);margin-bottom:2px">'
            f'<img src="data:image/png;base64,{b64}"'
            f' style="width:auto;max-width:100%;max-height:72px;filter:brightness(0) invert(1);">'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── 1. FUNDO DO MAPA ─────────────────────────────────────────────────────
    st.markdown('<span class="sb-label">◎ &nbsp;Fundo do Mapa</span>', unsafe_allow_html=True)
    TILES = {
        "○  Claro"       : "CartoDB positron",
        "◑  Escuro"      : "CartoDB dark_matter",
        "◎  OpenStreet"  : "OpenStreetMap",
        "⊙  Satélite"    : "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "□  Só Malha"    : None,
    }
    tile_choice = st.selectbox(
        "tile", list(TILES.keys()),
        label_visibility="collapsed",
        key="tile_sel",
    )
    tile_url = TILES[tile_choice]

    # ── 2. PROJETOS SAF ──────────────────────────────────────────────────────
    st.markdown('<hr class="sb-divider">', unsafe_allow_html=True)
    projetos_disp = df_saf["Projeto"].dropna().astype(str).tolist()
    _n_sel = len(st.session_state.get("sel_projetos", projetos_disp))
    st.markdown(
        f'<span class="sb-label">◉ &nbsp;Projetos SAF'
        f'<span class="sb-badge">{_n_sel} / {len(projetos_disp)}</span>'
        f'</span>',
        unsafe_allow_html=True,
    )
    _c1, _c2 = st.columns(2, gap="small")
    with _c1:
        if st.button("✓ Todos", key="btn_todos"):
            st.session_state["sel_projetos"] = projetos_disp
    with _c2:
        if st.button("✕ Nenhum", key="btn_nenhum"):
            st.session_state["sel_projetos"] = []
    projetos_sel = st.multiselect(
        "projetos",
        options=projetos_disp,
        default=projetos_disp,
        label_visibility="collapsed",
        key="sel_projetos",
        placeholder="Filtrar projetos...",
    )

    # ── 3. CAMADAS DO MAPA ───────────────────────────────────────────────────
    st.markdown('<hr class="sb-divider">', unsafe_allow_html=True)
    st.markdown('<span class="sb-label">⊕ &nbsp;Camadas do Mapa</span>', unsafe_allow_html=True)
    show_ref = st.toggle("Refinarias de Petróleo", value=False, key="show_ref")
    show_usi = st.toggle("Usinas de Etanol",        value=False, key="show_usi")
    show_fed = st.toggle("Rodovias Federais",        value=False, key="show_fed")
    show_est = st.toggle("Rodovias Estaduais",       value=False, key="show_est")

    # ── 4. FEEDSTOCKS SAF ────────────────────────────────────────────────────
    st.markdown('<hr class="sb-divider">', unsafe_allow_html=True)
    st.markdown('<span class="sb-label">◆ &nbsp;Feedstocks · SAF</span>', unsafe_allow_html=True)

    _feed_opts = ["— Desativado", "▸  Soja", "▸  Milho", "▸  Cana-de-açúcar"]
    _feed_raw = st.radio(
        "feed_prod", _feed_opts,
        label_visibility="collapsed",
        key="feed_produto",
    )
    show_feed    = _feed_raw != "— Desativado"
    feed_produto = None
    feed_ano     = None
    feed_tipo    = "Coroplético"

    if show_feed:
        feed_produto = _feed_raw.replace("▸", "").strip()
        if feed_produto == "Cana-de-açúcar":
            _ano_min, _ano_max, _ano_def = 2005, 2024, 2024
        else:
            _ano_min, _ano_max, _ano_def = 2010, 2023, 2023
        feed_ano = st.slider(
            "Ano", _ano_min, _ano_max, _ano_def,
            key="feed_ano",
        )
        feed_tipo_raw = st.radio(
            "feed_tipo",
            ["◫  Coroplético", "≋  Mapa de Calor"],
            label_visibility="collapsed",
            key="feed_tipo",
        )
        feed_tipo = "Mapa de Calor" if "Calor" in feed_tipo_raw else "Coroplético"

    # ── Footer ───────────────────────────────────────────────────────────────
    st.markdown(
        f'<p style="margin-top:18px;font-size:0.5rem;color:{TEXT};'
        f'opacity:0.32;text-align:center;letter-spacing:.09em;line-height:2">'
        f'SIEV · Inteligência em Energias Verdes · CEHTES 2025</p>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ÁREA PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════
num_ufs     = len(gdf)
num_regioes = gdf["NM_REGIAO"].nunique()

# Carregar camadas adicionais somente quando ativadas (cache garante 1 load)
gdf_ref = load_refinarias()   if show_ref else None
gdf_usi = load_usinas()       if show_usi else None
gdf_fed = load_rodovias_fed() if show_fed else None
gdf_est = load_rodovias_est() if show_est else None

# ── Feedstock choropleth data ─────────────────────────────────────────────────
feed_gdf_map   = None
feed_col_map   = 'producao'
feed_cap_map   = 'Produção (t)'
feed_name_map  = 'Feedstock SAF'
feed_id_map    = 'CD_MUN'
feed_label_map = 'NM_MUN'

if show_feed and feed_produto and feed_ano:
    _pk = {"Soja": "soja", "Milho": "milho", "Cana-de-açúcar": "cana"}[feed_produto]

    if feed_produto in ("Soja", "Milho"):
        with st.spinner(f"Carregando {feed_produto} {feed_ano}…"):
            _prod = load_feedstock_municipio(_pk, feed_ano)
        if not _prod.empty:
            _gdf_m   = load_municipios_shp()
            _merged  = _gdf_m.merge(_prod[['CD_MUN', 'producao', 'mun_nome']], on='CD_MUN', how='inner')
            feed_gdf_map   = _merged
            feed_col_map   = 'producao'
            feed_cap_map   = f'{feed_produto} · Produção {feed_ano} (t)'
            feed_name_map  = f'{feed_produto} · Produção municipal'
            feed_id_map    = 'CD_MUN'
            feed_label_map = 'NM_MUN'

    else:  # Cana → nível estadual
        with st.spinner("Carregando Cana-de-açúcar…"):
            _cana = load_feedstock_serie('cana')
        if not _cana.empty:
            _sfra   = f"{feed_ano}/{str(feed_ano + 1)[-2:]}"
            _ca_ano = (_cana[_cana['safra'] == _sfra]
                       .groupby('uf')['producao_mil_ton'].sum()
                       .reset_index()
                       .rename(columns={'uf': 'SIGLA_UF'}))
            _ca_ano['producao'] = _ca_ano['producao_mil_ton'] * 1000
            _merged_uf = gdf.merge(_ca_ano[['SIGLA_UF', 'producao']], on='SIGLA_UF', how='left')
            _merged_uf = _merged_uf[_merged_uf['producao'].notna()].copy()
            feed_gdf_map   = _merged_uf
            feed_col_map   = 'producao'
            feed_cap_map   = f'Cana · Produção Safra {_sfra} (t)'
            feed_name_map  = 'Cana-de-açúcar · Produção estadual'
            feed_id_map    = 'SIGLA_UF'
            feed_label_map = 'NM_UF'

# Lookup para detecção de cliques no mapa
_ref_lookup = (
    {str(r["nome_inst"]).strip(): {**{k: v for k, v in r.items() if k != "geometry"}, "_type": "refinaria"}
     for _, r in gdf_ref.iterrows()}
    if gdf_ref is not None else {}
)
_usi_lookup = (
    {str(r["Nome"]).strip(): {**{k: v for k, v in r.items() if k != "geometry"}, "_type": "usina"}
     for _, r in gdf_usi.iterrows()}
    if gdf_usi is not None else {}
)

# Aplicar filtro de projetos ao dataframe do mapa
if projetos_sel:
    df_mapa = df_saf[df_saf["Projeto"].astype(str).isin(projetos_sel)].reset_index(drop=True)
else:
    df_mapa = df_saf.iloc[0:0].reset_index(drop=True)

num_projetos      = len(df_mapa)
num_projetos_total = len(df_saf)

# ── Topbar ───────────────────────────────────────────────────────────────────
st.markdown(
    f'<div class="topbar">'
    f'  <div class="topbar-left">'
    f'    <span class="topbar-title">SIEV &nbsp;|&nbsp; Sistema de Inteligência em Energias Verdes</span>'
    f'    <span class="topbar-sub">Mapeamento Territorial · Brasil · SAF &amp; Energias Renováveis</span>'
    f'  </div>'
    f'  <span class="topbar-badge">CEHTES</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# ── Stat Cards ───────────────────────────────────────────────────────────────
st.markdown(
    f'<div class="cards-row">'
    f'  <div class="stat-card">'
    f'    <div class="s-label">Estados Mapeados</div>'
    f'    <div class="s-value">{num_ufs}<span class="s-unit">UFs</span></div>'
    f'  </div>'
    f'  <div class="stat-card">'
    f'    <div class="s-label">Projetos no Mapa</div>'
    f'    <div class="s-value">{num_projetos}'
    f'    <span class="s-unit">/ {num_projetos_total}</span></div>'
    f'  </div>'
    f'  <div class="stat-card">'
    f'    <div class="s-label">Regiões</div>'
    f'    <div class="s-value">{num_regioes}<span class="s-unit">regiões</span></div>'
    f'  </div>'
    f'  <div class="stat-card">'
    f'    <div class="s-label">Camada Ativa</div>'
    f'    <div class="s-text">{tile_choice}</div>'
    f'  </div>'
    f'</div>',
    unsafe_allow_html=True,
)

# ── Mapa + Painel ─────────────────────────────────────────────────────────────
# Session state
if "selected_project" not in st.session_state:
    st.session_state.selected_project = None

col_map, col_panel = st.columns([3, 1.6], gap="small")

with col_map:
    m = build_map(df_mapa, gdf, tile_choice, tile_url,
                  gdf_ref=gdf_ref, gdf_usi=gdf_usi, gdf_fed=gdf_fed, gdf_est=gdf_est,
                  feed_gdf=feed_gdf_map, feed_col=feed_col_map,
                  feed_caption=feed_cap_map, feed_name=feed_name_map,
                  feed_id_col=feed_id_map, feed_label_col=feed_label_map,
                  feed_tipo=feed_tipo)
    map_output = st_folium(
        m,
        width="stretch",
        height=560,
        returned_objects=["last_object_clicked_tooltip"],
    )

    # Detectar clique em marcador via tooltip
    if map_output:
        tooltip_val = map_output.get("last_object_clicked_tooltip")
        if tooltip_val:
            tooltip_clean = re.sub(r"<[^>]+>", "", str(tooltip_val)).strip()
            # SAF projects
            matched = False
            for _, row in df_saf.iterrows():
                if str(row.get("Projeto", "")).strip() == tooltip_clean:
                    st.session_state.selected_project = {**row.to_dict(), "_type": "saf"}
                    matched = True
                    break
            # Refinarias
            if not matched and tooltip_clean in _ref_lookup:
                st.session_state.selected_project = _ref_lookup[tooltip_clean]
                matched = True
            # Usinas
            if not matched and tooltip_clean in _usi_lookup:
                st.session_state.selected_project = _usi_lookup[tooltip_clean]

with col_panel:
    sel = st.session_state.selected_project
    if sel:
        _t = sel.get("_type", "saf")
        if _t == "refinaria":
            _title = str(sel.get("nome_inst", "Refinaria"))
            with st.expander(_title, expanded=True):
                render_refinaria_panel(sel)
        elif _t == "usina":
            _title = str(sel.get("Nome", "Usina de Etanol"))
            with st.expander(_title, expanded=True):
                render_usina_panel(sel)
        else:
            _title = str(sel.get("Projeto", "Projeto SAF"))
            with st.expander(_title, expanded=True):
                render_panel(sel)
    else:
        render_panel_placeholder()


# ══════════════════════════════════════════════════════════════════════════════
# SÉRIE HISTÓRICA DE FEEDSTOCKS
# ══════════════════════════════════════════════════════════════════════════════
if show_feed and feed_produto and feed_ano:
    _pk_ts = {"Soja": "soja", "Milho": "milho", "Cana-de-açúcar": "cana"}[feed_produto]
    st.markdown(
        f'<div class="section-header">Série Histórica · {feed_produto} · Evolução por Estado</div>',
        unsafe_allow_html=True,
    )
    with st.spinner("Carregando série histórica…"):
        _serie = load_feedstock_serie(_pk_ts)

    if not _serie.empty:
        ts_col1, ts_col2 = st.columns([3, 2], gap="small")

        with ts_col1:
            # ── Linha: produção por UF ao longo dos anos ─────────────────
            if 'producao_mil_ton' in _serie.columns and 'safra' in _serie.columns:
                _agg   = (_serie.groupby(['safra', 'uf'])['producao_mil_ton']
                          .sum().reset_index())
                _top8  = (_agg.groupby('uf')['producao_mil_ton']
                          .sum().nlargest(8).index.tolist())
                _agg_t = _agg[_agg['uf'].isin(_top8)]

                fig_ts = go.Figure()
                _colors_ts = [TEAL, GREEN, NAVY, "#E67E22", "#8E44AD",
                              "#C0392B", "#27AE60", "#2C3E50"]
                for _i, _uf in enumerate(_top8):
                    _d = _agg_t[_agg_t['uf'] == _uf].sort_values('safra')
                    fig_ts.add_trace(go.Scatter(
                        x=_d['safra'], y=_d['producao_mil_ton'],
                        mode='lines+markers', name=_uf,
                        line=dict(width=2, color=_colors_ts[_i % len(_colors_ts)]),
                        marker=dict(size=5),
                    ))
                fig_ts.update_layout(
                    title=dict(text=f'{feed_produto} · Produção por Estado (mil t)',
                               font=dict(size=13, color=NAVY2)),
                    xaxis=dict(title='Safra', tickangle=-45),
                    yaxis=dict(title='Produção (mil t)'),
                    height=350, template='plotly_white',
                    legend=dict(orientation='h', y=-0.35, x=0),
                    margin=dict(l=10, r=10, t=45, b=80),
                    plot_bgcolor='white',
                )
                st.plotly_chart(fig_ts, width="stretch")

        with ts_col2:
            # ── Barras: top 10 para o ano selecionado ────────────────────
            if feed_produto in ("Soja", "Milho") and feed_gdf_map is not None and not feed_gdf_map.empty:
                _top10 = (feed_gdf_map[['NM_MUN', 'SIGLA_UF', 'producao']]
                          .nlargest(10, 'producao').copy())
                _top10['label'] = _top10['NM_MUN'] + ' — ' + _top10['SIGLA_UF']
                fig_top = go.Figure(go.Bar(
                    x=_top10['producao'] / 1000,
                    y=_top10['label'],
                    orientation='h',
                    marker_color=TEAL,
                    text=(_top10['producao'] / 1000).round(0).astype(int).astype(str) + ' mil t',
                    textposition='outside',
                ))
                fig_top.update_layout(
                    title=dict(text=f'Top 10 Municípios · {feed_produto} {feed_ano}',
                               font=dict(size=13, color=NAVY2)),
                    xaxis=dict(title='Produção (mil t)'),
                    height=350, template='plotly_white',
                    yaxis=dict(autorange='reversed'),
                    margin=dict(l=10, r=80, t=45, b=20),
                    plot_bgcolor='white',
                )
                st.plotly_chart(fig_top, width="stretch")

            elif feed_produto == "Cana-de-açúcar" and not _serie.empty:
                _sfra_bar = f"{feed_ano}/{str(feed_ano + 1)[-2:]}"
                _cana_bar = (_serie[_serie['safra'] == _sfra_bar]
                             .groupby('uf')['producao_mil_ton']
                             .sum().nlargest(10).reset_index())
                _cana_bar.columns = ['UF', 'Produção (mil t)']
                fig_bar = go.Figure(go.Bar(
                    x=_cana_bar['Produção (mil t)'],
                    y=_cana_bar['UF'],
                    orientation='h',
                    marker_color=GREEN,
                    text=_cana_bar['Produção (mil t)'].round(0).astype(int).astype(str) + ' mil t',
                    textposition='outside',
                ))
                fig_bar.update_layout(
                    title=dict(text=f'Top 10 Estados · Cana Safra {_sfra_bar}',
                               font=dict(size=13, color=NAVY2)),
                    xaxis=dict(title='Produção (mil t)'),
                    height=350, template='plotly_white',
                    yaxis=dict(autorange='reversed'),
                    margin=dict(l=10, r=80, t=45, b=20),
                    plot_bgcolor='white',
                )
                st.plotly_chart(fig_bar, width="stretch")
    else:
        st.info(f"Dados históricos de {feed_produto} não disponíveis no momento.")

# ══════════════════════════════════════════════════════════════════════════════
# GRÁFICOS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(
    '<div class="section-header">Análise dos Projetos SAF · Capacidade &amp; Distribuição Tecnológica</div>',
    unsafe_allow_html=True,
)

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Capacidade por Rota",
    "Capacidade + Distribuição",
    "Linha do Tempo",
    "Distribuição Acumulada",
    "Evolução Acumulada",
])

with tab1:
    st.plotly_chart(criar_grafico_barras_saf(), width="stretch")

with tab2:
    st.plotly_chart(criar_grafico_barras_bolhas_saf(), width="stretch")

with tab3:
    st.plotly_chart(criar_grafico_timeline_saf(), width="stretch")

with tab4:
    st.plotly_chart(criar_grafico_rosca_saf(), width="stretch")

with tab5:
    st.plotly_chart(criar_grafico_acumulado_saf(), width="stretch")
