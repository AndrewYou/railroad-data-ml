"""Daniel Plainview's Dashboard: what's moving on U.S. rail, what's driving it, and how service is trending.

A page of dashboard/main.py, which sets up the page and theme.
"""
import io
import re

import pandas as pd
import streamlit as st

import charts
import data

MAP_H, CHART_H, TABLE_H = 470, 215, 290


def panel_header(title: str, *control_widths: float, title_width: float = 2.2):
    """A bold panel title with room for inline toggles to its right."""
    cols = st.columns([title_width, *control_widths], vertical_alignment="center")
    cols[0].markdown(f"**{title}**", unsafe_allow_html=True)
    return cols[1:]


def underline(text: str) -> str:
    """Marks text that follows the Trailing Window, so a reader sees what the button changed."""
    return f"<u>{text}</u>"


def toggle(container, options: list[str], key: str, default: str | None = None) -> str:
    return container.segmented_control(key, options, default=default or options[0], required=True,
                                       key=key, label_visibility="collapsed")


def eastern(ts) -> str:
    """e.g. 'Mon Oct 19, 2026 11:57 AM ET' (ET = EDT or EST, whichever applies that day)."""
    t = pd.Timestamp(ts).tz_convert("America/New_York")
    return f"{t:%a %b} {t.day}, {t.year} {t:%-I:%M %p} ET"


# Data and top bar -------------------------------------------------------------------------

if data.data_version() is None or (orig_all := data.originated()).empty:
    st.info("Waiting for the first data load (about 5 minutes after `docker compose up`). Refresh shortly.")
    st.stop()

status = data.status()
week = pd.Timestamp(status["carloads_week"])

title, rr_col, window_col, status_col, export_col = st.columns([2.3, 3.0, 2.4, 1.9, 0.6],
                                                               vertical_alignment="center")
title.markdown("<div style='font-size:1.6rem;font-weight:700;line-height:1.2;margin-bottom:1rem'>🛢️ Daniel Plainview's Dashboard</div>",
               unsafe_allow_html=True)  # plain line: a heading's extra spacing would sit lower than the controls
all_railroads = data.active_railroads()
railroads = rr_col.multiselect("Railroads", all_railroads, default=all_railroads, label_visibility="collapsed",
                               placeholder="Pick railroads")

window_label, window_buttons = window_col.columns([0.75, 2.1], vertical_alignment="center")
window_label.markdown(
    "<div style='font-size:0.85rem;margin-bottom:1rem;white-space:nowrap' title='Every year-over-year view compares the trailing "
    "1, 2 or 4 weeks with the same weeks a year earlier: the map, What&#39;s Driving It, the Terminals table, "
    "and the YoY % modes of What&#39;s Moving and Service.'>Trailing Window ⓘ</div>", unsafe_allow_html=True)
window = toggle(window_buttons, list(data.WINDOWS), "window", default="4 Weeks")  # every YoY view uses it
weeks = data.WINDOWS[window]
latest = f"trailing {underline(f'{weeks} weeks')}"
per_point = underline("that week") if weeks == 1 else f"the {underline(f'{weeks} weeks')} ending that week"

ok = status["last_status"] == "succeeded" and not status["open_issues"]
issues = "" if ok else f"<br><b>{status['open_issues']} open issue(s)</b> in ops.issue"
status_col.markdown(
    f"<div style='font-size:0.78rem;line-height:1.35;margin-bottom:1rem'>{'✅' if ok else '⚠️'} Data Through "
    f"Week Ending <b>{week:%a %b} {week.day}, {week.year}</b><br>Loaded {eastern(status['loaded_at'])}{issues}</div>",
    unsafe_allow_html=True)
export_slot = export_col.empty()

if not railroads:
    st.warning("Pick at least one railroad.")
    st.stop()
orig = orig_all[orig_all["railroad"].isin(railroads)]
export = {}  # sheet name -> DataFrame, for the Excel download


