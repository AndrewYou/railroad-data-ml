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
            if rows["group"].nunique() == 1:  # one series: show last year behind it
                fig.add_scatter(x=g["week_ending"], y=g["carloads_ly"], name="Same week last year",
                                line=dict(color=P.baseline, width=2), hovertemplate="%{y:,.0f}")
    if metric == "YoY %":
        zero_line(fig)
    return styled(fig, height, "% vs last year (4-wk)" if metric == "YoY %" else "carloads / week")


def drivers(df: pd.DataFrame, by: str, height: int) -> go.Figure:
    colors = [P.better if v >= 0 else P.worse for v in df["Contribution (pp)"]]
    fig = go.Figure(go.Bar(
        x=df["Contribution (pp)"], y=df.index, orientation="h", marker=dict(color=colors, cornerradius=4),
        customdata=df[["Change vs LY", "YoY %"]],
        hovertemplate="%{y}<br>%{x:+.2f} pp of network change<br>%{customdata[0]:+,.0f} carloads (%{customdata[1]:+.1f}%)<extra></extra>"))
    fig.add_vline(x=0, line_width=1, line_color=P.baseline)
    fig = styled(fig, height, hover="closest")
    fig.update_xaxes(title="percentage points of network YoY change", title_font_size=11, showgrid=True, gridcolor=P.grid)
    fig.update_yaxes(gridcolor=P.surface, tickfont=dict(size=11), tickmode="array", tickvals=list(df.index))
    return fig


def share(df: pd.DataFrame, column: str, height: int) -> go.Figure:
    railroad = column.split()[0]
    fig = go.Figure(go.Scatter(x=df["week_ending"], y=df[column], name=column,
                               line=dict(color=color_for(railroad), width=2), hovertemplate="%{y:.1f}%"))
    fig.add_hline(y=50, line_width=1, line_color=P.baseline)
    return styled(fig, height, f"{railroad} share of pair, % (13-wk)")


# Service --------------------------------------------------------------------------------

def service_yoy(df: pd.DataFrame, label: str, higher_is_better: bool, height: int) -> go.Figure:
    fig = go.Figure()
    for railroad, g in df.groupby("railroad"):
        fig.add_scatter(x=g["week_ending"], y=g["yoy_4wk"], name=railroad,
                        line=dict(color=color_for(railroad), width=2), hovertemplate="%{y:+.1f}%")
    zero_line(fig)
    direction = "up is better" if higher_is_better else "down is better"
    return styled(fig, height, f"{label}, % vs own last year ({direction})")


def service_history(df: pd.DataFrame, unit: str, height: int) -> go.Figure:
    """This year vs last year by week of year, over the range of all earlier years."""
    fig = go.Figure()
    fig.add_scatter(x=df["week"], y=df["range_high"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=df["week"], y=df["range_low"], name="Range, earlier years", fill="tonexty",
                    fillcolor=P.band, line=dict(width=0), hoverinfo="skip")
    if "Last year" in df:
        fig.add_scatter(x=df["week"], y=df["Last year"], name="Last year", line=dict(color=P.muted, width=2),
                        hovertemplate="%{y:,.1f}")
    if "This year" in df:
        fig.add_scatter(x=df["week"], y=df["This year"], name="This year", line=dict(color=P.better, width=2),
                        hovertemplate="%{y:,.1f}")
    fig = styled(fig, height, unit)
    fig.update_xaxes(title="week of year", title_font_size=11)
    return fig


# Map ------------------------------------------------------------------------------------

def _usa(fig: go.Figure, height: int) -> go.Figure:
    fig.update_geos(scope="usa", projection_type="albers usa", showland=True, landcolor=P.surface,
                    showlakes=False, subunitcolor=P.baseline, countrycolor=P.baseline, bgcolor=P.surface)
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor=P.surface,
                      font=dict(family=FONT, size=12, color=P.ink_2), hoverlabel=dict(font=dict(family=FONT)))
    return fig


def _colorbar(title: str) -> dict:
    return dict(title=dict(text=title, side="right", font=dict(size=11)), thickness=10, len=0.6, ticksuffix="%")


