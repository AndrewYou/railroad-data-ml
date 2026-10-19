"""Rail Freight Monitor: what's moving, what's driving it, and how service is trending, on one screen.

Run: streamlit run dashboard/app.py   (with the repo root on PYTHONPATH)
"""
import io

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

MAP_H, CHART_H, TABLE_H = 470, 215, 290
charts.set_theme(st.context.theme.type == "dark")


def panel_header(title: str, *control_widths: float):
    """A bold panel title with room for inline toggles to its right."""
    cols = st.columns([2.2, *control_widths], vertical_alignment="center")
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

title, rr_col, q_col, export_col, status_col = st.columns([1.6, 3.2, 1.1, 1.2, 2.6], vertical_alignment="bottom")
title.markdown("### Rail Freight Monitor")
all_railroads = data.active_railroads()
railroads = rr_col.multiselect("Railroads", all_railroads, default=all_railroads,
                               help="CPKC includes CP + KCS before the May 2025 merger (pro forma).")
quarter = q_col.selectbox("Quarter", data.quarters(orig_all), format_func=str)
export_slot = export_col.empty()
ok = status["last_status"] == "succeeded" and not status["open_issues"]
status_col.markdown(
    f"{'✅' if ok else '⚠️'} Data through **{week}** · loaded {pd.Timestamp(status['loaded_at']):%b %d %H:%M} UTC"
    + ("" if ok else f" · **{status['open_issues']} open issue(s)** in `ops.issue`"))

if not railroads:
    st.warning("Pick at least one railroad.")
    st.stop()
orig = orig_all[orig_all["railroad"].isin(railroads)]
export = {}  # sheet name -> DataFrame, for the Excel download


# Row 1: map | volume + drivers ------------------------------------------------------------

map_col, right_col = st.columns([5, 7])

with map_col:
    (layer_col,) = panel_header("Where: latest 4 weeks vs last year", 4.2)
    layer = toggle(layer_col, ["Terminal dwell", "Grain by state", "Coal by basin"], "map_layer")
    if layer == "Terminal dwell":
        geo = data.recent_vs_last_year(data.terminal_dwell().query("railroad in @railroads"),
                                       ["railroad", "terminal", "lat", "lon"], "dwell_hours", "mean")
        fig = charts.terminal_map(geo, MAP_H)
    elif layer == "Grain by state":
        geo = data.recent_vs_last_year(data.grain_by_state().query("railroad in @railroads"), ["state"], "cars", "sum")
        fig = charts.grain_map(geo, MAP_H)
    else:
        geo = data.recent_vs_last_year(data.coal_by_basin().query("railroad in @railroads"),
                                       ["railroad", "basin"], "loadings", "sum")
        fig = charts.coal_map(geo, MAP_H)
    export[f"Map - {layer}"] = geo
    event = st.plotly_chart(fig, config=charts.export_config(f"rail_map_{layer}_{week}"),
                            on_select="rerun", selection_mode="points", key=f"map_{layer}")
    st.caption(f"Through week ending {geo.attrs['through']}. "
               + ("Click a terminal to chart its dwell below; double-click the map to clear."
                  if layer == "Terminal dwell" else
                  "Coal units differ: CSX reports carloads, others unit trains." if layer == "Coal by basin" else
                  "All selected railroads combined."))
    points = event.selection.points if layer == "Terminal dwell" and event else []
    selected_terminal = (points[0]["customdata"][0], points[0]["customdata"][1]) if points else None

