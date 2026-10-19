"""Plotly figures. One palette per theme, one style, and a high-resolution PNG export on every chart."""
from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go

FONT = "system-ui, -apple-system, Segoe UI, sans-serif"
RAILROADS = ("BNSF", "UP", "NS", "CSX", "CN", "CPKC")  # fixed order = fixed color per railroad
SEGMENTS = ("Intermodal", "Coal", "Merchandise")


@dataclass(frozen=True)
class Palette:
    series: tuple[str, ...]  # validated categorical order
    better: str              # diverging poles (blue = better, red = worse) and gray midpoint
    worse: str
    neutral: str
    surface: str
    ink: str
    ink_2: str
    muted: str
    grid: str
    baseline: str
    band: str                # shaded historical range


LIGHT = Palette(("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"),
                "#2a78d6", "#e34948", "#f0efec",
                "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "rgba(195,194,183,0.35)")
DARK = Palette(("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"),
               "#3987e5", "#e66767", "#383835",
               "#1a1a19", "#f0efec", "#c3c2b7", "#898781", "#2c2c2a", "#383835", "rgba(137,135,129,0.28)")
P = LIGHT


def set_theme(dark: bool) -> None:
    """Match the charts to the app theme (Streamlit menu: Settings -> Theme)."""
    global P
    P = DARK if dark else LIGHT


def color_for(group: str) -> str:
    if group in RAILROADS:
        return P.series[RAILROADS.index(group)]
    if group in SEGMENTS:
        return P.series[SEGMENTS.index(group)]
    return P.series[0]  # Network


def export_config(name: str) -> dict:
    """Modebar camera button saves a 3x PNG (deck-ready) named after the chart and data week."""
    return {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"],
            "toImageButtonOptions": {"format": "png", "scale": 3, "filename": name}}


def styled(fig: go.Figure, height: int, y_title: str | None = None, hover="x unified") -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=4, r=4, t=28, b=4), hovermode=hover,
        paper_bgcolor=P.surface, plot_bgcolor=P.surface, font=dict(family=FONT, size=12, color=P.ink_2),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, title=None, font=dict(size=11)),
        hoverlabel=dict(font=dict(family=FONT)))
    fig.update_xaxes(showgrid=False, linecolor=P.baseline, ticks="", title=None)
    fig.update_yaxes(gridcolor=P.grid, zeroline=False, linecolor=P.baseline, title=y_title, title_font_size=11)
    return fig


def zero_line(fig: go.Figure) -> None:
    fig.add_hline(y=0, line_width=1, line_color=P.baseline)


def diverging(higher_is_better: bool) -> list:
    low, high = (P.worse, P.better) if higher_is_better else (P.better, P.worse)
    return [[0, low], [0.5, P.neutral], [1, high]]


# Volume, drivers, share -------------------------------------------------------------------

def volume(weekly: pd.DataFrame, metric: str, since: pd.Timestamp, height: int) -> go.Figure:
    rows = weekly[weekly["week_ending"] >= since]
    fig = go.Figure()
    for group, g in rows.groupby("group", sort=False):
        color = color_for(group)
        if metric == "YoY %":
            fig.add_scatter(x=g["week_ending"], y=g["yoy_4wk"], name=group, line=dict(color=color, width=2),
                            hovertemplate="%{y:+.1f}%")
        else:
            fig.add_scatter(x=g["week_ending"], y=g["carloads"], name=group, line=dict(color=color, width=2),
                            hovertemplate="%{y:,.0f}")
    if metric == "YoY %":
        zero_line(fig)
    return styled(fig, height, "YoY %, 4-Week Total" if metric == "YoY %" else "Carloads / Week")


