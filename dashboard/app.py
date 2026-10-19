"""Rail Freight Monitor: what's moving, what's driving it, and how service is trending, on one screen.

Run: streamlit run dashboard/app.py   (with the repo root on PYTHONPATH)
"""
import io
import re

import pandas as pd
import streamlit as st

import charts
import data

st.set_page_config(page_title="Rail Freight Monitor", page_icon="🚂", layout="wide")
st.markdown("""<style>
  .block-container {padding: 3rem 1.5rem 0.5rem; max-width: 100%;}
  div[data-testid="stVerticalBlock"] {gap: 0.35rem;}
  h3 {padding: 0 !important;}
</style>""", unsafe_allow_html=True)

MAP_H, CHART_H, TABLE_H = 500, 215, 290
charts.set_theme(st.context.theme.type == "dark")


def panel_header(title: str, *control_widths: float, title_width: float = 2.2):
    """A bold panel title with room for inline toggles to its right."""
    cols = st.columns([title_width, *control_widths], vertical_alignment="center")
    cols[0].markdown(f"**{title}**")
    return cols[1:]


def toggle(container, options: list[str], key: str, default: str | None = None) -> str:
    return container.segmented_control(key, options, default=default or options[0], required=True,
                                       key=key, label_visibility="collapsed")


# Data and top bar -------------------------------------------------------------------------

if data.data_version() is None or (orig_all := data.originated()).empty:
    st.info("Waiting for the first data load (about 5 minutes after `docker compose up`). Refresh shortly.")
    st.stop()

status = data.status()
week = status["carloads_week"]

title, rr_col, q_col, export_col, status_col = st.columns([1.6, 3.2, 1.1, 1.2, 2.6], vertical_alignment="center")
title.markdown("### Rail Freight Monitor")
all_railroads = data.active_railroads()
railroads = rr_col.multiselect("Railroads", all_railroads, default=all_railroads,
                               help="CPKC includes CP + KCS before the May 2025 merger (pro forma).")
quarter = q_col.selectbox("Quarter", data.quarters(orig_all), format_func=str)
export_slot = export_col.empty()
ok = status["last_status"] == "succeeded" and not status["open_issues"]
status_col.markdown(
    f"{'✅' if ok else '⚠️'} Data Through **{week}** · Loaded {pd.Timestamp(status['loaded_at']):%b %d %H:%M} UTC"
    + ("" if ok else f" · **{status['open_issues']} Open Issue(s)** in `ops.issue`"))

if not railroads:
    st.warning("Pick at least one railroad.")
    st.stop()
orig = orig_all[orig_all["railroad"].isin(railroads)]


def recent(df: pd.DataFrame, keys: list[str], value: str, how: str) -> pd.DataFrame:
    """Latest 4 weeks vs the same weeks last year, for the selected railroads."""
    return data.recent_vs_last_year(df[df["railroad"].isin(railroads)], keys, value, how)


export = {}  # sheet name -> DataFrame, for the Excel download


# Row 1: map | volume + drivers ------------------------------------------------------------

map_col, right_col = st.columns([6.5, 5.5])

