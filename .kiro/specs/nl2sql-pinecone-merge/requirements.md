# Requirements Document

## Introduction

Merge the standalone NL2SQL FastAPI application (currently at `ma-oracle-nl2sql/`) into the main M&A Oracle repository. The merged application must use the ingestion pipeline's `output/xbrl/financials.db` as its single source of truth for financial data, replace ChromaDB-based agent memory with Pinecone (`ma-oracle-cap` index) for few-shot SQL example storage and retrieval, unify configuration and dependencies across both codebases, and preserve the existing NL2SQL FastAPI service and glassmorphism web UI.

## Glossary

- **NL2SQL_Service**: The FastAPI application that converts natural language questions into SQL queries, executes them against the financial database, and returns structured results.
- **Ingestion_Pipeline**: The existing data pipeline (`run_ingestion.py`) that fetches XBRL, EDGAR, transcript, patent, and proxy data, stores structured financials in SQLite, and indexes text chunks into Pinecone.
- **Financials_DB**: The SQLite database at `output/xbrl/financials.db` containing `companies` and `financial_facts` tables, produced by the Ingestion_Pipeline's XBRL source.
- **Pinecone_Index**: The Pinecone vector index named `ma-oracle-cap` used by the main repository for document retrieval and, after this merge, for NL2SQL few-shot memory storage.
- **Agent_Memory**: The component that stores and retrieves few-shot SQL question/query examples to improve LLM-generated SQL quality. Currently backed by ChromaDB or an in-memory demo store.
- **Config_System**: The unified configuration layer combining `config.yaml` (static settings) and `.env` (secrets and environment-specific overrides).
- **Web_UI**: The glassmorphism-styled static frontend (`index.html`, `script.js`, `style.css`) served by the NL2SQL_Service.
- **SQL_Validator**: The component that sanitizes, validates, and checks generated SQL against the database schema before execution.
- **Pinecone_Memory_Namespace**: A dedicated namespace within the Pinecone_Index used exclusively for NL2SQL few-shot SQL examples, kept separate from document chunks.

## Requirements

### Requirement 1: Relocate NL2SQL Application into Main Repository

**User Story:** As a developer, I want the NL2SQL application modules to live inside the main repository structure, so that I can maintain a single codebase with shared configuration and dependencies.

#### Acceptance Criteria

1. WHEN the NL2SQL_Service is relocated, THE NL2SQL_Service SHALL reside under a `nl2sql/` directory at the repository root, containing all application modules (`api.py`, `config.py`, `database.py`, `llm.py`, `memory.py`, `models.py`, `pipeline.py`, `schema.py`, `security.py`, `seed_memory.py`).
2. WHEN the NL2SQL_Service is relocated, THE NL2SQL_Service SHALL serve the Web_UI static files from `nl2sql/static/` containing `index.html`, `script.js`, and `style.css`.
3. WHEN the NL2SQL_Service is relocated, THE NL2SQL_Service SHALL provide a `nl2sql/main.py` entry point that starts the FastAPI server using Uvicorn.
4. WHEN the NL2SQL_Service is relocated, THE NL2SQL_Service SHALL retain all existing internal module imports updated to reflect the new `nl2sql.app` package path.

### Requirement 2: Use Ingestion Pipeline's Financial Database

**User Story:** As a developer, I want the NL2SQL service to query the same `financials.db` produced by the ingestion pipeline, so that financial data is consistent and not duplicated.

#### Acceptance Criteria

1. THE Config_System SHALL default the NL2SQL database path to `output/xbrl/financials.db` relative to the repository root.
2. WHEN the `DB_PATH` environment variable is set, THE Config_System SHALL use the value of `DB_PATH` as the NL2SQL database path.
3. THE NL2SQL_Service SHALL remove the standalone `financials.db` copy previously bundled in `ma-oracle-nl2sql/`.
4. IF the Financials_DB file does not exist at the configured path, THEN THE NL2SQL_Service SHALL return a health status of `disconnected` for the database field and return an error message for chat queries.

### Requirement 3: Replace ChromaDB Memory with Pinecone

**User Story:** As a developer, I want the NL2SQL agent memory to use the existing Pinecone index instead of ChromaDB, so that the system uses a single vector store and ChromaDB can be removed as a dependency.

#### Acceptance Criteria

