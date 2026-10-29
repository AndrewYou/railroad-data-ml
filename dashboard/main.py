"""Dashboard entry point: page setup shared by both pages, and the navigation between them.

Run: streamlit run dashboard/main.py
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root, for `rail` (Streamlit Cloud has no PYTHONPATH)

import charts

st.set_page_config(page_title="Daniel Plainview's Dashboard", page_icon="🛢️", layout="wide")
st.markdown("""<style>
  .block-container {padding: 3rem 1.5rem 0.5rem; max-width: 100%;}
  div[data-testid="stVerticalBlock"] {gap: 0.35rem;}
</style>""", unsafe_allow_html=True)
charts.set_theme(st.context.theme.type == "dark")

st.navigation([st.Page("app.py", title="Equity Research", default=True),
               st.Page("nowcast_page.py", title="Carload Projection (Experiment)")], position="top").run()
