import logging
import os
import sys

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

API_URL = "https://economia.awesomeapi.com.br/json/daily"


# ---------------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------------
def get_engine() -> Engine:
    campos = ["DB_USER", "DB_PASSWORD", "DB_NAME", "DB_HOST", "DB_PORT"]
    faltando = [c for c in campos if not os.getenv(c)]
    if faltando:
        raise ValueError(f"Variáveis ausentes no .env: {', '.join(faltando)}")

    url = (
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    return create_engine(url)


# ---------------------------------------------------------------------------
# Modelo dimensional (dim_moeda + fato_cotacao)
# ---------------------------------------------------------------------------
def criar_tabelas(engine: Engine) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS dim_moeda (
        id_moeda SERIAL PRIMARY KEY,
        par VARCHAR(10) UNIQUE NOT NULL,
        moeda_origem VARCHAR(5) NOT NULL,
        moeda_destino VARCHAR(5) NOT NULL,
        nome VARCHAR(100)
    );

    CREATE TABLE IF NOT EXISTS fato_cotacao (
        id_moeda INTEGER NOT NULL REFERENCES dim_moeda(id_moeda),
        data DATE NOT NULL,
        compra NUMERIC(18, 6) NOT NULL,
        venda NUMERIC(18, 6) NOT NULL,
        maxima NUMERIC(18, 6),
        minima NUMERIC(18, 6),
        variacao NUMERIC(18, 6),
        PRIMARY KEY (id_moeda, data)
    );
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))
    logger.info("Tabelas verificadas/criadas.")


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------
def extrair(par: str, dias: int) -> list[dict]:
    url = f"{API_URL}/{par}/{dias}"
    logger.info("Extraindo %s (%d dias)...", par, dias)
    try:
        resposta = requests.get(url, timeout=15)
        resposta.raise_for_status()
        dados = resposta.json()
    except requests.exceptions.Timeout:
        logger.error("Timeout ao consultar %s", par)
        return []
    except requests.exceptions.HTTPError as e:
        logger.error("Erro HTTP em %s: %s", par, e)
        return []
    except requests.exceptions.RequestException as e:
        logger.error("Erro de conexão em %s: %s", par, e)
        return []
    except ValueError:
        logger.error("Resposta inválida (não é JSON) em %s", par)
        return []

    if not isinstance(dados, list):
        logger.error("Formato inesperado para %s: %s", par, dados)
        return []

    logger.info("%d registros extraídos para %s", len(dados), par)
    return dados


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------
def transformar(par: str, dados: list[dict]) -> tuple[dict, pd.DataFrame]:
    df = pd.DataFrame(dados)
    if df.empty:
        return {}, df

    df = df.rename(
        columns={
            "bid": "compra",
            "ask": "venda",
            "high": "maxima",
            "low": "minima",
            "pctChange": "variacao",
        }
    )

    # Tipos
    df["data"] = pd.to_datetime(df["timestamp"].astype(int), unit="s").dt.date
    for col in ["compra", "venda", "maxima", "minima", "variacao"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Qualidade: remove nulos nas colunas obrigatórias e valores inválidos
    antes = len(df)
    df = df.dropna(subset=["data", "compra", "venda"])
    df = df[(df["compra"] > 0) & (df["venda"] > 0)]
    # Mantém um registro por dia
    df = df.drop_duplicates(subset=["data"], keep="first")
    descartados = antes - len(df)
    if descartados:
        logger.warning("%s: %d registros descartados na validação", par, descartados)

    origem, destino = par.split("-")
    nome = dados[0].get("name", par)
    dim = {
        "par": par,
        "moeda_origem": origem,
        "moeda_destino": destino,
        "nome": nome,
    }

    df = df[["data", "compra", "venda", "maxima", "minima", "variacao"]]
    return dim, df


# ---------------------------------------------------------------------------
# Load (idempotente: pode rodar várias vezes sem duplicar)
# ---------------------------------------------------------------------------
def carregar(engine: Engine, dim: dict, df: pd.DataFrame) -> int:
    upsert_dim = text(
        """
        INSERT INTO dim_moeda (par, moeda_origem, moeda_destino, nome)
        VALUES (:par, :moeda_origem, :moeda_destino, :nome)
        ON CONFLICT (par) DO UPDATE SET nome = EXCLUDED.nome
        RETURNING id_moeda
        """
    )
    upsert_fato = text(
        """
        INSERT INTO fato_cotacao
            (id_moeda, data, compra, venda, maxima, minima, variacao)
        VALUES
            (:id_moeda, :data, :compra, :venda, :maxima, :minima, :variacao)
        ON CONFLICT (id_moeda, data) DO UPDATE SET
            compra = EXCLUDED.compra,
            venda = EXCLUDED.venda,
            maxima = EXCLUDED.maxima,
            minima = EXCLUDED.minima,
            variacao = EXCLUDED.variacao
        """
    )

    with engine.begin() as conn:
        id_moeda = conn.execute(upsert_dim, dim).scalar_one()
        registros = df.assign(id_moeda=id_moeda).to_dict(orient="records")
        # NaN -> None para o PostgreSQL aceitar como NULL
        registros = [
            {k: (None if pd.isna(v) else v) for k, v in r.items()}
            for r in registros
        ]
        conn.execute(upsert_fato, registros)

    return len(registros)


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
def main() -> None:
    logger.info("=== Início do pipeline ETL de cotações ===")

    try:
        engine = get_engine()
        criar_tabelas(engine)
    except Exception as e:
        logger.critical("Falha ao preparar o banco: %s", e)
        sys.exit(1)

    pares = [p.strip() for p in os.getenv("MOEDAS", "USD-BRL").split(",") if p.strip()]
    dias = int(os.getenv("DIAS", "30"))

    total_ok, total_falha, total_linhas = 0, 0, 0

    for par in pares:
        dados = extrair(par, dias)
        if not dados:
            total_falha += 1
            continue

        try:
            dim, df = transformar(par, dados)
            if df.empty:
                logger.warning("%s: nenhum dado válido após transformação", par)
                total_falha += 1
                continue
            linhas = carregar(engine, dim, df)
            logger.info("%s: %d linhas carregadas", par, linhas)
            total_ok += 1
            total_linhas += linhas
        except Exception as e:
            logger.error("Erro ao processar %s: %s", par, e)
            total_falha += 1

    logger.info(
        "=== Fim: %d par(es) ok, %d falha(s), %d linhas carregadas ===",
        total_ok,
        total_falha,
        total_linhas,
    )


if __name__ == "__main__":
    main()