with map_col, st.container(border=True):
    (layer_col,) = panel_header("Where: Latest 4 Weeks vs. Last Year", 6.0)
    layer = toggle(layer_col, ["Terminal Dwell", "Grain Cars Loaded", "Grain Car Orders",
                               "Grain Shuttle Turns", "Coal Loadings"], "map_layer")

    if layer == "Terminal Dwell":
        geo = recent(data.terminal_dwell(), ["railroad", "terminal", "lat", "lon"], "dwell_hours", "mean")
        fig = charts.terminal_map(geo, layer, MAP_H)
        note = "Red = slower than last year. Click a terminal to chart its dwell in the Service panel; double-click the map to clear."
    elif layer == "Grain Cars Loaded":
        geo = recent(data.grain_by_state(), ["state"], "cars", "sum")
        fig = charts.state_map(geo, "cars", layer, "cars loaded", MAP_H)
        note = "Grain cars loaded and billed by origin state, selected railroads combined. Blue = more than last year."
    elif layer == "Grain Car Orders":
        geo = recent(data.grain_orders_by_state(), ["state"], "orders", "sum")
        fig = charts.state_map(geo, "orders", layer, "car orders placed", MAP_H)
        note = "Grain car orders placed by state (shipper demand for cars), selected railroads combined. Blue = more than last year."
    elif layer == "Grain Shuttle Turns":
        geo = recent(data.shuttle_turns_by_region(), ["railroad", "region"], "turns", "mean")
        fig = charts.railroad_markers(geo, "region", charts.SHUTTLE_REGIONS, "turns", layer,
                                      lambda r: "trips / month", MAP_H)
        note = "Average shuttle trips per month by destination, one marker per railroad (never summed). Blue = faster turns."
    else:
        geo = recent(data.coal_by_basin(), ["railroad", "basin"], "loadings", "sum")
        fig = charts.railroad_markers(geo, "basin", charts.COAL_BASINS, "loadings", layer,
                                      lambda r: "carloads" if r == "CSX" else "unit trains", MAP_H)
        note = "One marker per railroad: CSX reports carloads, the others unit trains, so they are never summed."
    export[f"Map - {layer}"] = geo
    event = st.plotly_chart(fig, config=charts.export_config(f"rail_map_{layer}_{week}"),
                            on_select="rerun", selection_mode="points", key=f"map_{layer}")
    st.caption(f"Through week ending {geo.attrs['through']}. {note}")
    points = event.selection.points if layer == "Terminal Dwell" and event else []
    selected_terminal = (points[0]["customdata"][0], points[0]["customdata"][1]) if points else None

with right_col:
    with st.container(border=True):
        metric_col, by_col, span_col = panel_header("What's Moving: Originated Carloads", 1.6, 2.6, 1.5)
        metric = toggle(metric_col, ["Carloads", "YoY %"], "volume_metric")
        by = toggle(by_col, ["Network", "Segment", "Railroad"], "volume_by")
        span = toggle(span_col, ["1Y", "2Y", "5Y"], "volume_span", default="2Y")
        weekly = data.weekly_volume(orig, {"Network": None, "Segment": "segment", "Railroad": "railroad"}[by])
        since = weekly["week_ending"].max() - pd.DateOffset(years=int(span[0]))
        st.plotly_chart(charts.volume(weekly, metric, since, CHART_H),
                        config=charts.export_config(f"rail_volume_{by}_{week}"))
        export[f"Volume by {by}"] = weekly

    with st.container(border=True):
        (drivers_by_col,) = panel_header("What's Driving It: Change vs. Last Year", 2.6)
        drivers_by = toggle(drivers_by_col, ["Commodity", "Railroad", "Segment"], "drivers_by")
        contrib = data.drivers(orig, quarter, drivers_by.lower())
        top = contrib.reindex(contrib["Contribution (pp)"].abs().nlargest(10).index).sort_values("Contribution (pp)")
        st.plotly_chart(charts.drivers(top, CHART_H), config=charts.export_config(f"rail_drivers_{quarter}_{week}"))
        network = data.quarter_to_date(orig, quarter, [])
        q, total = network.attrs, network.iloc[0]
        st.caption(
            f"Originated carloads, **{quarter} to date** ({q['weeks']} weeks ending {q['first']} to {q['through']}) "
            f"vs. **the same {q['weeks']} weeks a year earlier** ({q['first_ly']} to {q['through_ly']}). "
            f"The network changed {total['Change vs LY']:+,.0f} carloads ({total['YoY %']:+.1f}%). Each bar is one "
            f"{drivers_by.lower()}'s change divided by last year's network total, so all bars add up to "
            f"{total['YoY %']:+.1f}%. Largest 10 shown.")
        export[f"Drivers by {drivers_by}"] = contrib.reset_index()


# Row 2: service | market share ----------------------------------------------------------

service_col, share_col = st.columns([6, 6])