def drivers(df: pd.DataFrame, network_yoy: float, height: int) -> go.Figure:
    """Waterfall: each driver's points of YoY change, stepping from 0 to the network's YoY %."""
    df = df.sort_values("Contribution (pp)", ascending=False)
    labels = [*df.index, "Network"]
    values = [*df["Contribution (pp)"], network_yoy]
    changes = [*df["Change vs LY"], None]
    fig = go.Figure(go.Waterfall(
        x=labels, y=values, measure=["relative"] * len(df) + ["total"],
        text=[f"{v:+.1f}" for v in values], textposition="outside", textfont=dict(size=11, color=P.ink_2),
        increasing=dict(marker=dict(color=P.better)), decreasing=dict(marker=dict(color=P.worse)),
        totals=dict(marker=dict(color=P.muted)), connector=dict(line=dict(color=P.baseline, width=1)),
        customdata=changes,
        hovertemplate="<b>%{x}</b><br>%{y:+.2f} pts of network YoY<br>%{customdata:+,.0f} carloads<extra></extra>"))
    fig = styled(fig, height, "YoY Change (Percentage Points)", hover="closest")
    fig.update_xaxes(tickfont=dict(size=11))
    fig.update_yaxes(ticksuffix="", zeroline=True, zerolinecolor=P.baseline)
    return fig


def share(df: pd.DataFrame, y_title: str, height: int, reference: float | None = None) -> go.Figure:
    """One line per railroad: its share of the group's originated carloads."""
    fig = go.Figure()
    for railroad in [r for r in RAILROADS if r in df]:
        fig.add_scatter(x=df["week_ending"], y=df[railroad], name=railroad,
                        line=dict(color=color_for(railroad), width=2), hovertemplate="%{y:.1f}%")
    if reference:
        fig.add_hline(y=reference, line_width=1, line_color=P.baseline)
    return styled(fig, height, y_title)


# Service --------------------------------------------------------------------------------

def service_yoy(df: pd.DataFrame, label: str, higher_is_better: bool, height: int) -> go.Figure:
    fig = go.Figure()
    for railroad, g in df.groupby("railroad"):
        fig.add_scatter(x=g["week_ending"], y=g["yoy_4wk"], name=railroad,
                        line=dict(color=color_for(railroad), width=2), hovertemplate="%{y:+.1f}%")
    zero_line(fig)
    direction = "Up Is Better" if higher_is_better else "Down Is Better"
    return styled(fig, height, f"{label} YoY % ({direction})")


def service_history(df: pd.DataFrame, unit: str, height: int) -> go.Figure:
    """This year vs last year by week of year, over the range of all earlier years."""
    fig = go.Figure()
    fig.add_scatter(x=df["week"], y=df["range_high"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=df["week"], y=df["range_low"], name="Range of Earlier Years", fill="tonexty",
                    fillcolor=P.band, line=dict(width=0), hoverinfo="skip")
    if "Last year" in df:
        fig.add_scatter(x=df["week"], y=df["Last year"], name="Last Year", line=dict(color=P.muted, width=2),
                        hovertemplate="%{y:,.1f}")
    if "This year" in df:
        fig.add_scatter(x=df["week"], y=df["This year"], name="This Year", line=dict(color=P.better, width=2),
                        hovertemplate="%{y:,.1f}")
    fig = styled(fig, height, unit)
    fig.update_xaxes(title="Week of Year", title_font_size=11)
    return fig


# Map ------------------------------------------------------------------------------------

def _usa(fig: go.Figure, height: int) -> go.Figure:
    fig.update_geos(scope="usa", projection_type="albers usa", showland=True, landcolor=P.surface,
                    showlakes=False, subunitcolor=P.baseline, countrycolor=P.baseline, bgcolor=P.surface)
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor=P.surface,
                      font=dict(family=FONT, size=12, color=P.ink_2), hoverlabel=dict(font=dict(family=FONT)))
    return fig


def _colorbar(variable: str) -> dict:
    return dict(title=dict(text=f"{variable} YoY from Last Year", side="right", font=dict(size=11)),
                thickness=10, len=0.75, ticksuffix="%")


