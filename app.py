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

# ── Traduções PT / EN ─────────────────────────────────────────────────────────
def get_lang() -> str:
    v = st.session_state.get("lang_sel", "🇧🇷 PT")
    return "en" if "EN" in str(v) else "pt"

T: dict = {
    "pt": {
        "sb_map_bg":     "◎ &nbsp;Fundo do Mapa",
        "sb_projects":   "◉ &nbsp;Projetos SAF",
        "sb_layers":     "⊕ &nbsp;Camadas do Mapa",
        "sb_feedstocks": "◆ &nbsp;Feedstocks · SAF",
        "btn_all":       "✓ Todos",
        "btn_none":      "✕ Nenhum",
        "lyr_ref":       "Refinarias de Petróleo",
        "lyr_usi":       "Usinas de Etanol",
        "lyr_fed":       "Rodovias Federais",
        "lyr_est":       "Rodovias Estaduais",
        "feed_off":      "— Desativado",
        "feed_soy":      "▸  Soja",
        "feed_corn":     "▸  Milho",
        "feed_cane":     "▸  Cana-de-açúcar",
        "feed_year_lbl": "Ano",
        "feed_choro":    "◫  Coroplético",
        "feed_heat":     "≋  Mapa de Calor",
        "filter_ph":     "Filtrar projetos...",
        "footer":        "SIEV · Inteligência em Energias Verdes · CEHTES 2025",
        "topbar_sub":    "Mapeamento Territorial · Brasil · SAF &amp; Energias Renováveis",
        "card_states":   "Estados Mapeados",
        "card_states_u": "UFs",
        "card_projects": "Projetos no Mapa",
        "card_regions":  "Regiões",
        "card_regions_u":"regiões",
        "card_layer":    "Camada Ativa",
        "ph_title":      "Selecione um projeto",
        "ph_body":       "Clique em um marcador<br>no mapa para ver os<br>detalhes do projeto",
        "p_saf_type":    "Projeto SAF · Brasil",
        "p_cap":         "Capacidade SAF",
        "p_cap_u":       "m³/ano",
        "p_year":        "Ano de Início",
        "p_city":        "Município / UF",
        "p_feed":        "Feedstock Principal",
        "p_invest":      "Investimento",
        "p_stage":       "Estágio do Projeto",
        "p_stage_d":     "Descrição do Estágio",
        "p_sources":     "Fontes",
        "r_type":        "Refinaria · Brasil",
        "r_company":     "Empresa / Razão Social",
        "r_city":        "Município / UF",
        "r_cap":         "Capacidade Autorizada",
        "r_year":        "Ano de Inauguração",
        "r_source":      "Fonte dos Dados",
        "u_type":        "Usina de Etanol · Brasil",
        "u_cap":         "Capacidade",
        "u_cap_u":       "m³/dia",
        "u_start":       "Início",
        "u_city":        "Município / UF",
        "u_status":      "Situação Operacional",
        "u_class":       "Classe de Capacidade",
        "leg_route":     "Rota Tecnológica",
        "leg_layers":    "Camadas Ativas",
        "rt_copro":      "Coprocessamento HEFA",
        "rt_hefa":       "HEFA Dedicado",
        "rt_atj":        "ATJ (Alcohol-to-Jet)",
        "rt_ft":         "FT (Fischer-Tropsch)",
        "rt_other":      "Outros",
        "map_state":     "Estado:",
        "map_uf":        "UF:",
        "map_region":    "Região:",
        "feed_prod_u":   "Produção (t)",
        "feed_lyr":      "Feedstock SAF",
        "sec_feed":      "Série Histórica · {name} · Evolução por Estado",
        "sec_charts":    "Análise dos Projetos SAF · Capacidade &amp; Distribuição Tecnológica",
        "tab1":          "Capacidade por Rota",
        "tab2":          "Capacidade + Distribuição",
        "tab3":          "Linha do Tempo",
        "tab4":          "Distribuição Acumulada",
        "tab5":          "Evolução Acumulada",
        "sp_load":       "Carregando {} {}…",
        "sp_cane":       "Carregando Cana-de-açúcar…",
        "sp_hist":       "Carregando série histórica…",
        "no_data":       "Dados históricos de {} não disponíveis no momento.",
        "ch_by_state":   "{} · Produção por Estado (mil t)",
        "ch_season":     "Safra",
        "ch_prod_u":     "Produção (mil t)",
        "ch_top10_mun":  "Top 10 Municípios · {} {}",
        "ch_prod_unit_t":"Produção (mil t)",
        "ch_top10_uf":   "Top 10 Estados · Cana Safra {}",
        "tile_light":    "○  Claro",
        "tile_dark":     "◑  Escuro",
        "tile_osm":      "◎  OpenStreet",
        "tile_sat":      "⊙  Satélite",
        "tile_mesh":     "□  Só Malha",
        "lyr_ref_map":   "Refinarias de Petróleo",
        "lyr_usi_map":   "Usinas de Etanol",
        "lyr_fed_map":   "Rodovias Federais",
        "lyr_est_map":   "Rodovias Estaduais",
        "feed_soy_name": "Soja",
        "feed_corn_name":"Milho",
        "feed_cane_name":"Cana-de-açúcar",
        "feed_mun_prod": "{} · Produção {} (t)",
        "feed_mun_lyr":  "{} · Produção municipal",
        "feed_uf_prod":  "Cana · Produção Safra {} (t)",
        "feed_uf_lyr":   "Cana-de-açúcar · Produção estadual",
    },
    "en": {
        "sb_map_bg":     "◎ &nbsp;Map Background",
        "sb_projects":   "◉ &nbsp;SAF Projects",
        "sb_layers":     "⊕ &nbsp;Map Layers",
        "sb_feedstocks": "◆ &nbsp;Feedstocks · SAF",
        "btn_all":       "✓ All",
        "btn_none":      "✕ None",
        "lyr_ref":       "Oil Refineries",
        "lyr_usi":       "Ethanol Plants",
        "lyr_fed":       "Federal Highways",
        "lyr_est":       "State Highways",
        "feed_off":      "— Disabled",
        "feed_soy":      "▸  Soybean",
        "feed_corn":     "▸  Corn",
        "feed_cane":     "▸  Sugarcane",
        "feed_year_lbl": "Year",
        "feed_choro":    "◫  Choropleth",
        "feed_heat":     "≋  Heat Map",
        "filter_ph":     "Filter projects...",
        "footer":        "SIEV · Green Energy Intelligence · CEHTES 2025",
        "topbar_sub":    "Territorial Mapping · Brazil · SAF &amp; Renewable Energies",
        "card_states":   "States Mapped",
        "card_states_u": "UFs",
        "card_projects": "Projects on Map",
        "card_regions":  "Regions",
        "card_regions_u":"regions",
        "card_layer":    "Active Layer",
        "ph_title":      "Select a project",
        "ph_body":       "Click on a marker<br>on the map to view<br>project details",
        "p_saf_type":    "SAF Project · Brazil",
        "p_cap":         "SAF Capacity",
        "p_cap_u":       "m³/year",
        "p_year":        "Start Year",
        "p_city":        "City / State",
        "p_feed":        "Main Feedstock",
        "p_invest":      "Investment",
        "p_stage":       "Project Stage",
        "p_stage_d":     "Stage Description",
        "p_sources":     "Sources",
        "r_type":        "Refinery · Brazil",
        "r_company":     "Company",
        "r_city":        "City / State",
        "r_cap":         "Authorized Capacity",
        "r_year":        "Opening Year",
        "r_source":      "Data Source",
        "u_type":        "Ethanol Plant · Brazil",
        "u_cap":         "Capacity",
        "u_cap_u":       "m³/day",
        "u_start":       "Start",
        "u_city":        "City / State",
        "u_status":      "Operational Status",
        "u_class":       "Capacity Class",
        "leg_route":     "Technology Route",
        "leg_layers":    "Active Layers",
        "rt_copro":      "Co-processing HEFA",
        "rt_hefa":       "Dedicated HEFA",
        "rt_atj":        "ATJ (Alcohol-to-Jet)",
        "rt_ft":         "FT (Fischer-Tropsch)",
        "rt_other":      "Others",
        "map_state":     "State:",
        "map_uf":        "UF:",
        "map_region":    "Region:",
        "feed_prod_u":   "Production (t)",
        "feed_lyr":      "SAF Feedstock",
        "sec_feed":      "Historical Series · {name} · State Evolution",
        "sec_charts":    "SAF Projects Analysis · Capacity &amp; Technology Distribution",
        "tab1":          "Capacity by Route",
        "tab2":          "Capacity + Distribution",
        "tab3":          "Timeline",
        "tab4":          "Cumulative Distribution",
        "tab5":          "Cumulative Evolution",
        "sp_load":       "Loading {} {}…",
        "sp_cane":       "Loading Sugarcane…",
        "sp_hist":       "Loading historical series…",
        "no_data":       "Historical data for {} not available at the moment.",
        "ch_by_state":   "{} · Production by State (thousand t)",
        "ch_season":     "Season",
        "ch_prod_u":     "Production (thousand t)",
        "ch_top10_mun":  "Top 10 Municipalities · {} {}",
        "ch_prod_unit_t":"Production (thousand t)",
        "ch_top10_uf":   "Top 10 States · Sugarcane Season {}",
        "tile_light":    "○  Light",
        "tile_dark":     "◑  Dark",
        "tile_osm":      "◎  OpenStreet",
        "tile_sat":      "⊙  Satellite",
        "tile_mesh":     "□  Mesh Only",
        "lyr_ref_map":   "Oil Refineries",
        "lyr_usi_map":   "Ethanol Plants",
        "lyr_fed_map":   "Federal Highways",
        "lyr_est_map":   "State Highways",
        "feed_soy_name": "Soybean",
        "feed_corn_name":"Corn",
        "feed_cane_name":"Sugarcane",
        "feed_mun_prod": "{} · Production {} (t)",
        "feed_mun_lyr":  "{} · Municipal Production",
        "feed_uf_prod":  "Sugarcane · Season {} Production (t)",
        "feed_uf_lyr":   "Sugarcane · State Production",
    },
}