def recent(df: pd.DataFrame, keys: list[str], value: str, how: str, weeks: int) -> pd.DataFrame:
    """Latest `weeks` vs the same weeks last year, for the selected railroads."""
    return data.recent_vs_last_year(df[df["railroad"].isin(railroads)], keys, value, how, weeks)


# Row 1: map | volume + drivers ------------------------------------------------------------

map_col, right_col = st.columns([6.5, 5.5])

with map_col, st.container(border=True):
    (layer_col,) = panel_header(f"Where: Trailing {underline(window)} vs. Last Year", 6.6, title_width=3.0)
    layer = toggle(layer_col, ["Terminal Dwell", "Grain Cars Loaded", "Grain Car Orders",
                               "Grain Shuttle Turns", "Coal Loadings"], "map_layer")

    if layer == "Terminal Dwell":
        geo = recent(data.terminal_dwell(), ["railroad", "terminal", "lat", "lon"], "dwell_hours", "mean", weeks)
        fig = charts.terminal_map(geo, layer, MAP_H)
        note = "Click a terminal to render its Service vs. Own History panel below. Double-click the map to clear."
    elif layer == "Grain Cars Loaded":
        geo = recent(data.grain_by_state(), ["state"], "cars", "sum", weeks)
        fig = charts.state_map(geo, "cars", layer, "cars loaded", MAP_H)
        note = "Grain cars loaded and billed by origin state, selected railroads combined. Blue = more than last year."
    elif layer == "Grain Car Orders":
        geo = recent(data.grain_orders_by_state(), ["state"], "orders", "sum", weeks)
        fig = charts.state_map(geo, "orders", layer, "car orders placed", MAP_H)
        note = "Grain car orders placed by state (shipper demand for cars), selected railroads combined. Blue = more than last year."
    elif layer == "Grain Shuttle Turns":
        geo = recent(data.shuttle_turns_by_region(), ["railroad", "region"], "turns", "mean", weeks)
        fig = charts.railroad_markers(geo, "region", charts.SHUTTLE_REGIONS, "turns", layer,
                                      lambda r: "trips / month", MAP_H)
        note = "Average shuttle trips per month by destination, one marker per railroad (never summed). Blue = faster turns."
    else:
        geo = recent(data.coal_by_basin(), ["railroad", "basin"], "loadings", "sum", weeks)
        fig = charts.railroad_markers(geo, "basin", charts.COAL_BASINS, "loadings", layer,
                                      lambda r: "carloads" if r == "CSX" else "unit trains", MAP_H)
        note = "One marker per railroad: CSX reports carloads, the others unit trains, so they are never summed."
    export[f"Map - {layer}"] = geo
    event = st.plotly_chart(fig, config=charts.export_config(f"rail_map_{layer}_{week.date()}"),
                            on_select="rerun", selection_mode="points", key=f"map_{layer}")
    st.caption(note)
    points = event.selection.points if layer == "Terminal Dwell" and event else []
    selected_terminal = (points[0]["customdata"][0], points[0]["customdata"][1]) if points else None