with service_col, st.container(border=True):
    svc_view_col, svc_metric_col, svc_rr_col = panel_header("Service vs. Own History", 2.3, 3.5, 1.2, title_width=2.0)
    view = toggle(svc_view_col, ["Vs. History", "YoY % (All)"], "service_view")
    label_to_measure = {v[0]: k for k, v in data.SERVICE_METRICS.items()}
    measure = label_to_measure[toggle(svc_metric_col, list(label_to_measure), "service_metric")]
    label, unit, higher_is_better = data.SERVICE_METRICS[measure]
    railroad = svc_rr_col.selectbox("Railroad", railroads, key="service_railroad", label_visibility="collapsed",
                                    disabled=view != "Vs. History" or selected_terminal is not None)
    svc = data.service().query("railroad in @railroads")

    if selected_terminal:
        rr, terminal = selected_terminal
        series = data.terminal_dwell().query("railroad == @rr and terminal == @terminal")
        hist = data.by_week_of_year(series, "dwell_hours")
        st.plotly_chart(charts.service_history(hist, "Hours", CHART_H),
                        config=charts.export_config(f"rail_dwell_{rr}_{terminal}_{week}"))
        st.caption(f"Terminal dwell at **{terminal}** ({rr}) by week of year. Double-click the map to clear.")
        export[f"Dwell {rr} {terminal}"[:31]] = hist
    elif view == "Vs. History":
        series = svc.query("railroad == @railroad and measure == @measure")
        hist = data.by_week_of_year(series, "value")
        st.plotly_chart(charts.service_history(hist, unit, CHART_H),
                        config=charts.export_config(f"rail_{measure}_{railroad}_{week}"))
        st.caption(f"{label} for **{railroad}** by week of year, against the range of earlier years.")
        export[f"{label} {railroad}"] = hist
    else:
        yoy = data.service_yoy(svc, measure)
        yoy = yoy[yoy["week_ending"] >= yoy["week_ending"].max() - pd.DateOffset(years=2)]
        st.plotly_chart(charts.service_yoy(yoy, label, higher_is_better, CHART_H),
                        config=charts.export_config(f"rail_{measure}_yoy_{week}"))
        st.caption("4-week average vs. the same weeks last year. Levels aren't comparable across railroads; "
                   "changes are.")
        export[f"{label} YoY"] = yoy

with share_col, st.container(border=True):
    group_col, seg_col, com_col = panel_header("Market Share", 4.6, 1.5, 1.8, title_width=1.3)
    group_name = toggle(group_col, list(data.SHARE_GROUPS), "share_group")
    segment = seg_col.selectbox("Segment", ["All Segments", *data.SEGMENTS], key="share_segment",
                                label_visibility="collapsed")
    segment = None if segment == "All Segments" else segment
    all_commodities = data.commodities()
    options = all_commodities[all_commodities["segment"] == segment] if segment else all_commodities
    commodity = com_col.selectbox("Commodity", ["All Commodities", *sorted(options["commodity"])],
                                  key="share_commodity", label_visibility="collapsed")
    commodity = None if commodity == "All Commodities" else commodity
    group = data.SHARE_GROUPS[group_name]
    share = data.market_share(orig_all, group, segment, commodity)
    what = commodity or segment or "all commodities"
    if group:
        y_title, reference = "Share of Pair, % (13-Week)", 50
        note = (f"{group[0]} and {group[1]} compete for the same customers; each line is its share of their "
                f"combined originated carloads ({what}).")
    else:
        y_title, reference = "Share of Network, % (13-Week)", None
        note = (f"Each railroad's share of all originated carloads ({what}). Reflects network size as much as "
                "competition: railroads only win share from those serving the same region.")
    st.plotly_chart(charts.share(share, y_title, CHART_H, reference),
                    config=charts.export_config(f"rail_share_{group_name}_{week}"))
    st.caption(f"{note} 13-week rolling. Not affected by the railroad filter.")
    export[f"Share - {group_name}"[:31]] = share


# Row 3: tables --------------------------------------------------------------------------

COUNT = st.column_config.NumberColumn(format="localized")
PCT = st.column_config.NumberColumn(format="%+.1f%%")
DISPLAY = {"railroad": "Railroad", "segment": "Segment", "commodity": "Commodity", "QTD carloads": "QTD Carloads",
           "QTD last year": "QTD Last Year", "Change vs LY": "Change vs. Last Year",
           "Projected quarter": "Projected Quarter", "Last year's quarter": "Last Year's Quarter",
           "Contribution (pp)": "Contribution (Pct. Pts.)"}

qtd_parts = [network.reset_index(names="railroad").assign(segment="All"),
             data.quarter_to_date(orig, quarter, ["railroad"]).reset_index().assign(segment="All"),
             data.quarter_to_date(orig, quarter, ["railroad", "segment"]).reset_index()]