with right_col:
    metric_col, by_col, span_col = panel_header("What's moving: originated carloads", 1.6, 2.6, 1.5)
    metric = toggle(metric_col, ["Carloads", "YoY %"], "volume_metric")
    by = toggle(by_col, ["Network", "Segment", "Railroad"], "volume_by")
    span = toggle(span_col, ["1Y", "2Y", "5Y"], "volume_span", default="2Y")
    weekly = data.weekly_volume(orig, {"Network": None, "Segment": "segment", "Railroad": "railroad"}[by])
    since = weekly["week_ending"].max() - pd.DateOffset(years=int(span[0]))
    st.plotly_chart(charts.volume(weekly, metric, since, CHART_H),
                    config=charts.export_config(f"rail_volume_{by}_{week}"))
    export[f"Volume by {by}"] = weekly

    (drivers_by_col,) = panel_header(f"What's driving it: {quarter} to date vs last year", 3.2)
    drivers_by = toggle(drivers_by_col, ["Commodity", "Railroad", "Segment"], "drivers_by")
    contrib = data.drivers(orig, quarter, drivers_by.lower())
    top = contrib.reindex(contrib["Contribution (pp)"].abs().nlargest(10).index).sort_values("Contribution (pp)")
    st.plotly_chart(charts.drivers(top, drivers_by, CHART_H), config=charts.export_config(f"rail_drivers_{quarter}_{week}"))
    export[f"Drivers by {drivers_by}"] = contrib.reset_index()


# Row 2: service | market share ----------------------------------------------------------

service_col, share_col = st.columns([6, 6])

with service_col:
    svc_metric_col, svc_view_col, svc_rr_col = panel_header("Service vs own history", 3.4, 2.2, 1.4)
    label_to_measure = {v[0]: k for k, v in data.SERVICE_METRICS.items()}
    measure = label_to_measure[toggle(svc_metric_col, list(label_to_measure), "service_metric")]
    label, unit, higher_is_better = data.SERVICE_METRICS[measure]
    view = toggle(svc_view_col, ["vs history", "YoY % all"], "service_view")
    railroad = svc_rr_col.selectbox("Railroad", railroads, key="service_railroad", label_visibility="collapsed")
    svc = data.service().query("railroad in @railroads")

    if selected_terminal:
        rr, terminal = selected_terminal
        series = data.terminal_dwell().query("railroad == @rr and terminal == @terminal")
        hist = data.by_week_of_year(series, "dwell_hours")
        st.plotly_chart(charts.service_history(hist, "hours", CHART_H),
                        config=charts.export_config(f"rail_dwell_{rr}_{terminal}_{week}"))
        st.caption(f"Terminal dwell at **{terminal}** ({rr}), by week of year. Double-click the map to clear.")
        export[f"Dwell {rr} {terminal}"[:31]] = hist
    elif view == "vs history":
        series = svc.query("railroad == @railroad and measure == @measure")
        hist = data.by_week_of_year(series, "value")
        st.plotly_chart(charts.service_history(hist, unit, CHART_H),
                        config=charts.export_config(f"rail_{measure}_{railroad}_{week}"))
        cpkc_note = " CPKC history starts at the May 2025 merger." if railroad == "CPKC" else ""
        st.caption(f"{label} for **{railroad}** by week of year, against the range of earlier years.{cpkc_note}")
        export[f"{label} {railroad}"] = hist
    else:
        yoy = data.service_yoy(svc, measure)
        yoy = yoy[yoy["week_ending"] >= yoy["week_ending"].max() - pd.DateOffset(years=2)]
        st.plotly_chart(charts.service_yoy(yoy, label, higher_is_better, CHART_H),
                        config=charts.export_config(f"rail_{measure}_yoy_{week}"))
        st.caption("4-week average vs the same weeks last year. Levels aren't comparable across railroads; changes are.")
        export[f"{label} YoY"] = yoy

with share_col:
    pair_col, seg_col, com_col = panel_header("Market share between direct competitors", 3.0, 1.6, 2.2)
    pair_name = toggle(pair_col, list(data.PAIRS), "share_pair")
    segment = seg_col.selectbox("Segment", ["All segments", *data.SEGMENTS], key="share_segment",
                                label_visibility="collapsed")
    segment = None if segment == "All segments" else segment
    all_commodities = data.commodities()
    options = all_commodities[all_commodities["segment"] == segment] if segment else all_commodities
    commodity = com_col.selectbox("Commodity", ["All commodities", *sorted(options["commodity"])], key="share_commodity",
                                  label_visibility="collapsed")
    commodity = None if commodity == "All commodities" else commodity
    pair = data.PAIRS[pair_name]
    share = data.market_share(orig_all, pair, segment, commodity)
    share_column = share.columns[1]
    st.plotly_chart(charts.share(share, share_column, CHART_H),
                    config=charts.export_config(f"rail_share_{pair[0]}_{pair[1]}_{week}"))
    st.caption(f"{pair[0]} share of {pair[0]} + {pair[1]} originated carloads"
               f" ({commodity or segment or 'all commodities'}), 13-week rolling. Not affected by the railroad filter.")
    export[f"Share {pair[0]} vs {pair[1]}"] = share