with right_col:
    with st.container(border=True):
        metric_col, by_col, span_col = panel_header("What's Moving: Originated Carloads", 1.6, 2.6, 1.5)
        metric = toggle(metric_col, ["Carloads", "YoY %"], "volume_metric")
        by = toggle(by_col, ["Network", "Segment", "Railroad"], "volume_by")
        span = toggle(span_col, ["1Y", "2Y", "5Y"], "volume_span", default="2Y")
        weekly = data.weekly_volume(orig, {"Network": None, "Segment": "segment", "Railroad": "railroad"}[by], weeks)
        since = weekly["week_ending"].max() - pd.DateOffset(years=int(span[0]))
        st.plotly_chart(charts.volume(weekly, metric, since, CHART_H),
                        config=charts.export_config(f"rail_volume_{by}_{week.date()}"))
        st.caption(("Weekly originated carloads." if metric == "Carloads" else
                    f"Each point: carloads in {per_point} vs. the same weeks a year earlier.")
                   + " CPKC includes CP and KCS before the May 2025 merger.", unsafe_allow_html=True)
        export[f"Volume by {by}"] = weekly

    with st.container(border=True):
        (drivers_by_col,) = panel_header(f"What's Driving It: Trailing {underline(window)} vs. Last Year", 2.6, title_width=3.6)
        drivers_by = toggle(drivers_by_col, ["Commodity", "Railroad", "Segment"], "drivers_by")
        contrib = data.drivers(orig, weeks, drivers_by.lower())
        d = contrib.attrs
        st.plotly_chart(charts.drivers(contrib, d["network_yoy"], CHART_H),
                        config=charts.export_config(f"rail_drivers_{window}_{week.date()}"))
        st.caption(
            (f"Originated carloads, **{underline('week')} ending {d['through']}** vs. **the same week a year earlier** "
             f"({d['through_ly']})" if weeks == 1 else
             f"Originated carloads, **{latest}** (weeks ending {d['first']} to {d['through']}) "
             f"vs. **the same weeks a year earlier** ({d['first_ly']} to {d['through_ly']})")
            + f": the network changed "
            f"{d['network_change']:+,.0f} carloads ({d['network_yoy']:+.1f}%).", unsafe_allow_html=True)
        export[f"Drivers by {drivers_by}"] = contrib.reset_index(names=drivers_by)


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
                        config=charts.export_config(f"rail_dwell_{rr}_{terminal}_{week.date()}"))
        st.caption(f"Terminal dwell at **{terminal}** ({rr}) by week of year. Double-click the map to clear.")
        export[f"Dwell {rr} {terminal}"] = hist
    elif view == "Vs. History":
        series = svc.query("railroad == @railroad and measure == @measure")
        hist = data.by_week_of_year(series, "value")
        st.plotly_chart(charts.service_history(hist, unit, CHART_H),
                        config=charts.export_config(f"rail_{measure}_{railroad}_{week.date()}"))
        st.caption(f"{label} for **{railroad}** by week of year, against the range of earlier years.")
        export[f"{label} {railroad}"] = hist
    else:
        yoy = data.service_yoy(svc, measure, weeks)
        yoy = yoy[yoy["week_ending"] >= yoy["week_ending"].max() - pd.DateOffset(years=2)]
        st.plotly_chart(charts.service_yoy(yoy, label, higher_is_better, CHART_H),
                        config=charts.export_config(f"rail_{measure}_yoy_{week.date()}"))
        st.caption(f"Each point: the average over {per_point} vs. the same weeks a year earlier."
                   + " Levels aren't comparable across railroads; changes are.", unsafe_allow_html=True)
        export[f"{label} YoY"] = yoy

with share_col, st.container(border=True):
    seg_col, com_col = panel_header("Market Share (13-Week)", 1.5, 1.7, title_width=3.0)
    segment = seg_col.selectbox("Segment", ["All Segments", *data.SEGMENTS], key="share_segment",
                                label_visibility="collapsed")
    segment = None if segment == "All Segments" else segment
    all_commodities = data.commodities()
    options = all_commodities[all_commodities["segment"] == segment] if segment else all_commodities
    commodity = com_col.selectbox("Commodity", ["All Commodities", *sorted(options["commodity"])],
                                  key="share_commodity", label_visibility="collapsed")
    commodity = None if commodity == "All Commodities" else commodity
    share = data.market_share(orig, segment, commodity)  # shares of the railroads picked in the top bar
    st.plotly_chart(charts.share(share, "Share of Selected Railroads, %", CHART_H, 50 if len(railroads) == 2 else None),
                    config=charts.export_config(f"rail_share_{week.date()}"))
    what = commodity or segment or "all commodities"
    st.caption(f"Each railroad's share of the selected railroads' originated carloads ({what}). "
               "Pick two railroads in the top bar to compare them head to head.")
    export["Market Share"] = share


# Row 3: tables (scoped by quarter) ----------------------------------------------------------