tracker = (pd.concat(qtd_parts, ignore_index=True).rename(columns=DISPLAY)
           [["Railroad", "Segment", "QTD Carloads", "QTD Last Year", "YoY %", "Change vs. Last Year",
             "Projected Quarter", "Last Year's Quarter"]].round({"Projected Quarter": 0}))

commodity_table = (data.drivers(orig, quarter, "commodity").reset_index()
                   .merge(data.commodities(), on="commodity").rename(columns=DISPLAY)
                   [["Commodity", "Segment", "QTD Carloads", "QTD Last Year", "YoY %", "Change vs. Last Year",
                     "Contribution (Pct. Pts.)"]]
                   .sort_values("Contribution (Pct. Pts.)", ascending=False))

terminals = (recent(data.terminal_dwell(), ["railroad", "terminal"], "dwell_hours", "mean")
             .rename(columns={"railroad": "Railroad", "terminal": "Terminal", "dwell_hours": "Dwell (Hours, 4-Week Avg)",
                              "dwell_hours_ly": "Last Year (Hours)", "yoy": "Change %"})
             .sort_values("Change %", ascending=False))

remaining_ly = total["Last year's quarter"] - total["QTD last year"]
projection_help = (
    f"Carloads so far this quarter, plus last year's carloads for the {13 - q['weeks']} weeks still to come, "
    f"grown at this quarter's to-date YoY rate. Projected = QTD Carloads + Last Year's Remaining Weeks × "
    f"(1 + YoY %). Network: {total['QTD carloads']:,.0f} + {remaining_ly:,.0f} × (1 {total['YoY %']:+.1f}%) "
    f"= {total['Projected quarter']:,.0f}.")
counts = {c: COUNT for c in ["QTD Carloads", "Change vs. Last Year", "Last Year's Quarter"]}
counts["QTD Last Year"] = st.column_config.NumberColumn(
    format="localized", help=f"The same weeks one year earlier: {q['first_ly']} to {q['through_ly']}.")

tabs = st.container(border=True).tabs(["Quarter-to-Date Tracker", "Commodities", "Terminals"])
with tabs[0]:
    st.dataframe(tracker, height=TABLE_H, hide_index=True, column_config={
        **counts, "YoY %": PCT,
        "Projected Quarter": st.column_config.NumberColumn(format="localized", help=projection_help)})
with tabs[1]:
    st.dataframe(commodity_table, height=TABLE_H, hide_index=True, column_config={
        **counts, "YoY %": PCT, "Contribution (Pct. Pts.)": st.column_config.NumberColumn(
            format="%+.2f", help="This commodity's change divided by last year's network total. Adds up to the network YoY %.")})
with tabs[2]:
    st.dataframe(terminals, height=TABLE_H, hide_index=True, column_config={
        "Change %": PCT, "Dwell (Hours, 4-Week Avg)": st.column_config.NumberColumn(format="%.1f"),
        "Last Year (Hours)": st.column_config.NumberColumn(format="%.1f")})

export |= {"QTD Tracker": tracker, "Commodities": commodity_table, "Terminals": terminals}


# Excel export: every table plus the data behind each chart, stamped with what it shows -------

def workbook(sheets: dict[str, pd.DataFrame]) -> bytes:
    about = pd.DataFrame({"": ["Data through week ending", "Loaded at (UTC)", "Railroads", "Quarter", "Source"],
                          "Value": [str(week), str(status["loaded_at"]), ", ".join(railroads), str(quarter),
                                    "USDA AgTransport (STB EP 724 filings): tb7q-kn5i, axkm-yjzy"]})
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        about.to_excel(writer, sheet_name="About", index=False)
        for name, df in sheets.items():
            df = df.copy()
            for col in df.select_dtypes("datetimetz").columns:
                df[col] = df[col].dt.tz_localize(None)
            df.to_excel(writer, sheet_name=re.sub(r"[\[\]:*?/\\]", "", name)[:31], index=False)  # Excel's rules
    return buffer.getvalue()


export_slot.download_button("⬇ Excel", workbook(export), file_name=f"rail_monitor_{week}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            help="Every table and the data behind each chart, as shown. "
                                 "Charts: use the camera icon on each chart for a PNG.")
