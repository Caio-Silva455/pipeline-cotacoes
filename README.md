# Pipeline ETL de Cotações

Pipeline de dados em Python que extrai cotações de moedas da API pública
[AwesomeAPI](https://docs.awesomeapi.com.br/api-de-moedas), transforma e valida
os dados com pandas e carrega tudo em PostgreSQL usando um **modelo dimensional**
(tabelas fato e dimensão). Um dashboard em Streamlit consome o banco e exibe
indicadores e gráficos interativos.

## Tecnologias

- **Python 3.11+**: pandas, requests, SQLAlchemy, python-dotenv
- **PostgreSQL 16** (via Docker Compose)
- **Streamlit + Plotly**: dashboard
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
| **Extract** | Consulta a API para cada par de moedas configurado, com timeout e tratamento de erros HTTP, de conexão e de JSON inválido. |
| **Transform** | Renomeia colunas, converte tipos, remove nulos, valores não positivos e duplicatas, e monta a dimensão da moeda. |
| **Load** | Grava na dimensão e na tabela fato com *upsert*, então o pipeline pode rodar várias vezes sem duplicar dados. |
| **Visualização** | Dashboard com filtros por moeda e período, indicadores e gráficos. |

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
├── docker-compose.yml   # PostgreSQL local
├── .env.example         # modelo de configuração
├── .gitignore
├── requirements.txt
├── etl.py               # pipeline (extract, transform, load)
├── dashboard.py         # dashboard Streamlit
└── README.md
```

## Como rodar

### Pré-requisitos

- Python 3.11 ou superior
- Docker e Docker Compose
- Git

### Passo a passo

```bash
# 1. Clonar o repositório
git clone https://github.com/Caio-Silva455/pipeline-cotacoes.git
cd pipeline-cotacoes

# 2. Criar o arquivo de configuração
cp .env.example .env

# 3. Subir o PostgreSQL
docker compose up -d

# 4. Criar o ambiente virtual e instalar as dependências
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 5. Executar o pipeline
python etl.py

# 6. Abrir o dashboard
streamlit run dashboard.py
```

O dashboard abre em `http://localhost:8501`.

## Configuração

Todas as opções ficam no arquivo `.env`:

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `DB_USER` | Usuário do PostgreSQL | `etl` |
| `DB_PASSWORD` | Senha do PostgreSQL | `etl123` |
| `DB_NAME` | Nome do banco | `cotacoes` |
| `DB_HOST` | Host do banco | `localhost` |
| `DB_PORT` | Porta do banco | `5432` |
| `MOEDAS` | Pares de moedas, separados por vírgula | `USD-BRL,EUR-BRL,BTC-BRL` |
| `DIAS` | Quantidade de dias de histórico | `30` |

O arquivo `.env` está no `.gitignore`. Nunca versione credenciais.

## Exemplo de saída

```
2026-10-07 10:00:01 [INFO] === Início do pipeline ETL de cotações ===
2026-10-07 10:00:01 [INFO] Tabelas verificadas/criadas.
2026-10-07 10:00:01 [INFO] Extraindo USD-BRL (30 dias)...
2026-10-07 10:00:02 [INFO] 30 registros extraídos para USD-BRL
2026-10-07 10:00:02 [INFO] USD-BRL: 30 linhas carregadas
...
2026-10-07 10:00:04 [INFO] === Fim: 3 par(es) ok, 0 falha(s), 90 linhas carregadas ===
```

> Adicione aqui um print do dashboard em funcionamento
> (`docs/dashboard.png`) e referencie com `![Dashboard](docs/dashboard.png)`.

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

Variação em relação ao dia anterior, com função de janela:

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
- **Logs por etapa:** facilitam a depuração e o acompanhamento da execução.

## Limitações conhecidas

- A API pública tem limite de requisições e não oferece garantia de
  disponibilidade (SLA).
- O pipeline roda sob demanda; não há agendamento automático.
- Ainda não há testes automatizados.

## Próximos passos

- [ ] Testes automatizados com `pytest` (funções de transformação)
- [ ] Agendamento com cron ou Apache Airflow
- [ ] Retentativas com *backoff* em falhas de rede
- [ ] Deploy do banco e do dashboard em nuvem (GCP ou AWS)
- [ ] Pipeline de CI com GitHub Actions

## Autor

**Caio Silva**
GitHub: [github.com/Caio-Silva455](https://github.com/Caio-Silva455)