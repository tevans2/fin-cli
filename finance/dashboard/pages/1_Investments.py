from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from finance.dashboard.loader import get_usd_zar_rate, load_investments

st.set_page_config(page_title="Investments", page_icon="📈", layout="wide")

# ── load ──────────────────────────────────────────────────────────────────────

df = load_investments()

if df.empty:
    st.error("No investment data found. Check FIN_DATA_DIR.")
    st.stop()

rate, rate_updated = get_usd_zar_rate()

with st.sidebar:
    st.header("📈 Investments")
    if rate:
        st.caption(f"USD/ZAR: **{rate:.2f}**")
        if rate_updated:
            st.caption(f"Rate updated: {rate_updated[:16]}")
    else:
        st.warning("USD/ZAR rate unavailable — USD values excluded from ZAR totals")
    if st.button("↺  Refresh"):
        st.cache_data.clear()
        st.rerun()

# ── latest snapshot per investment ────────────────────────────────────────────

latest = (
    df.sort_values("date")
    .groupby("name")
    .last()
    .reset_index()
)

# all accounts unified in ZAR (USD converted if rate available)
latest_zar = latest.dropna(subset=["value_zar"])

total_zar = latest_zar["value_zar"].sum()
total_baseline_zar = latest_zar["baseline_zar"].sum()
total_gain_zar = total_zar - total_baseline_zar
total_gain_pct = (total_gain_zar / total_baseline_zar * 100) if total_baseline_zar else 0

usd_rows = latest[latest["currency"] == "USD"]

# ── summary ───────────────────────────────────────────────────────────────────

st.title("Investments")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Portfolio (ZAR)", f"R{total_zar:,.0f}")
c2.metric("Total Gain (ZAR)", f"R{total_gain_zar:+,.0f}", delta=f"{total_gain_pct:+.1f}% since baseline")
c3.metric("Accounts", str(len(latest)))

if not usd_rows.empty:
    usd_row = usd_rows.iloc[0]
    usd_label = f"${usd_row['value']:,.2f}"
    if rate:
        usd_label += f"  ≈  R{usd_row['value_zar']:,.0f}"
    c4.metric("IBKR (USD)", usd_label, delta=f"${usd_row['gain']:+,.2f} since baseline")

# ── allocation + gain/loss ────────────────────────────────────────────────────

st.divider()
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("Allocation (ZAR)")
    if not latest_zar.empty:
        fig_pie = px.pie(
            latest_zar,
            names="name",
            values="value_zar",
            hole=0.45,
            color_discrete_sequence=px.colors.sequential.Blues_r,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        fig_pie.update_layout(
            showlegend=False,
            height=360,
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig_pie, width="stretch")

with col_b:
    st.subheader("Gain since baseline (ZAR)")
    gain_df = latest_zar.copy()
    gain_df["gain_zar"] = gain_df["value_zar"] - gain_df["baseline_zar"]
    gain_df["gain_zar_pct"] = (gain_df["gain_zar"] / gain_df["baseline_zar"] * 100).round(1)
    gain_df = gain_df.sort_values("gain_zar")
    colors = ["#ef5350" if g < 0 else "#42a5f5" for g in gain_df["gain_zar"]]
    fig_gain = go.Figure(go.Bar(
        x=gain_df["gain_zar"],
        y=gain_df["name"],
        orientation="h",
        marker_color=colors,
        text=[f"R{g:+,.0f} ({p:+.1f}%)" for g, p in zip(gain_df["gain_zar"], gain_df["gain_zar_pct"])],
        textposition="outside",
    ))
    fig_gain.update_layout(
        height=360,
        margin=dict(l=0, r=80, t=10, b=0),
        xaxis_title="ZAR",
        yaxis_title="",
    )
    st.plotly_chart(fig_gain, width="stretch")

# ── value history ─────────────────────────────────────────────────────────────

st.divider()
st.subheader("Value history")

tab_zar_hist, tab_usd_hist = st.tabs(["All accounts (ZAR)", "IBKR (USD native)"])

with tab_zar_hist:
    hist = df.dropna(subset=["value_zar"]).sort_values("date").copy()
    if not hist.empty:
        fig_hist = px.line(
            hist,
            x="date", y="value_zar",
            color="name",
            markers=True,
            labels={"date": "", "value_zar": "Value (ZAR)", "name": "Account"},
        )
        fig_hist.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_hist, width="stretch")
        if rate:
            st.caption(f"USD accounts converted at R{rate:.2f}/USD")

with tab_usd_hist:
    hist_usd = df[df["currency"] == "USD"].sort_values("date")
    if not hist_usd.empty:
        fig_usd = px.line(
            hist_usd,
            x="date", y="value",
            color="name",
            markers=True,
            labels={"date": "", "value": "Value (USD)", "name": "Account"},
        )
        fig_usd.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_usd, width="stretch")
    else:
        st.info("No USD history.")

# ── per-investment detail table ───────────────────────────────────────────────

st.divider()
st.subheader("Detail")

rows = []
for _, r in latest.iterrows():
    native = f"R{r['value']:,.2f}" if r["currency"] == "ZAR" else f"${r['value']:,.2f}"
    zar_equiv = f"R{r['value_zar']:,.0f}" if r["value_zar"] is not None else "—"
    baseline_nat = f"R{r['baseline_value']:,.2f}" if r["currency"] == "ZAR" else f"${r['baseline_value']:,.2f}"
    gain_nat = f"R{r['gain']:+,.2f}" if r["currency"] == "ZAR" else f"${r['gain']:+,.2f}"
    rows.append({
        "Account": r["name"],
        "Latest (native)": native,
        "Latest (ZAR)": zar_equiv,
        "Baseline": baseline_nat,
        "Gain": gain_nat,
        "Gain %": f"{r['gain_pct']:+.1f}%",
        "Last Updated": r["date"].strftime("%Y-%m-%d"),
    })

st.dataframe(rows, width="stretch", hide_index=True)