def terminal_map(df: pd.DataFrame, height: int) -> go.Figure:
    no_history = df[df["yoy"].isna()]
    df = df[df["yoy"].notna()]
    fig = go.Figure(go.Scattergeo(
        lat=df["lat"], lon=df["lon"], mode="markers", showlegend=False,
        marker=dict(size=11, color=df["yoy"].clip(-30, 30), colorscale=diverging(False), cmin=-30, cmax=30,
                    line=dict(width=1, color=P.ink_2), colorbar=_colorbar("dwell vs LY")),
        customdata=df[["railroad", "terminal", "dwell_hours", "dwell_hours_ly", "yoy"]],
        hovertemplate="<b>%{customdata[1]}</b> (%{customdata[0]})<br>dwell %{customdata[2]:.1f} h"
                      "<br>last year %{customdata[3]:.1f} h (%{customdata[4]:+.1f}%)<extra></extra>"))
    fig.add_scattergeo(  # hollow: no same-weeks-last-year value to compare against
        lat=no_history["lat"], lon=no_history["lon"], mode="markers", showlegend=False,
        marker=dict(size=11, color="rgba(0,0,0,0)", line=dict(width=1.5, color=P.muted)),
        customdata=no_history[["railroad", "terminal", "dwell_hours"]],
        hovertemplate="<b>%{customdata[1]}</b> (%{customdata[0]})<br>dwell %{customdata[2]:.1f} h"
                      "<br>no value for the same weeks last year<extra></extra>")
    return _usa(fig, height)


def grain_map(df: pd.DataFrame, height: int) -> go.Figure:
    fig = go.Figure(go.Choropleth(
        locations=df["state"], locationmode="USA-states", z=df["yoy"].clip(-50, 50),
        colorscale=diverging(True), zmin=-50, zmax=50, marker_line_color=P.surface, marker_line_width=1,
        colorbar=_colorbar("grain cars vs LY"), customdata=df[["state", "cars", "cars_ly", "yoy"]],
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]:,.0f} cars loaded"
                      "<br>last year %{customdata[2]:,.0f} (%{customdata[3]:+.1f}%)<extra></extra>"))
    return _usa(fig, height)


BASINS = {  # approximate centre of each coal production region
    "Powder River Basin": (44.0, -105.6), "Uinta Basin": (39.6, -110.8), "Illinois Basin": (38.3, -88.0),
    "Northern Appalachia": (39.8, -80.2), "Central Appalachia": (37.5, -82.0), "Southern Appalachia": (33.6, -87.2)}


def coal_map(df: pd.DataFrame, height: int) -> go.Figure:
    """One marker per railroad and basin, offset so they don't overlap. Units differ by railroad."""
    df = df[df["basin"].isin(BASINS) & (df["loadings_ly"] > 0)].copy()
    offsets = {r: i for i, r in enumerate(RAILROADS)}
    df["lat"] = df["basin"].map(lambda b: BASINS[b][0])
    df["lon"] = df["basin"].map(lambda b: BASINS[b][1]) + df["railroad"].map(offsets).fillna(0) * 1.2 - 3
    df["unit"] = df["railroad"].map(lambda r: "carloads" if r == "CSX" else "unit trains")
    fig = go.Figure(go.Scattergeo(
        lat=df["lat"], lon=df["lon"], mode="markers+text", text=df["railroad"], textposition="top center",
        textfont=dict(size=10, color=P.ink_2),
        marker=dict(size=13, color=df["yoy"].clip(-50, 50), colorscale=diverging(True), cmin=-50, cmax=50,
                    line=dict(width=1, color=P.ink_2), colorbar=_colorbar("coal loadings vs LY")),
        customdata=df[["basin", "railroad", "loadings", "loadings_ly", "yoy", "unit"]],
        hovertemplate="<b>%{customdata[0]}</b>, %{customdata[1]}<br>%{customdata[2]:,.1f} %{customdata[5]}"
                      "<br>last year %{customdata[3]:,.1f} (%{customdata[4]:+.1f}%)<extra></extra>"))
    return _usa(fig, height)
