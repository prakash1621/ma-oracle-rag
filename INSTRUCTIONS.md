# M&A Oracle — Data Pipeline Setup Instructions

## What This Is

This is the data ingestion pipeline for the M&A Oracle project. It downloads, parses, and indexes financial data from 7 sources for 12 major tech companies. Your teammates can run this independently without the full project.

## Prerequisites

- Python 3.9 or higher
- pip (Python package manager)
- Internet connection (to download SEC filings)
- AWS account with Bedrock access (for embeddings) OR use free local embeddings

## Step-by-Step Setup

### Step 1: Copy the shared/ folder

Copy the entire `shared/` folder to your machine. You can put it anywhere.

### Step 2: Open terminal and navigate to the folder

```bash
cd shared
```

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
```

This installs: requests, beautifulsoup4, pyyaml, faiss-cpu, boto3, langchain packages.
Total size: ~200MB. Takes 2-3 minutes.

### Step 4: Create your .env file

```bash
cp .env.example .env
```

Open `.env` in any text editor and set this line:

```
SEC_USER_AGENT=MAOracle yourname@gmail.com
```

Replace `yourname@gmail.com` with your actual email(give dummy email).

WHY EMAIL? SEC (the government agency that hosts financial filings) requires every API user to provide a contact email. This is NOT for login — it's just so SEC can contact you if your script causes issues. Any real email works. Without it, SEC blocks all requests.

### Step 5: Set up embeddings (choose one option)

OPTION A — AWS Bedrock (default, better quality):
Add these lines to your `.env` file:
```
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_DEFAULT_REGION=us-east-1
```
Ask your team lead for AWS credentials if you don't have them.

OPTION B — Free local embeddings (no AWS needed):
1. Install extra package:
   ```bash
   pip install sentence-transformers langchain-huggingface
   ```
   (This downloads ~500MB of ML model files)

2. Edit `config.yaml`, change this line:
   ```yaml
   embedding:
     provider: "huggingface"    # change from "bedrock" to "huggingface"
   ```

OPTION C — Skip embeddings for now:
You can run ingestion without embeddings. Just don't use the `--index` flag.
The data will be saved as JSON files you can view directly.

## Running the Pipeline

### Ingest all data (recommended first run)

```bash
python run_ingestion.py
```

This downloads data for all 12 companies from all 7 sources.
Takes about 5-10 minutes (mostly waiting for SEC rate limits).

### Ingest specific companies only

```bash
python run_ingestion.py --tickers AAPL MSFT NVDA
```

### Ingest specific sources only

```bash
python run_ingestion.py --sources edgar
python run_ingestion.py --sources xbrl
python run_ingestion.py --sources edgar xbrl transcripts
```

### Available source names

| Source Name      | What It Downloads                                    |
|-----------------|------------------------------------------------------|
| edgar           | SEC 10-K annual report filings (HTML, parsed to text)|
| xbrl            | Structured financial numbers (revenue, income, etc.) |
| transcripts     | Quarterly earnings press releases from SEC 8-K       |
| patents         | Patent titles and abstracts for each company         |
| proxy           | Board members, executive compensation (DEF 14A)      |
| company_facts   | Company metadata (SIC code, state, fiscal year)      |

### Check what data you have

```bash
python run_ingestion.py --stats
```

### Build search index (requires embeddings setup from Step 5)

```bash
python run_ingestion.py --index
```

This converts all text chunks into vectors and saves a FAISS index.
Takes 30-60 minutes with Bedrock, 10-20 minutes with local embeddings.

## Where Your Data Goes

After running, check the `output/` folder:

```
output/
├── edgar/
│   └── chunked_documents.json    ← 10-K filing text chunks (open in any editor)
├── xbrl/
│   └── financials.db             ← Financial numbers (open with DB Browser for SQLite)
├── transcripts/
│   └── chunked_documents.json    ← Earnings release text chunks
├── patents/
│   └── patents.db                ← Patent data (SQLite)
│   └── chunked_documents.json    ← Patent text chunks
├── proxy/
│   └── chunked_documents.json    ← Proxy statement text chunks
├── company_facts/
│   └── companies.json            ← Company metadata
└── vector_store/                 ← FAISS search index (created by --index)
    ├── index.faiss
    └── index.pkl
```

## Understanding the Data

### JSON chunk files (chunked_documents.json)

Each file contains an array of objects like:
```json
{
  "text": "The actual text content from the filing...",
  "metadata": {
    "company_name": "Apple Inc.",
    "filing_type": "10-K",
    "filing_date": "2024-11-01",
    "item_number": "1A",
    "item_title": "Risk Factors",
    "category": "sec_filing"
  }
}
```

### XBRL database (financials.db)

Contains structured financial data. You can query it with SQL:
```sql
SELECT entity_name, label, value, fiscal_year
FROM financial_facts
WHERE label = 'Revenue' AND is_annual = 1
ORDER BY entity_name, fiscal_year DESC
```

### Company facts (companies.json)

Contains company metadata:
```json
{
  "cik": "0000320193",
  "name": "Apple Inc.",
  "ticker": "AAPL",
  "sic": "3571",
  "state": "CA",
  "fiscal_year_end": "0928"
}
```

## The 12 Companies

| Ticker | Company              | Industry          |
|--------|---------------------|-------------------|
| AAPL   | Apple Inc.          | Consumer Tech     |
| MSFT   | Microsoft           | Enterprise Tech   |
| NVDA   | NVIDIA              | Semiconductors    |
| AMZN   | Amazon              | E-commerce/Cloud  |
| META   | Meta Platforms      | Social Media      |
| GOOGL  | Alphabet            | Search/Cloud      |
| TSLA   | Tesla               | EV/Energy         |
| CRM    | Salesforce          | Enterprise SaaS   |
| SNOW   | Snowflake           | Data Cloud        |
| CRWD   | CrowdStrike         | Cybersecurity     |
| PANW   | Palo Alto Networks  | Cybersecurity     |
| FTNT   | Fortinet            | Cybersecurity     |

## Troubleshooting

### "SEC_USER_AGENT not set"
You forgot Step 4. Create `.env` file with your email.

### "ExpiredTokenException" or AWS credential errors
Your AWS credentials expired. Get fresh ones from your AWS console or ask your team lead.

### "No module named 'langchain_huggingface'"
You chose Option B (local embeddings) but didn't install the package. Run:
```bash
pip install sentence-transformers langchain-huggingface
```

### "No module named 'langchain_aws'"
Run: `pip install langchain-aws boto3`

### Ingestion is slow
SEC has a rate limit (max 10 requests/second). The pipeline respects this automatically. Each company takes about 30-60 seconds.

### Want to add more companies?
Edit `config.yaml` and add tickers to the `companies` list. Any US public company ticker works.

 