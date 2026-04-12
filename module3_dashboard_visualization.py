from datetime import datetime

import pandas as pd
import streamlit as st

from platform_services import (
    build_heatmap_figure,
    export_history_to_csv,
    get_alert_history,
    get_count_history,
    get_latest_zone_snapshot,
    import_csv_history,
    initialize_database,
    sync_config_to_database,
)

st.set_page_config(page_title="People Counting Dashboard", layout="wide")

initialize_database()
sync_config_to_database()
import_csv_history()

st.title("Module 3: Dashboard and Visualization")
st.caption("Live occupancy analytics, heatmaps, trend charts, and exportable reports.")

with st.sidebar:
    st.header("Dashboard Controls")
    lookback_hours = st.slider("Trend window (hours)", min_value=1, max_value=72, value=24)
    if st.button("Refresh data", use_container_width=True):
        st.rerun()

snapshot_df = get_latest_zone_snapshot()
history_df = get_count_history(lookback_hours)
alerts_df = get_alert_history()

total_people = int(snapshot_df["people_count"].sum()) if not snapshot_df.empty else 0
active_alerts = int((snapshot_df["status"] == "ALERT").sum()) if not snapshot_df.empty else 0
zone_count = int(snapshot_df["zone_code"].nunique()) if not snapshot_df.empty else 0
last_seen = str(snapshot_df["captured_at"].max()) if not snapshot_df.empty else "-"

metric_columns = st.columns(4)
metric_columns[0].metric("Total People", total_people)
metric_columns[1].metric("Configured Zones", zone_count)
metric_columns[2].metric("Active Alerts", active_alerts)
metric_columns[3].metric("Last Update", last_seen)

left_column, right_column = st.columns([1.2, 1])

with left_column:
    st.subheader("Zone Occupancy")
    if snapshot_df.empty:
        st.info("No live counts yet. Start `module2_people_detection_counting.py` to feed analytics.")
    else:
        zone_chart = snapshot_df.set_index("zone_name")[["people_count", "threshold_value"]]
        st.bar_chart(zone_chart)

    st.subheader("Crowd Trend")
    if history_df.empty:
        st.info("No time-series history available yet.")
    else:
        trend_df = history_df.pivot_table(
            index="captured_at",
            columns="zone_name",
            values="people_count",
            aggfunc="mean",
        ).fillna(0)
        st.line_chart(trend_df)

with right_column:
    st.subheader("Density Heatmap")
    st.pyplot(build_heatmap_figure(snapshot_df), clear_figure=True, use_container_width=True)

    st.subheader("Current Zone Snapshot")
    if snapshot_df.empty:
        st.dataframe(pd.DataFrame(columns=["zone_name", "people_count", "threshold_value", "status"]))
    else:
        st.dataframe(
            snapshot_df[["zone_name", "people_count", "threshold_value", "status", "captured_at"]],
            use_container_width=True,
            hide_index=True,
        )

st.subheader("Alerts")
if alerts_df.empty:
    st.success("No alerts have been recorded yet.")
else:
    st.dataframe(alerts_df, use_container_width=True, hide_index=True)

st.subheader("Export Reports")
if history_df.empty:
    st.info("Export becomes available after count events are recorded.")
else:
    if st.button("Generate CSV Report", use_container_width=True):
        exported_path = export_history_to_csv(history_df, "dashboard_counts")
        st.session_state["latest_export_path"] = exported_path

    latest_export_path = st.session_state.get("latest_export_path")
    if latest_export_path:
        with open(latest_export_path, "rb") as file:
            st.download_button(
                label="Download CSV Report",
                data=file.read(),
                file_name=latest_export_path.split("\\")[-1].split("/")[-1],
                mime="text/csv",
            )
        st.caption(f"Latest export generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
