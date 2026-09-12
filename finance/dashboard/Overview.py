from __future__ import annotations

import plotly.express as px
import streamlit as st

from finance.dashboard.loader import get_balances, load_transactions

st.set_page_config(page_title="Finance", page_icon="💰", layout="wide")

# ── load ──────────────────────────────────────────────────────────────────────

df = load_transactions()

if df.empty:
    st.error("No transaction data found. Is FIN_DATA_DIR set correctly?")
    st.stop()

balances_df = get_balances()

# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("💰 Finance")

    months = sorted(df["month"].unique(), reverse=True)
    selected_month = st.selectbox("Month", options=months, format_func=str)

    banks = sorted(df["bank"].unique())
    selected_banks = st.multiselect("Banks", banks, default=banks)

    st.divider()
    if st.button("↺  Refresh"):
        st.cache_data.clear()
        st.rerun()

# ── derived ───────────────────────────────────────────────────────────────────

month_df = df[
    (df["month"] == selected_month) &
    df["bank"].isin(selected_banks)
]

exp = month_df[
    month_df["category"].str.startswith("expenses:") &
    ~month_df["category"].eq("expenses:unknown")
]
inc = month_df[
    month_df["category"].str.startswith("income:") &
    ~month_df["category"].eq("income:unknown")
]

total_spend = abs(exp["amount"].sum())
total_income = inc["amount"].sum()
net = total_income - total_spend
savings_rate = (net / total_income * 100) if total_income > 0 else 0

prev_month = selected_month - 1
prev_spend = abs(
    df[
        (df["month"] == prev_month) &
        df["bank"].isin(selected_banks) &
        df["category"].str.startswith("expenses:") &
        ~df["category"].eq("expenses:unknown")
    ]["amount"].sum()
)

six_start = selected_month - 5
trend_df = df[
    (df["month"] >= six_start) &
    (df["month"] <= selected_month) &
    df["bank"].isin(selected_banks)
]

# ── summary ───────────────────────────────────────────────────────────────────

st.title(f"Finance — {selected_month}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Net Income", f"R{net:,.0f}")
c2.metric("Savings Rate", f"{savings_rate:.0f}%")
delta_spend = total_spend - prev_spend
c3.metric(
    "Total Spend", f"R{total_spend:,.0f}",
    delta=f"{delta_spend:+,.0f} vs prior",
    delta_color="inverse",
)
c4.metric("Total Income", f"R{total_income:,.0f}")

# ── net worth ─────────────────────────────────────────────────────────────────

if not balances_df.empty:
    liquid = balances_df[balances_df["group"] == "liquid"]["balance"].sum()
    investments = balances_df[balances_df["group"] == "investments"]["balance"].sum()
    liabilities = abs(balances_df[balances_df["group"] == "liabilities"]["balance"].sum())
    net_worth = liquid + investments - liabilities

    st.divider()
    st.subheader("Net Worth")
    w1, w2, w3, w4 = st.columns(4)
    w1.metric("Net Worth (ZAR)", f"R{net_worth:,.0f}")
    w2.metric("Liquid Cash", f"R{liquid:,.0f}")
    w3.metric("Investments (ZAR¹)", f"R{investments:,.0f}")
    w4.metric("Liabilities", f"R{liabilities:,.0f}" if liabilities else "—")
    st.caption("¹ Non-ZAR investment accounts (e.g. IBKR USD) excluded from totals")

# ── spending ──────────────────────────────────────────────────────────────────

st.divider()
st.subheader("Spending")

col_a, col_b = st.columns(2)

spend_by_cat = (
    exp.groupby("top_category")["amount"]
    .sum().abs()
    .reset_index()
    .rename(columns={"top_category": "Category", "amount": "ZAR"})
    .sort_values("ZAR", ascending=True)
)

with col_a:
    if not spend_by_cat.empty:
        fig = px.bar(
            spend_by_cat,
            x="ZAR", y="Category",
            orientation="h",
            title=f"This month ({selected_month})",
            color="ZAR",
            color_continuous_scale="Blues",
        )
        fig.update_layout(
            coloraxis_showscale=False, height=400,
            margin=dict(l=0, r=10, t=40, b=0),
        )
        st.plotly_chart(fig, width="stretch")

spend_trend = (
    trend_df[
        trend_df["category"].str.startswith("expenses:") &
        ~trend_df["category"].eq("expenses:unknown")
    ]
    .groupby(["month", "top_category"])["amount"]
    .sum().abs()
    .reset_index()
    .rename(columns={"top_category": "Category", "amount": "ZAR"})
)
spend_trend["month"] = spend_trend["month"].astype(str)

with col_b:
    if not spend_trend.empty:
        fig2 = px.bar(
            spend_trend,
            x="month", y="ZAR",
            color="Category",
            title="6-month trend",
            barmode="stack",
        )
        fig2.update_layout(
            height=400,
            margin=dict(l=0, r=0, t=40, b=0),
            xaxis_title="",
        )
        st.plotly_chart(fig2, width="stretch")

# ── income ────────────────────────────────────────────────────────────────────

st.divider()
st.subheader("Income")

inc_trend = (
    trend_df[
        trend_df["category"].str.startswith("income:") &
        ~trend_df["category"].eq("income:unknown")
    ]
    .groupby(["month", "category"])["amount"]
    .sum()
    .reset_index()
    .rename(columns={"category": "Source", "amount": "ZAR"})
)
inc_trend["month"] = inc_trend["month"].astype(str)

if not inc_trend.empty:
    fig3 = px.bar(
        inc_trend,
        x="month", y="ZAR",
        color="Source",
        title="Income by source (6 months)",
        barmode="stack",
    )
    fig3.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=40, b=0),
        xaxis_title="",
    )
    st.plotly_chart(fig3, width="stretch")

# ── merchants ─────────────────────────────────────────────────────────────────

st.divider()
st.subheader("Merchants this month")

if not exp.empty:
    merchants = (
        exp.groupby(["display_name", "top_category"])
        .agg(total=("amount", lambda x: round(abs(x.sum()), 2)), txns=("amount", "count"))
        .reset_index()
        .sort_values("total", ascending=False)
        .rename(columns={
            "display_name": "Merchant",
            "top_category": "Category",
            "total": "Total (R)",
            "txns": "Txns",
        })
    )
    st.dataframe(merchants, width="stretch", hide_index=True)

# ── register ──────────────────────────────────────────────────────────────────

st.divider()
st.subheader("Transactions")

f1, f2 = st.columns([2, 3])
with f1:
    all_cats = ["All"] + sorted(month_df["top_category"].dropna().unique())
    cat_filter = st.selectbox("Category", all_cats)
with f2:
    search = st.text_input("Search", placeholder="Description...")

reg = month_df.copy()
if cat_filter != "All":
    reg = reg[reg["top_category"] == cat_filter]
if search:
    reg = reg[reg["display_name"].str.contains(search, case=False, na=False)]

display = reg[["date", "display_name", "amount", "category", "bank"]].sort_values("date", ascending=False).copy()
display["date"] = display["date"].dt.strftime("%Y-%m-%d")
display.columns = ["Date", "Description", "Amount (R)", "Category", "Bank"]
st.dataframe(display, width="stretch", hide_index=True)