# Internal constants (language-agnostic)
_TILE_URLS = [
    "CartoDB positron",
    "CartoDB dark_matter",
    "OpenStreetMap",
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    None,
]
_FEED_PT_NAMES = ["", "Soja", "Milho", "Cana-de-açúcar"]  # index 0 = disabled

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
            aliases=[T[get_lang()]["map_state"], T[get_lang()]["map_uf"], T[get_lang()]["map_region"]],
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
    _lg = get_lang()
    legenda_itens = [
        (T[_lg]["rt_copro"], "#1B4F8A"),
        (T[_lg]["rt_hefa"],  "#2980B9"),
        (T[_lg]["rt_atj"],   "#E67E22"),
        (T[_lg]["rt_ft"],    "#1A7F4B"),
        (T[_lg]["rt_other"], "#607D8B"),
    ]
    legenda_html = f"""
<div style="position:fixed;bottom:24px;left:16px;background:white;padding:12px 16px;
     border-radius:7px;border:1px solid #D8E3EC;font-family:'Segoe UI',Arial,sans-serif;
     font-size:11.5px;box-shadow:0 3px 10px rgba(0,0,0,0.13);z-index:1000;min-width:190px;">
  <div style="font-weight:700;margin-bottom:9px;color:#0D2E57;font-size:11px;
       text-transform:uppercase;letter-spacing:.8px;">{T[_lg]["leg_route"]}</div>
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
        extras.append((T[_lg]["lyr_ref_map"], "#1a1a1a", "●"))
    if gdf_usi is not None:
        extras.append((T[_lg]["lyr_usi_map"], "#27AE60", "●"))
    if gdf_fed is not None:
        extras.append((T[_lg]["lyr_fed_map"], "#1565C0", "—"))
    if gdf_est is not None:
        extras.append((T[_lg]["lyr_est_map"], "#E65100", "—"))
    if extras:
        legenda_extra = f"""
