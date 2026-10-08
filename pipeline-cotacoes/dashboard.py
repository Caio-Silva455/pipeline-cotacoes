import os

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

st.set_page_config(page_title="Cotações", layout="wide")
st.title("Dashboard de Cotações")


@st.cache_resource
def get_engine():
    url = (
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    return create_engine(url)


@st.cache_data(ttl=300)
def carregar_dados() -> pd.DataFrame:
    query = """
        SELECT d.par, d.nome, f.data, f.compra, f.venda,
               f.maxima, f.minima, f.variacao
        FROM fato_cotacao f
        JOIN dim_moeda d ON d.id_moeda = f.id_moeda
        ORDER BY f.data
    """
    return pd.read_sql(query, get_engine())


df = carregar_dados()

if df.empty:
    st.warning("Sem dados. Rode primeiro: python etl.py")
    st.stop()

df["data"] = pd.to_datetime(df["data"])

# Filtros
st.sidebar.header("Filtros")
pares = st.sidebar.multiselect(
    "Moedas", sorted(df["par"].unique()), default=sorted(df["par"].unique())[:1]
)
data_min, data_max = df["data"].min().date(), df["data"].max().date()
periodo = st.sidebar.date_input("Período", (data_min, data_max))

filtrado = df[df["par"].isin(pares)]
if len(periodo) == 2:
    filtrado = filtrado[
        (filtrado["data"].dt.date >= periodo[0])
        & (filtrado["data"].dt.date <= periodo[1])
    ]

if filtrado.empty:
    st.info("Nenhum dado para os filtros selecionados.")
    st.stop()

# Indicadores (último valor de cada par)
st.subheader("Indicadores")
ultimos = filtrado.sort_values("data").groupby("par").tail(1)
colunas = st.columns(len(ultimos))
for col, (_, linha) in zip(colunas, ultimos.iterrows()):
    col.metric(
        label=linha["par"],
        value=f"{linha['compra']:,.4f}",
        delta=f"{linha['variacao']:.2f}%",
    )

# Gráficos
st.subheader("Evolução da cotação de compra")
st.plotly_chart(
    px.line(filtrado, x="data", y="compra", color="par", markers=True),
    width="stretch",
)

st.subheader("Variação diária (%)")
st.plotly_chart(
    px.bar(filtrado, x="data", y="variacao", color="par", barmode="group"),
    width="stretch",
)

with st.expander("Ver dados"):
    st.dataframe(filtrado, width="stretch")