COUNT = st.column_config.NumberColumn(format="localized")
PCT = st.column_config.NumberColumn(format="%+.1f%%")
DISPLAY = {"railroad": "Railroad", "segment": "Segment", "commodity": "Commodity", "QTD carloads": "QTD Carloads",
           "QTD last year": "QTD Last Year", "Change vs LY": "Change vs. Last Year",
           "Projected quarter": "Projected Quarter", "Last year's quarter": "Last Year's Quarter"}

with st.container(border=True):
    quarter_col, _ = panel_header("Quarter to Date", 1.4, 8.0, title_width=1.2)
    quarter = quarter_col.selectbox("Quarter", data.quarters(orig_all), label_visibility="collapsed",
                                    format_func=lambda p: f"Q{p.quarter} {p.year}")
    network = data.quarter_to_date(orig, quarter, [])
    q, total = network.attrs, network.iloc[0]

    tracker = (pd.concat([network.reset_index(names="railroad").assign(segment="All"),
                          data.quarter_to_date(orig, quarter, ["railroad"]).reset_index().assign(segment="All"),
                          data.quarter_to_date(orig, quarter, ["railroad", "segment"]).reset_index()],
                         ignore_index=True).rename(columns=DISPLAY)
               [["Railroad", "Segment", "QTD Carloads", "QTD Last Year", "YoY %", "Change vs. Last Year",
                 "Projected Quarter", "Last Year's Quarter"]].round({"Projected Quarter": 0}))

    commodity_table = (data.quarter_to_date(orig, quarter, ["commodity"]).reset_index()
                       .merge(data.commodities(), on="commodity").rename(columns=DISPLAY))
    commodity_table["Contribution (Pct. Pts.)"] = (commodity_table["Change vs. Last Year"]
                                                   / commodity_table["QTD Last Year"].sum() * 100)
    commodity_table = commodity_table[["Commodity", "Segment", "QTD Carloads", "QTD Last Year", "YoY %",
                                       "Change vs. Last Year", "Contribution (Pct. Pts.)"]].sort_values(
        "Contribution (Pct. Pts.)", ascending=False)

    dwell_col = f"Dwell (Hours, {weeks}-Week Avg)"
    terminals = (recent(data.terminal_dwell(), ["railroad", "terminal"], "dwell_hours", "mean", weeks)
                 .rename(columns={"railroad": "Railroad", "terminal": "Terminal", "dwell_hours": dwell_col,
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

    tabs = st.tabs(["Quarter-to-Date Tracker", "Commodities", "Terminals"])
    with tabs[0]:
        st.dataframe(tracker, height=TABLE_H, hide_index=True, column_config={
            **counts, "YoY %": PCT,
            "Projected Quarter": st.column_config.NumberColumn(format="localized", help=projection_help)})
    with tabs[1]:
        st.dataframe(commodity_table, height=TABLE_H, hide_index=True, column_config={
            **counts, "YoY %": PCT, "Contribution (Pct. Pts.)": st.column_config.NumberColumn(
                format="%+.2f", help="This commodity's change divided by last year's network total. "
                                     "Adds up to the network YoY %.")})
    with tabs[2]:
        st.dataframe(terminals, height=TABLE_H, hide_index=True, column_config={
            "Change %": PCT, dwell_col: st.column_config.NumberColumn(format="%.1f"),
            "Last Year (Hours)": st.column_config.NumberColumn(format="%.1f")})

export |= {"QTD Tracker": tracker, "Commodities": commodity_table, "Terminals": terminals}


# Excel export: every table plus the data behind each chart, stamped with what it shows -------

def workbook(sheets: dict[str, pd.DataFrame]) -> bytes:
    about = pd.DataFrame({"": ["Data through week ending", "Loaded at", "Railroads", "Quarter (tables)",
                               "Comparison window", "Source"],
                          "Value": [str(week.date()), eastern(status["loaded_at"]), ", ".join(railroads),
                                    f"Q{quarter.quarter} {quarter.year}", f"Trailing {window} vs. same weeks last year",
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


export_slot.download_button("⬇ Excel", workbook(export), file_name=f"plainview_rail_{week.date()}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            help="Every table and the data behind each chart, as shown. "
                                 "Charts: use the camera icon on each chart for a PNG.")