<div style="position:fixed;bottom:24px;left:220px;background:white;padding:10px 14px;
     border-radius:7px;border:1px solid #D8E3EC;font-family:'Segoe UI',Arial,sans-serif;
     font-size:11.5px;box-shadow:0 3px 10px rgba(0,0,0,0.13);z-index:1000;min-width:180px;">
  <div style="font-weight:700;margin-bottom:8px;color:#0D2E57;font-size:11px;
       text-transform:uppercase;letter-spacing:.8px;">{T[_lg]["leg_layers"]}</div>
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
    lang = get_lang()
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
         letter-spacing:1.3px;font-weight:700;margin-bottom:7px;">{T[lang]["p_saf_type"]}</div>
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
           font-weight:700;margin-bottom:4px;">{T[lang]["p_cap"]}</div>
      <div style="color:{DARK};font-size:20px;font-weight:700;">{capacidade}</div>
      <div style="color:#8899bb;font-size:9px;margin-top:1px;">{T[lang]["p_cap_u"]}</div>
    </div>
    <div style="flex:1;padding:12px 16px;">
      <div style="color:#8899bb;font-size:9px;text-transform:uppercase;letter-spacing:.7px;
           font-weight:700;margin-bottom:4px;">{T[lang]["p_year"]}</div>
      <div style="color:{DARK};font-size:20px;font-weight:700;">{ano}</div>
    </div>
  </div>

  <!-- Campos de detalhe -->
  <div style="padding:14px 18px 6px 18px;">
    {campo(T[lang]["p_city"], municipio)}
    {campo(T[lang]["p_feed"], feedstock)}
    {campo(T[lang]["p_invest"], investimento)}
    {campo(T[lang]["p_stage"], estagio)}
    {campo(T[lang]["p_stage_d"], base)}
  </div>

  <!-- Fontes -->
  {"" if not fontes_html else f'''
  <div style="padding:10px 18px 14px 18px;border-top:1px solid #EEF2F7;margin-top:4px;">
    <div style="color:#8899bb;font-size:9px;text-transform:uppercase;letter-spacing:.7px;
         font-weight:700;margin-bottom:7px;">{T[lang]["p_sources"]}</div>
    {fontes_html}
  </div>'''}

