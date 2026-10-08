# Pipeline ETL de Cotações

Pipeline de dados em Python que extrai cotações de moedas da API pública
[AwesomeAPI](https://docs.awesomeapi.com.br/api-de-moedas), transforma e valida
os dados com **pandas** e carrega tudo em **PostgreSQL** usando um **modelo
dimensional** (tabelas fato e dimensão). Um dashboard em **Streamlit** consome o
banco e exibe indicadores e gráficos interativos.

Todo o ambiente (banco, ETL e dashboard) sobe com **Docker Compose**, com
configuração por variáveis de ambiente.

## Demonstração

![Dashboard](docs/dashboard.png)

![Modelo de dados](docs/modelo-er.png)

## Funcionalidades

- Extração de cotações diárias de vários pares de moedas (configuráveis).
- Validação de qualidade dos dados: nulos, valores não positivos e duplicatas.
- Carga **idempotente**: o pipeline pode rodar várias vezes sem duplicar dados.
- Modelo dimensional (`dim_moeda` e `fato_cotacao`) criado automaticamente.
- Dashboard com filtro por moeda e período, indicadores, gráfico de evolução da
  cotação, gráfico de variação diária e tabela com os dados.
- Logs por etapa e resumo final de sucessos e falhas.

## Tecnologias

- **Python**: pandas, requests, SQLAlchemy, psycopg2, python-dotenv
- **PostgreSQL 16**
- **Streamlit** e **Plotly**: dashboard
- **Docker** e **Docker Compose**
- **Git/GitHub**

## Arquitetura

```
┌──────────────┐   ┌───────────┐   ┌──────────────────┐   ┌──────────────┐   ┌───────────┐
│ AwesomeAPI   │──▶│  Extract  │──▶│    Transform     │──▶│     Load     │──▶│ Streamlit │
│ (REST/JSON)  │   │ requests  │   │ pandas + checks  │   │  PostgreSQL  │   │ dashboard │
└──────────────┘   └───────────┘   └──────────────────┘   └──────────────┘   └───────────┘
```

| Etapa | O que faz |
|-------|-----------|
| **Extract** | Consulta a API para cada par de moedas, com timeout e tratamento de erros HTTP, de conexão e de JSON inválido. |
| **Transform** | Renomeia colunas, converte tipos, remove nulos, valores não positivos e duplicatas, e monta a dimensão da moeda. |
| **Load** | Grava na dimensão e na tabela fato com *upsert* (`ON CONFLICT DO UPDATE`). |
| **Visualização** | Dashboard em Streamlit lendo direto do PostgreSQL. |

## Modelo de dados

Modelo dimensional simples (estrela):

```
dim_moeda                          fato_cotacao
─────────────────                  ─────────────────────────
id_moeda (PK)  ◀───────────────── id_moeda (PK, FK)
par (UNIQUE)                       data (PK)
moeda_origem                       compra
moeda_destino                      venda
nome                               maxima
                                   minima
                                   variacao
```

- **`dim_moeda`**: um registro por par de moedas (ex.: `USD-BRL`).
- **`fato_cotacao`**: uma linha por moeda e por dia. A chave primária composta
  `(id_moeda, data)` garante a unicidade e viabiliza a carga idempotente.

## Estrutura do projeto

```
pipeline-cotacoes/
├── docs/                # prints do dashboard e do modelo de dados
├── .dockerignore
├── .env.example         # modelo de configuração
├── .gitignore
├── Dockerfile           # imagem usada pelo ETL e pelo dashboard
├── README.md
├── dashboard.py         # dashboard Streamlit
├── docker-compose.yml   # banco, ETL e dashboard
├── etl.py               # pipeline (extract, transform, load)
└── requirements.txt
```

## Como rodar

### Pré-requisitos

- Docker e Docker Compose
- Git

### Opção 1: tudo no Docker (recomendada)

```bash
# 1. Clonar o repositório
git clone https://github.com/Caio-Silva455/pipeline-cotacoes.git
cd pipeline-cotacoes

# 2. Criar o arquivo de configuração
cp .env.example .env

# 3. Subir o banco de dados
docker compose up -d

# 4. Rodar o pipeline ETL (cria as tabelas e carrega os dados)
docker compose --profile etl run --rm etl

# 5. Subir o dashboard
docker compose --profile dashboard up -d dashboard
```

Abra o dashboard em **http://localhost:8501**.

Na primeira execução o Docker baixa a imagem do PostgreSQL e constrói a imagem do
projeto, então pode levar alguns minutos.

Para parar tudo:

```bash
docker compose down        # para os containers (os dados ficam no volume)
docker compose down -v     # para os containers e apaga os dados
```

### Opção 2: Python local com o banco no Docker

Requer Python 3.11 ou superior.

```bash
cp .env.example .env
docker compose up -d

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python etl.py
python -m streamlit run dashboard.py
```

Nesse modo, `DB_HOST=localhost` e `DB_PORT=5433` (valores do `.env.example`) fazem
o Python local falar com o PostgreSQL do container.

## Configuração

Todas as opções ficam no arquivo `.env`:

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `DB_USER` | Usuário do PostgreSQL | `etl` |
| `DB_PASSWORD` | Senha do PostgreSQL | `etl123` |
| `DB_NAME` | Nome do banco | `cotacoes` |
| `DB_HOST` | Host do banco (uso local) | `localhost` |
| `DB_PORT` | Porta do banco exposta na máquina | `5433` |
| `MOEDAS` | Pares de moedas, separados por vírgula | `USD-BRL,EUR-BRL,BTC-BRL` |
| `DIAS` | Quantidade de dias de histórico | `30` |

Dentro do Docker, os containers `etl` e `dashboard` usam `DB_HOST=db` e
`DB_PORT=5432` (rede interna do Compose). Essas duas variáveis são sobrescritas no
`docker-compose.yml`, e o seu `.env` continua valendo para o Python local.

O arquivo `.env` está no `.gitignore`. Nunca versione credenciais reais.

## Acessando o banco com uma ferramenta SQL

Em DBeaver, pgAdmin ou `psql`, use:

| Campo | Valor |
|-------|-------|
| Host | `localhost` |
| Porta | `5433` |
| Banco | `cotacoes` |
| Usuário | `etl` |
| Senha | `etl123` |

Ou direto pelo container:

```bash
docker compose exec db psql -U etl -d cotacoes
```

## Exemplo de saída

```
2026-10-08 11:53:37 [INFO] === Início do pipeline ETL de cotações ===
2026-10-08 11:53:37 [INFO] Tabelas verificadas/criadas.
2026-10-08 11:53:37 [INFO] Extraindo USD-BRL (30 dias)...
2026-10-08 11:53:37 [INFO] 30 registros extraídos para USD-BRL
2026-10-08 11:53:37 [INFO] USD-BRL: 30 linhas carregadas
2026-10-08 11:53:37 [INFO] Extraindo EUR-BRL (30 dias)...
2026-10-08 11:53:38 [INFO] 30 registros extraídos para EUR-BRL
2026-10-08 11:53:38 [INFO] EUR-BRL: 30 linhas carregadas
2026-10-08 11:53:38 [INFO] Extraindo BTC-BRL (30 dias)...
2026-10-08 11:53:38 [INFO] 30 registros extraídos para BTC-BRL
2026-10-08 11:53:38 [INFO] BTC-BRL: 30 linhas carregadas
2026-10-08 11:53:38 [INFO] === Fim: 3 par(es) ok, 0 falha(s), 90 linhas carregadas ===
```

## Validação dos dados

Duas verificações feitas durante o desenvolvimento:

**1. Idempotência.** Após a primeira carga, `SELECT COUNT(*) FROM fato_cotacao`
retorna **90** (3 pares x 30 dias). Executar o ETL novamente mantém o resultado em
90, sem duplicar linhas.

**2. Consistência da variação.** A coluna `variacao`, que vem pronta da API, foi
comparada com a variação calculada em relação ao dia anterior:

```sql
SELECT f.data,
       f.compra,
       f.variacao AS variacao_api,
       ROUND((f.compra / LAG(f.compra) OVER (ORDER BY f.data) - 1) * 100, 2) AS variacao_vs_dia_anterior
FROM fato_cotacao f
JOIN dim_moeda d ON d.id_moeda = f.id_moeda
WHERE d.par = 'EUR-BRL'
ORDER BY f.data DESC
LIMIT 10;
```

Nos 10 registros mais recentes de EUR-BRL, os dois valores coincidem (diferenças
apenas de arredondamento), então o gráfico de variação diária do dashboard reflete
a variação real entre dias consecutivos.

## Consultas úteis

Média da cotação de compra por moeda nos últimos 30 dias:

```sql
SELECT d.par, ROUND(AVG(f.compra), 4) AS media_compra
FROM fato_cotacao f
JOIN dim_moeda d ON d.id_moeda = f.id_moeda
WHERE f.data >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY d.par
ORDER BY d.par;
```

Diferença em relação ao dia anterior, com função de janela:

```sql
SELECT d.par,
       f.data,
       f.compra,
       f.compra - LAG(f.compra) OVER (PARTITION BY f.id_moeda ORDER BY f.data) AS dif_dia_anterior
FROM fato_cotacao f
JOIN dim_moeda d ON d.id_moeda = f.id_moeda
ORDER BY d.par, f.data;
```

## Decisões técnicas

- **Carga idempotente:** `INSERT ... ON CONFLICT DO UPDATE` evita duplicação ao
  reexecutar o pipeline e permite corrigir dados já carregados.
- **Modelo dimensional:** separa o cadastro das moedas (dimensão) das medidas
  diárias (fato), facilitando consultas analíticas e a inclusão de novas moedas.
- **Tratamento de erros por etapa:** a falha em um par de moedas não derruba o
  pipeline inteiro. O resumo final mostra quantos pares tiveram sucesso e falha.
- **Validação de qualidade:** registros com nulos, valores não positivos ou
  duplicados são descartados e registrados em log.
- **Configuração por variáveis de ambiente:** sem credenciais no código.
- **Docker Compose com perfis:** o banco sobe sozinho; ETL e dashboard são
  executados sob demanda (`--profile etl` e `--profile dashboard`).
- **Healthcheck no banco:** ETL e dashboard só iniciam depois que o PostgreSQL
  está pronto para aceitar conexões.
- **Porta 5433 no host:** evita conflito com um PostgreSQL local na porta 5432.

## Limitações conhecidas

- A API pública tem limite de requisições e não oferece garantia de
  disponibilidade (SLA).
- O pipeline roda sob demanda; não há agendamento automático.
- Não há testes automatizados.
- As dependências do `requirements.txt` não têm versão fixada.
- A senha de exemplo (`etl123`) serve apenas para uso local.

## Próximos passos

- [ ] Testes automatizados com `pytest` (funções de transformação)
- [ ] Fixar as versões das dependências
- [ ] Agendamento com cron ou Apache Airflow
- [ ] Retentativas com *backoff* em falhas de rede
- [ ] Pipeline de CI com GitHub Actions
- [ ] Deploy do banco e do dashboard em nuvem (GCP ou AWS)

## Autor

**Caio Silva**
GitHub: [github.com/Caio-Silva455](https://github.com/Caio-Silva455)