def terminal_map(df: pd.DataFrame, variable: str, height: int) -> go.Figure:
    """One point per terminal, colored by dwell vs the same weeks last year (red = slower)."""
    no_history = df[df["yoy"].isna()]
    df = df[df["yoy"].notna()]
    fig = go.Figure(go.Scattergeo(
        lat=df["lat"], lon=df["lon"], mode="markers", showlegend=False,
        marker=dict(size=11, color=df["yoy"].clip(-30, 30), colorscale=diverging(False), cmin=-30, cmax=30,
                    line=dict(width=1, color=P.ink_2), colorbar=_colorbar(variable)),
        customdata=df[["railroad", "terminal", "dwell_hours", "dwell_hours_ly", "yoy"]],
        hovertemplate="<b>%{customdata[1]}</b> (%{customdata[0]})<br>Dwell %{customdata[2]:.1f} h"
                      "<br>Last year %{customdata[3]:.1f} h (%{customdata[4]:+.1f}%)<extra></extra>"))
    fig.add_scattergeo(  # hollow: no same-weeks-last-year value to compare against
        lat=no_history["lat"], lon=no_history["lon"], mode="markers", showlegend=False,
        marker=dict(size=11, color="rgba(0,0,0,0)", line=dict(width=1.5, color=P.muted)),
        customdata=no_history[["railroad", "terminal", "dwell_hours"]],
        hovertemplate="<b>%{customdata[1]}</b> (%{customdata[0]})<br>Dwell %{customdata[2]:.1f} h"
                      "<br>No value for the same weeks last year<extra></extra>")
    return _usa(fig, height)


def state_map(df: pd.DataFrame, value: str, variable: str, unit: str, height: int) -> go.Figure:
    """States shaded by change vs the same weeks last year (blue = up)."""
    fig = go.Figure(go.Choropleth(
        locations=df["state"], locationmode="USA-states", z=df["yoy"].clip(-50, 50),
        colorscale=diverging(True), zmin=-50, zmax=50, marker_line_color=P.surface, marker_line_width=1,
        colorbar=_colorbar(variable), customdata=df[["state", value, f"{value}_ly", "yoy"]],
        hovertemplate=f"<b>%{{customdata[0]}}</b><br>%{{customdata[1]:,.0f}} {unit}"
                      "<br>Last year %{customdata[2]:,.0f} (%{customdata[3]:+.1f}%)<extra></extra>"))
    return _usa(fig, height)


COAL_BASINS = {  # approximate centre of each coal production region
    "Powder River Basin": (44.0, -105.6), "Uinta Basin": (39.6, -110.8), "Illinois Basin": (38.3, -88.0),
    "Northern Appalachia": (39.8, -80.2), "Central Appalachia": (37.5, -82.0), "Southern Appalachia": (33.6, -87.2)}
SHUTTLE_REGIONS = {  # approximate destination of grain shuttle trains; Mexico drawn at the border
    "PNW": (46.2, -122.9), "CA": (36.8, -119.8), "CA/AZ": (33.4, -114.6), "West TX": (31.8, -102.4),
    "AR/TX": (33.4, -94.0), "Gulf": (29.7, -94.9), "River": (38.6, -90.2), "Mexico": (27.6, -99.5)}


def railroad_markers(df: pd.DataFrame, place: str, centers: dict, value: str, variable: str,
                     unit_for, height: int) -> go.Figure:
    """One marker per railroad and place, offset so they don't overlap. Never summed across railroads."""
    df = df[df[place].isin(centers) & (df[f"{value}_ly"] > 0)].copy()
    offsets = {r: i for i, r in enumerate(RAILROADS)}
    df["lat"] = df[place].map(lambda c: centers[c][0])
    df["lon"] = df[place].map(lambda c: centers[c][1]) + (df["railroad"].map(offsets).fillna(0) - 2.5) * 2.2
    df["unit"] = df["railroad"].map(unit_for)
    fig = go.Figure(go.Scattergeo(
        lat=df["lat"], lon=df["lon"], mode="markers+text", text=df["railroad"], textposition="top center",
        textfont=dict(size=10, color=P.ink_2), showlegend=False,
        marker=dict(size=13, color=df["yoy"].clip(-50, 50), colorscale=diverging(True), cmin=-50, cmax=50,
                    line=dict(width=1, color=P.ink_2), colorbar=_colorbar(variable)),
        customdata=df[[place, "railroad", value, f"{value}_ly", "yoy", "unit"]],
        hovertemplate="<b>%{customdata[0]}</b>, %{customdata[1]}<br>%{customdata[2]:,.1f} %{customdata[5]}"
                      "<br>Last year %{customdata[3]:,.1f} (%{customdata[4]:+.1f}%)<extra></extra>"))
    return _usa(fig, height)