</div>"""

    st.markdown(html, unsafe_allow_html=True)


def render_refinaria_panel(row: dict):
    lang = get_lang()
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
         letter-spacing:1.3px;font-weight:700;margin-bottom:7px;">{T[lang]["r_type"]}</div>
    <div style="font-size:15px;font-weight:700;color:#FFF;margin-bottom:4px;">{nome}</div>
    <span style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.35);
          border-radius:3px;padding:3px 9px;font-size:10px;color:white;font-weight:600;">{sigla}</span>
  </div>
  <div style="padding:14px 18px 10px 18px;">
    {campo(T[lang]["r_company"], empresa)}
    {campo(T[lang]["r_city"], f"{munic} — {uf}")}
    {campo(T[lang]["r_cap"], cap)}
    {campo(T[lang]["r_year"], ano)}
    {campo(T[lang]["r_source"], fonte)}
  </div>
</div>"""
    st.markdown(html, unsafe_allow_html=True)


def render_usina_panel(row: dict):
    lang = get_lang()
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
         letter-spacing:1.3px;font-weight:700;margin-bottom:7px;">{T[lang]["u_type"]}</div>
    <div style="font-size:15px;font-weight:700;color:#FFF;margin-bottom:4px;">{nome}</div>
    <span style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.35);
          border-radius:3px;padding:3px 9px;font-size:10px;color:white;font-weight:600;">{tipo}</span>
  </div>
  <div style="display:flex;background:#F2F6FB;border-bottom:1px solid #D8E3EC;">
    <div style="flex:1;padding:12px 16px;border-right:1px solid #D8E3EC;">
      <div style="color:#8899bb;font-size:9px;text-transform:uppercase;letter-spacing:.7px;
           font-weight:700;margin-bottom:4px;">{T[lang]["u_cap"]}</div>
      <div style="color:#0A3D1F;font-size:17px;font-weight:700;">{cap}</div>
      <div style="color:#8899bb;font-size:9px;">{T[lang]["u_cap_u"]}</div>
    </div>
    <div style="flex:1;padding:12px 16px;">
      <div style="color:#8899bb;font-size:9px;text-transform:uppercase;letter-spacing:.7px;
           font-weight:700;margin-bottom:4px;">{T[lang]["u_start"]}</div>
      <div style="color:#0A3D1F;font-size:17px;font-weight:700;">{inicio}</div>
    </div>
  </div>
  <div style="padding:14px 18px 10px 18px;">
    {campo(T[lang]["u_city"], f"{cidade} — {uf}")}
    {campo(T[lang]["u_status"], situacao)}
    {campo(T[lang]["u_class"], classe)}
  </div>
</div>"""
    st.markdown(html, unsafe_allow_html=True)


def render_panel_placeholder():
    lang = get_lang()
    st.markdown(f"""
<div style="background:white;border-radius:7px;border:1.5px dashed #B8CDE0;
     display:flex;align-items:center;justify-content:center;flex-direction:column;
     padding:48px 24px;text-align:center;min-height:460px;">
  <svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="#B0C4DE"
       stroke-width="1.2" style="margin-bottom:16px;">
    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
    <circle cx="12" cy="10" r="3"/>
  </svg>
  <div style="font-size:14px;font-weight:700;color:#6B7A8D;margin-bottom:6px;">
    {T[lang]["ph_title"]}
  </div>
  <div style="font-size:12px;color:#9AABBE;line-height:1.6;max-width:200px;">
    {T[lang]["ph_body"]}
  </div>