1. THE Agent_Memory SHALL store and retrieve few-shot SQL examples using the Pinecone_Index (`ma-oracle-cap`).
2. THE Agent_Memory SHALL use a dedicated Pinecone_Memory_Namespace (e.g., `nl2sql-memory`) to isolate few-shot SQL examples from document chunks stored in other namespaces.
3. WHEN a new successful SQL query is executed, THE Agent_Memory SHALL upsert the question-SQL pair into the Pinecone_Memory_Namespace with an embedding of the question text.
4. WHEN the NL2SQL_Service searches for similar prior examples, THE Agent_Memory SHALL query the Pinecone_Memory_Namespace using semantic similarity and return up to the configured `memory_search_limit` results.
5. THE Agent_Memory SHALL embed question text using the same embedding model configured in `config.yaml` under `embedding.pinecone.model_name`.
6. WHEN the NL2SQL_Service starts, THE Agent_Memory SHALL seed the Pinecone_Memory_Namespace with the predefined training examples from `seed_memory.py` if those examples are not already present.
7. THE NL2SQL_Service SHALL remove all ChromaDB imports and usage from the codebase.

### Requirement 4: Unify Configuration

**User Story:** As a developer, I want a single configuration system for both the ingestion pipeline and the NL2SQL service, so that I do not need to maintain separate `.env` files and config classes.

#### Acceptance Criteria

1. THE Config_System SHALL read NL2SQL settings from the main repository's `config.yaml` under a new `nl2sql` section (containing `host`, `port`, `max_rows`, `memory_search_limit`, `memory_namespace`).
2. THE Config_System SHALL read API keys (`PINECONE_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`) from the main repository's `.env` file.
3. THE Config_System SHALL read the Pinecone index name from `config.yaml` at `vector_store.pinecone.index_name`.
4. THE Config_System SHALL read the LLM model and base URL from `config.yaml` at `llm` section, with environment variable overrides (`LLM_MODEL`, `LLM_BASE_URL`) taking precedence.
5. THE Config_System SHALL remove the separate `ma-oracle-nl2sql/.env.example` file after merging its required variables into the main `.env.example`.

### Requirement 5: Unify Dependencies

**User Story:** As a developer, I want a single `requirements.txt` for the entire repository, so that I can install all dependencies in one step.

#### Acceptance Criteria

1. THE main `requirements.txt` SHALL include `fastapi`, `uvicorn`, and `vanna[openai]` as additional dependencies required by the NL2SQL_Service.
2. THE main `requirements.txt` SHALL remove `chromadb` since the NL2SQL_Service no longer uses ChromaDB.
3. WHEN a developer runs `pip install -r requirements.txt`, THE dependency set SHALL be sufficient to run both the Ingestion_Pipeline and the NL2SQL_Service.
4. THE NL2SQL_Service SHALL remove the separate `ma-oracle-nl2sql/requirements.txt` file after merging.

### Requirement 6: Preserve NL2SQL API and Web UI Functionality

**User Story:** As a user, I want the NL2SQL chat interface and API to continue working after the merge, so that I can still ask natural language questions about financial data.

#### Acceptance Criteria

1. THE NL2SQL_Service SHALL expose a `GET /health` endpoint returning database connection status and agent memory item count.
2. THE NL2SQL_Service SHALL expose a `POST /chat` endpoint accepting a JSON body with a `question` field and returning `message`, `sql_query`, `columns`, `rows`, and `row_count`.
3. THE NL2SQL_Service SHALL expose a `GET /` endpoint serving the glassmorphism Web_UI.
4. THE NL2SQL_Service SHALL mount static assets at `/static` for CSS and JavaScript files.
5. THE SQL_Validator SHALL reject queries containing write operations (INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, REPLACE, TRUNCATE, ATTACH, DETACH, PRAGMA, VACUUM, REINDEX, ANALYZE).
6. THE SQL_Validator SHALL verify that all referenced tables and qualified column references exist in the Financials_DB schema.
7. WHEN the NL2SQL_Service generates a SQL query that returns results, THE NL2SQL_Service SHALL save the question-SQL pair to Agent_Memory for future few-shot retrieval.

### Requirement 7: Update Ingestion Pipeline Awareness

**User Story:** As a developer, I want the ingestion pipeline to remain unmodified in its core behavior, so that the merge does not break existing data ingestion or Pinecone indexing.

#### Acceptance Criteria

1. THE Ingestion_Pipeline SHALL continue to produce the Financials_DB at `output/xbrl/financials.db` with the same `companies` and `financial_facts` schema.
2. THE Ingestion_Pipeline SHALL continue to index document chunks into the Pinecone_Index under the existing namespace without interference from the NL2SQL_Service's memory namespace.
3. THE `config.yaml` SHALL add an `nl2sql` section without modifying existing sections used by the Ingestion_Pipeline.
