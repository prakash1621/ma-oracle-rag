# Implementation Plan: NL2SQL Pinecone Merge

## Overview

Merge the standalone NL2SQL FastAPI application into the main repository, replacing ChromaDB with Pinecone-backed agent memory, unifying configuration and dependencies, and removing the old `ma-oracle-nl2sql/` directory. Tasks are ordered so each step builds on the previous, with no orphaned code.

## Tasks

- [x] 1. Set up project structure and copy unchanged modules
  - [x] 1.1 Create `nl2sql/` directory structure and copy unchanged files
    - Create `nl2sql/`, `nl2sql/app/`, `nl2sql/static/` directories
    - Create `nl2sql/app/__init__.py`
    - Copy unchanged modules from `ma-oracle-nl2sql/app/` to `nl2sql/app/`: `database.py`, `llm.py`, `security.py`, `schema.py`, `models.py`, `pipeline.py`
    - Copy static files from `ma-oracle-nl2sql/static/` to `nl2sql/static/`: `index.html`, `script.js`, `style.css`
    - Update all `from app.` imports in copied files to `from nl2sql.app.`
    - _Requirements: 1.1, 1.2, 1.4_

- [x] 2. Implement unified configuration
  - [x] 2.1 Rewrite `nl2sql/app/config.py` to read from `config.yaml` and `.env`
    - Load `.env` via `python-dotenv`, parse `config.yaml` with `pyyaml`
    - Populate `Settings` dataclass with fields: `db_path` (default `output/xbrl/financials.db`), `llm_base_url`, `llm_model`, `groq_api_key`, `host`, `port`, `max_rows`, `memory_search_limit`, `memory_namespace`, `pinecone_api_key`, `pinecone_index_name`, `pinecone_embed_model`
    - Environment variables (`DB_PATH`, `LLM_MODEL`, `LLM_BASE_URL`, `GROQ_API_KEY`, `PINECONE_API_KEY`) override `config.yaml` values
    - _Requirements: 2.1, 2.2, 4.1, 4.2, 4.3, 4.4_

  - [ ]* 2.2 Write property test for config environment variable override
    - **Property 1: Config environment variable override**
    - **Validates: Requirements 2.2, 4.4**

  - [x] 2.3 Add `nl2sql` section to `config.yaml`
    - Add `nl2sql:` section with `host`, `port`, `max_rows`, `memory_search_limit`, `memory_namespace`, `llm_base_url`, `llm_model` keys
    - Do not modify any existing sections
    - _Requirements: 4.1, 7.3_

  - [x] 2.4 Update `.env.example` with NL2SQL variables
    - Add `GROQ_API_KEY` and `PINECONE_API_KEY` entries to the main `.env.example`
    - _Requirements: 4.2, 4.5_

- [x] 3. Implement Pinecone-backed agent memory
  - [x] 3.1 Rewrite `nl2sql/app/memory.py` with `PineconeAgentMemory`
    - Implement `PineconeAgentMemory` class extending Vanna's `AgentMemory`
    - Use Pinecone `upsert_records` / `search_records` with integrated embedding (`chunk_text` field)
    - Use `nl2sql-memory` namespace (from settings)
    - Generate deterministic `_id` as `"nl2sql-" + sha256(question)[:16]`
    - Implement `save_tool_usage`, `search_similar_usage`, `get_recent_memories`
    - Implement `count_memories` using `describe_index_stats` filtered by namespace
    - Preserve `build_tool_context` and `create_agent_memory` factory function
    - Remove all ChromaDB and DemoAgentMemory imports
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.7_

  - [ ]* 3.2 Write property test for memory store-and-retrieve round trip
    - **Property 2: Memory store-and-retrieve round trip**
    - **Validates: Requirements 3.1, 3.3, 6.7**

  - [ ]* 3.3 Write property test for search result count respects limit
    - **Property 3: Search result count respects limit**
    - **Validates: Requirements 3.4**

- [x] 4. Update seed memory and API entry points
  - [x] 4.1 Update `nl2sql/app/seed_memory.py` with new import paths
    - Copy from `ma-oracle-nl2sql/app/seed_memory.py`
    - Update imports from `app.*` to `nl2sql.app.*`
    - Idempotency is handled by deterministic Pinecone `_id` values (upsert deduplicates)
    - _Requirements: 3.6_

  - [ ]* 4.2 Write property test for seed memory idempotency
    - **Property 4: Seed memory is idempotent**
    - **Validates: Requirements 3.6**

  - [x] 4.3 Update `nl2sql/app/api.py` with new import paths and static file paths
    - Update all imports from `app.*` to `nl2sql.app.*`
    - Update `StaticFiles(directory=...)` to `nl2sql/static`
    - Update `FileResponse(...)` to `nl2sql/static/index.html`
    - _Requirements: 1.4, 6.1, 6.2, 6.3, 6.4_

  - [x] 4.4 Create `nl2sql/main.py` entry point
    - Import `app` from `nl2sql.app.api` and `get_settings` from `nl2sql.app.config`
    - Run uvicorn with `nl2sql.main:app`
    - _Requirements: 1.3_

- [x] 5. Checkpoint - Verify core structure
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Unify dependencies and write validator tests
  - [x] 6.1 Update main `requirements.txt` with NL2SQL dependencies
    - Add `fastapi>=0.100.0`, `uvicorn>=0.23.0`, `vanna[openai]>=0.7.0`
    - Ensure `chromadb` is NOT added
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ]* 6.2 Write property test for SQL validator rejects write operations
    - **Property 5: SQL validator rejects write operations**
    - **Validates: Requirements 6.5**

  - [ ]* 6.3 Write property test for SQL validator rejects unknown schema references
    - **Property 6: SQL validator rejects unknown schema references**
    - **Validates: Requirements 6.6**

- [x] 7. Clean up old directory
  - [x] 7.1 Remove `ma-oracle-nl2sql/` directory
    - Delete the entire `ma-oracle-nl2sql/` directory and all its contents
    - _Requirements: 1.1, 2.3, 4.5, 5.4_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- The design uses Python throughout — all implementation tasks use Python