</div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
# ── Compute language (before sidebar so it's available everywhere) ────────────
lang = get_lang()

with st.sidebar:
    # ── Language selector ─────────────────────────────────────────────────────
    st.radio(
        "lang_sel",
        ["🇧🇷 PT", "🇬🇧 EN"],
        horizontal=True,
        label_visibility="collapsed",
        key="lang_sel",
    )
    lang = get_lang()

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
    st.markdown(f'<span class="sb-label">{T[lang]["sb_map_bg"]}</span>', unsafe_allow_html=True)
    _tile_labels = [T[lang]["tile_light"], T[lang]["tile_dark"], T[lang]["tile_osm"],
                    T[lang]["tile_sat"], T[lang]["tile_mesh"]]
    tile_idx = st.selectbox(
        "tile", range(5),
        format_func=lambda i: _tile_labels[i],
        label_visibility="collapsed",
        key="tile_sel_idx",
    )
    tile_url    = _TILE_URLS[tile_idx]
    tile_choice = _tile_labels[tile_idx]

    # ── 2. PROJETOS SAF ──────────────────────────────────────────────────────
    st.markdown('<hr class="sb-divider">', unsafe_allow_html=True)
    projetos_disp = df_saf["Projeto"].dropna().astype(str).tolist()
    _n_sel = len(st.session_state.get("sel_projetos", projetos_disp))
    st.markdown(
        f'<span class="sb-label">{T[lang]["sb_projects"]}'
        f'<span class="sb-badge">{_n_sel} / {len(projetos_disp)}</span>'
        f'</span>',
        unsafe_allow_html=True,
    )
    _c1, _c2 = st.columns(2, gap="small")
    with _c1:
        if st.button(T[lang]["btn_all"], key="btn_todos"):
            st.session_state["sel_projetos"] = projetos_disp
    with _c2:
        if st.button(T[lang]["btn_none"], key="btn_nenhum"):
            st.session_state["sel_projetos"] = []
    projetos_sel = st.multiselect(
        "projetos",
        options=projetos_disp,
        default=projetos_disp,
        label_visibility="collapsed",
        key="sel_projetos",
        placeholder=T[lang]["filter_ph"],
    )

    # ── 3. CAMADAS DO MAPA ───────────────────────────────────────────────────
    st.markdown('<hr class="sb-divider">', unsafe_allow_html=True)
    st.markdown(f'<span class="sb-label">{T[lang]["sb_layers"]}</span>', unsafe_allow_html=True)
    show_ref = st.toggle(T[lang]["lyr_ref"], value=False, key="show_ref")
    show_usi = st.toggle(T[lang]["lyr_usi"], value=False, key="show_usi")
    show_fed = st.toggle(T[lang]["lyr_fed"], value=False, key="show_fed")
    show_est = st.toggle(T[lang]["lyr_est"], value=False, key="show_est")

    # ── 4. FEEDSTOCKS SAF ────────────────────────────────────────────────────
    st.markdown('<hr class="sb-divider">', unsafe_allow_html=True)
    st.markdown(f'<span class="sb-label">{T[lang]["sb_feedstocks"]}</span>', unsafe_allow_html=True)

    _feed_opts = [T[lang]["feed_off"], T[lang]["feed_soy"], T[lang]["feed_corn"], T[lang]["feed_cane"]]
    _feed_idx = st.radio(
        "feed_prod", range(4),
        format_func=lambda i: _feed_opts[i],
        label_visibility="collapsed",
        key="feed_produto_idx",
    )
    show_feed    = _feed_idx > 0
    feed_produto = _FEED_PT_NAMES[_feed_idx] if _feed_idx > 0 else None
    feed_display = T[lang].get(f"feed_{['','soy','corn','cane'][_feed_idx]}_name", "") if _feed_idx > 0 else ""
    feed_ano     = None
    feed_tipo    = "Coroplético"

    if show_feed:
        if feed_produto == "Cana-de-açúcar":
            _ano_min, _ano_max, _ano_def = 2005, 2024, 2024
        else:
            _ano_min, _ano_max, _ano_def = 2010, 2023, 2023
        feed_ano = st.slider(
            T[lang]["feed_year_lbl"], _ano_min, _ano_max, _ano_def,
            key="feed_ano",
        )
        _tipo_idx = st.radio(
            "feed_tipo",
            range(2),
            format_func=lambda i: [T[lang]["feed_choro"], T[lang]["feed_heat"]][i],
            label_visibility="collapsed",
            key="feed_tipo_idx",
        )
        feed_tipo = "Mapa de Calor" if _tipo_idx == 1 else "Coroplético"

    # ── Footer ───────────────────────────────────────────────────────────────
    st.markdown(
        f'<p style="margin-top:18px;font-size:0.5rem;color:{TEXT};'
        f'opacity:0.32;text-align:center;letter-spacing:.09em;line-height:2">'
        f'{T[lang]["footer"]}</p>',
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
        with st.spinner(T[lang]["sp_load"].format(feed_display, feed_ano)):
            _prod = load_feedstock_municipio(_pk, feed_ano)
        if not _prod.empty:
            _gdf_m   = load_municipios_shp()
            _merged  = _gdf_m.merge(_prod[['CD_MUN', 'producao', 'mun_nome']], on='CD_MUN', how='inner')
            feed_gdf_map   = _merged
            feed_col_map   = 'producao'
            feed_cap_map   = T[lang]["feed_mun_prod"].format(feed_display, feed_ano)
            feed_name_map  = T[lang]["feed_mun_lyr"].format(feed_display)
            feed_id_map    = 'CD_MUN'
            feed_label_map = 'NM_MUN'

    else:  # Cana → nível estadual
        with st.spinner(T[lang]["sp_cane"]):
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
            feed_cap_map   = T[lang]["feed_uf_prod"].format(_sfra)
            feed_name_map  = T[lang]["feed_uf_lyr"]
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
    f'    <span class="topbar-title">Mapping of Sustainable Aviation Fuel (SAF) Projects &amp; Value Chains in Brazil</span>'
    f'    <span class="topbar-sub">{T[lang]["topbar_sub"]}</span>'
    f'  </div>'
    f'  <span class="topbar-badge">CEHTES</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# ── Stat Cards ───────────────────────────────────────────────────────────────
st.markdown(
    f'<div class="cards-row">'
    f'  <div class="stat-card">'
    f'    <div class="s-label">{T[lang]["card_states"]}</div>'
    f'    <div class="s-value">{num_ufs}<span class="s-unit">{T[lang]["card_states_u"]}</span></div>'
    f'  </div>'
    f'  <div class="stat-card">'
    f'    <div class="s-label">{T[lang]["card_projects"]}</div>'
    f'    <div class="s-value">{num_projetos}'
    f'    <span class="s-unit">/ {num_projetos_total}</span></div>'
    f'  </div>'
    f'  <div class="stat-card">'
    f'    <div class="s-label">{T[lang]["card_regions"]}</div>'
    f'    <div class="s-value">{num_regioes}<span class="s-unit">{T[lang]["card_regions_u"]}</span></div>'
    f'  </div>'
    f'  <div class="stat-card">'
    f'    <div class="s-label">{T[lang]["card_layer"]}</div>'
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
        f'<div class="section-header">{T[lang]["sec_feed"].format(name=feed_display)}</div>',
        unsafe_allow_html=True,
    )
    with st.spinner(T[lang]["sp_hist"]):
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
                    title=dict(text=T[lang]["ch_by_state"].format(feed_display),
                               font=dict(size=13, color=NAVY2)),
                    xaxis=dict(title=T[lang]["ch_season"], tickangle=-45),
                    yaxis=dict(title=T[lang]["ch_prod_u"]),
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
                    title=dict(text=T[lang]["ch_top10_mun"].format(feed_display, feed_ano),
                               font=dict(size=13, color=NAVY2)),
                    xaxis=dict(title=T[lang]["ch_prod_unit_t"]),
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
                    title=dict(text=T[lang]["ch_top10_uf"].format(_sfra_bar),
                               font=dict(size=13, color=NAVY2)),
                    xaxis=dict(title=T[lang]["ch_prod_unit_t"]),
                    height=350, template='plotly_white',
                    yaxis=dict(autorange='reversed'),
                    margin=dict(l=10, r=80, t=45, b=20),
                    plot_bgcolor='white',
                )
                st.plotly_chart(fig_bar, width="stretch")
    else:
        st.info(T[lang]["no_data"].format(feed_display))

# ══════════════════════════════════════════════════════════════════════════════
# GRÁFICOS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(
    f'<div class="section-header">{T[lang]["sec_charts"]}</div>',
    unsafe_allow_html=True,
)

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    T[lang]["tab1"],
    T[lang]["tab2"],
    T[lang]["tab3"],
    T[lang]["tab4"],
    T[lang]["tab5"],
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