# Row 3: tables --------------------------------------------------------------------------

PCT = st.column_config.NumberColumn(format="%+.1f%%")
COUNT = st.column_config.NumberColumn(format="localized")

qtd_parts = [data.quarter_to_date(orig, quarter, []).reset_index(names="railroad").assign(segment="All"),
             data.quarter_to_date(orig, quarter, ["railroad"]).reset_index().assign(segment="All"),
             data.quarter_to_date(orig, quarter, ["railroad", "segment"]).reset_index()]
tracker = pd.concat(qtd_parts, ignore_index=True).rename(columns={"railroad": "Railroad", "segment": "Segment"})
tracker = tracker[["Railroad", "Segment", "QTD carloads", "QTD last year", "YoY %", "Change vs LY",
                   "Projected quarter", "Last year's quarter"]].round({"Projected quarter": 0})

commodity_table = (data.drivers(orig, quarter, "commodity").reset_index()
                   .merge(data.commodities(), on="commodity")
                   .rename(columns={"commodity": "Commodity", "segment": "Segment", "read_through": "Read-through"})
                   [["Commodity", "Segment", "Read-through", "QTD carloads", "QTD last year", "YoY %",
                     "Change vs LY", "Contribution (pp)"]]
                   .sort_values("Contribution (pp)", ascending=False))

terminals = (data.recent_vs_last_year(data.terminal_dwell().query("railroad in @railroads"),
                                      ["railroad", "terminal"], "dwell_hours", "mean")
             .rename(columns={"railroad": "Railroad", "terminal": "Terminal", "dwell_hours": "Dwell (h, 4-wk avg)",
                              "dwell_hours_ly": "Last year (h)", "yoy": "Change %"})
             .sort_values("Change %", ascending=False))

revisions = data.revisions().query("railroad in @railroads or railroad not in @all_railroads")

tabs = st.tabs(["Quarter-to-date tracker", "Commodities", "Terminals", "Revisions to history"])
with tabs[0]:
    q_info = data.quarter_to_date(orig, quarter, [])
    st.caption(f"{quarter}: {q_info.attrs['weeks']} of 13 weeks, through week ending {q_info.attrs['through']}. "
               "Projected quarter = to date + last year's remaining weeks grown at the to-date YoY rate.")
    st.dataframe(tracker, height=TABLE_H, hide_index=True, column_config={
        "YoY %": PCT, **{c: COUNT for c in tracker.columns if "carloads" in c or "quarter" in c or "LY" in c}})
with tabs[1]:
    st.dataframe(commodity_table, height=TABLE_H, hide_index=True, column_config={
        "YoY %": PCT, "Contribution (pp)": st.column_config.NumberColumn(format="%+.2f"),
        "QTD carloads": COUNT, "QTD last year": COUNT, "Change vs LY": COUNT})
with tabs[2]:
    st.dataframe(terminals, height=TABLE_H, hide_index=True, column_config={
        "Change %": PCT, "Dwell (h, 4-wk avg)": st.column_config.NumberColumn(format="%.1f"),
        "Last year (h)": st.column_config.NumberColumn(format="%.1f")})
with tabs[3]:
    if revisions.empty:
        st.caption("No published values have been restated by the source yet.")
    st.dataframe(revisions, height=TABLE_H, hide_index=True)

export |= {"QTD tracker": tracker, "Commodities": commodity_table, "Terminals": terminals, "Revisions": revisions}


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
            df.to_excel(writer, sheet_name=name[:31], index=False)
    return buffer.getvalue()


export_slot.download_button("⬇ Excel", workbook(export), file_name=f"rail_monitor_{week}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            help="Every table and the data behind each chart, as shown. "
                                 "Charts: use the camera icon on each chart for a PNG.")
