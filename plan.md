
# Plan: research_nlp restructure + dashboard foundations

Repo: C:\Users\angel.adeoye\dev\financial_research (the \\bluecrest.local copy is stale; never edit it).
Goal: reorganise the backend under a temporary namespace `research_nlp`, then add SQLAlchemy storage, claim/graph tables, a FastAPI read API and a React + TypeScript (Vite) frontend for a document explorer, claim explorer and knowledge graph.
Execute one phase at a time. Verify every fact about current files before acting; an earlier codebase summary was partly wrong.

## Conventions (apply to all new or refactored code)

- Every package has an empty `__init__.py`; no re-exports. Callers import from modules directly.
- Each package declares its enums (StrEnum) and dataclasses (frozen where possible) in `types.py`; abstract base classes go in `base.py`.
- Group behaviour in classes (encapsulation; inheritance where there is a real is-a). Avoid loose module-level functions except trivial helpers.
- Pydantic models are allowed for IO schemas (e.g. `argumentation/schema.py`, `api/schemas.py`).
- Directories are organised by function. All hard-coded config (registries, taxonomies, experiments, prompts, pipelines, theme) lives in root `config/`, never inside `src/`.
- Concise code; comments only where the code cannot speak for itself; one line each.
- Keep the existing ruff and pyright settings (Google docstrings, 120 chars).

## Target layout

```
financial_research/
├── src/research_nlp/
│   ├── core/            # Settings, ConfigLoader
│   ├── ingestion/       # email pipeline (untouched for now)
│   ├── parsing/         # untouched
│   ├── extraction/      # was src/gliner
│   ├── argumentation/   # refactored in Phase 4
│   ├── models/          # LLM backends (name temporary)
│   ├── ontology/
│   ├── ontology_new/    # kept until canonical version decided
│   ├── storage/         # existing repos + engine.py, tables/, repositories/, migrations/
│   ├── api/             # FastAPI
│   ├── training/
│   ├── classes.py       # email pipeline, untouched for now
│   ├── pipeline.py      # email pipeline, untouched for now
│   └── utils.py         # untouched for now
├── frontend/            # Vite React TS
├── tests/  (fixtures/gold/)
├── config/ (registries, taxonomies, experiments, prompts, pipelines, theme)
├── data/
├── docs/
├── notebooks/
├── pyproject.toml
└── uv.lock
```

## Phase 0-pre: remove stale tests

The email pipeline is already broken (it references removed `EmailMetadata`, `ExtractedEmail`, `EmailSegment`, a missing `ingestion/dedup.py`, the renamed `OutlookEmailParser`, a missing `schemas` package, and an undeclared `pandas`). The user will fix it later.

1. Delete these test files: test_drop_inline_images.py, test_duplicate_window.py, test_email_extraction.py, test_email_parser.py, test_email_storage.py, test_fingerprints.py, test_incremental_sync.py, test_inline_figures.py, test_pipeline.py, test_tagging.py, test_tagging_schemas.py.
2. Do NOT edit any email pipeline code: classes.py, pipeline.py, utils.py, ingestion/, parsing/, storage/emails.py, storage/migration.py, storage/__main__.py.
3. Baseline: run `uv run python -m pytest` and record the pass count (argumentation and ontology tests remain).

## Phase 0: namespace move (mechanical, no logic changes)

1. Create `src/research_nlp/__init__.py` (empty).
2. `git mv` into `src/research_nlp/`: argumentation, ingestion, ontology, ontology_new, parsing, storage, classes.py, pipeline.py, utils.py. Also `git mv src/gliner src/research_nlp/extraction`.
3. Create empty packages: core/, api/, models/, training/ (each with an empty `__init__.py`).
4. pyproject.toml:
   - add `[build-system]` with hatchling, and `[tool.hatch.build.targets.wheel] packages = ["src/research_nlp"]`
   - remove `pythonpath = ["src"]` from `[tool.pytest.ini_options]`
   - remove `extraPaths` from `[tool.pyright]`
   - add `frontend` and `**/node_modules` to the ruff `extend-exclude` and pyright `exclude`
5. Rewrite absolute imports in non-email code (argumentation, ontology, extraction), tests and notebooks: `src.<pkg>` or bare `<pkg>` becomes `research_nlp.<pkg>`. Leave relative imports alone. Leave email-pipeline files untouched even if their imports are broken.
6. Move the root gold YAMLs (`*_argument_map_gold_v04.yaml`, `*_v06.yaml`) to `tests/fixtures/gold/` and update the paths in `tests/conftest.py`.
7. Move root markdown docs (argument_hierarchy_open_questions.md, claim_classification_revision.md, CLAIM_ONTOLOGY_IMPLEMENTATION_PLAN.md) to `docs/`; keep README.md at the root. Move extraction.ipynb and inference_experiments.ipynb to `notebooks/`.
8. `.gitignore`: add `frontend/node_modules/` and `frontend/dist/`.
9. Run `uv sync`.
   Verify: `uv run pytest` (without `python -m`) matches the baseline pass count; `uv run ruff check src tests` and `uv run pyright` show no new errors outside email pipeline files; searching non-email code for `from src.` returns nothing.

## Phase 1: core settings and config loading (depends on 0)

1. Add dependency `pydantic-settings`.
2. `core/settings.py`: `Settings` (BaseSettings, env prefix `RESEARCH_NLP_`) with `root_dir` (default: repo root via `Path(__file__).resolve().parents[3]`), `config_dir`, `data_dir`, `db_url` (default `sqlite:///<data_dir>/research.sqlite3`).
3. `core/config.py`: `ConfigLoader` class, built from `Settings`, with cached methods `registry(name)`, `taxonomy(name)`, `prompt(group, name)`, `pipeline(name)`, `theme(name)`; YAML/JSON/MD by file extension.
4. Move argumentation config out of `src/`:
   - `argumentation/prompts/system_prompt.md` and `user_prompt.md` (plus any examples) go to `config/prompts/argumentation/`
   - `argumentation/prompts/taxonomy.yaml` goes to `config/taxonomies/argumentation.yaml` (check for a clash with the existing `config/taxonomies/taxonomy.yaml` first)
   - `argumentation/pipeline.yaml` goes to `config/pipelines/argumentation.yaml`
5. Replace every `PACKAGE_DIR`-based path in argumentation (taxonomy.py, pipeline.py, prompt.py, diagram.py) with `ConfigLoader` calls. `diagram.py` reads the theme from `config/theme/argument_map.json`.
   Verify: pytest is green; searching the argumentation package for `PACKAGE_DIR` returns nothing.

## Phase 2: SQLAlchemy and Alembic infrastructure (depends on 1)

1. Add dependencies `sqlalchemy>=2.0` and `alembic`.
2. `storage/engine.py`: a `Database` class wrapping engine and sessionmaker, with a `session()` context manager, built from `Settings.db_url`.
3. `storage/tables/base.py`: `Base(DeclarativeBase)`. Add `tables/emails.py` and `tables/entities.py` mirroring the EXISTING sqlite schema exactly (inspect `research.sqlite3` and `storage/emails.py` / `entities.py`; do not modify those modules).
4. `storage/migrations/`: Alembic env wired to `Base.metadata` and `Settings.db_url`, plus a baseline revision for the existing tables; stamp existing databases rather than recreating them. Keep `alembic.ini` at the repo root, or configure Alembic from pyproject.
5. `storage/repositories/base.py`: generic `Repository[T]` with session injection.
   Verify: on a COPY of `data/research.sqlite3`, `alembic stamp head` then `alembic upgrade head` is a no-op and row counts are unchanged; pytest is green.

## Phase 3: claim and graph tables (depends on 2)

1. `storage/types.py`: StrEnums `SourceType` (EMAIL, PDF, TEXT), `LinkRole` (SUPPORTING, RATIONALE, RISK, CONDITION, CATALYST, QUALIFIER), `RunStatus`.
2. `storage/tables/`:
   - `documents`: id, source_type, external_id (e.g. email fingerprint), title, author, published_at, text
   - `extraction_runs`: id, document_id, backend, model, prompt_version, schema_version, config_hash, status, created_at, extras JSON (rejected_links, exclusions, adjudication_notes)
   - `evidence`: id, run_id, local_id (E###), text
   - `statements`: id, run_id, local_id (S###), brief, statement, claim_type, modality, modality_cue
   - `statement_evidence`: association between statements and evidence
   - `arguments`: id, run_id, local_id (A###), summary, core_statement_id
   - `argument_links`: argument_id, statement_id, role
   - `entity_mentions`: entity_id, statement_id, evidence_id (nullable)
3. Write an Alembic revision for these tables.
4. `storage/repositories/argument_maps.py`: `ArgumentMapRepository` with `save(map, document, run_meta) -> run_id` and `load(run_id) -> ArgumentMap` (the Pydantic model from `argumentation/schema.py`). Also add `storage/repositories/documents.py`.
5. Add a test that loads each gold fixture, saves it, loads it back and asserts equality.
   Verify: round-trip tests pass; counts per gold file (evidence/statements/arguments) are Ocado 14/26/8, MS D1 9/14/7, ING FX 37/39/13.

## Phase 4: argumentation refactor (depends on 1; may run in parallel with 2–3)

1. `argumentation/types.py`: move in the enums (Modality, claim types, roles) and dataclasses (PipelineConfig, PipelineResult, SourceDocument, PreprocessConfig, ValidationIssue, Taxonomy). `schema.py` keeps only the Pydantic IO models.
2. Turn loose functions into classes: `DocumentLoader` (ingest.py), `PromptRenderer` (prompt.py), `TaxonomyLoader` (taxonomy.py), `ArgumentMapValidator` (validate.py), `ArgumentMapPipeline` (pipeline.py, including the repair loop), `ArgumentMapEvaluator` (evaluate.py), `ArgumentMapWriter` (writer.py), `ArgumentMapDiagram` (already a class).
3. Move `argumentation/backends/` to `models/`: `models/base.py` (`ModelBackend` ABC plus factory), `models/claude_agent.py`, `models/ollama_local.py`, `models/types.py`.
4. Empty `argumentation/__init__.py` and update callers (cli.py, tests, notebooks) to import from modules.
   Verify: all test_argumentation_* tests pass (update their imports only, not their assertions); the CLI still produces YAML and Mermaid output for an Ocado input.

## Phase 5: FastAPI read API (depends on 3)

1. Add dependencies `fastapi` and `uvicorn[standard]`.
2. `api/app.py`: `create_app()` with CORS for `http://localhost:5173`. `api/deps.py`: `Database` and session dependencies. `api/schemas.py`: response models.
3. Routers:
   - `routers/documents.py`: GET /documents (paginated), GET /documents/{id}
   - `routers/claims.py`: GET /claims (filters: document_id, claim_type, modality), GET /claims/{id} including evidence
   - `routers/graph.py`: GET /graph?document_id=…&run_id=… returns `{nodes:[{id,type,label,...}], edges:[{source,target,role}]}`; nodes cover documents, arguments, statements and entities
4. Run with `uv run uvicorn research_nlp.api.app:create_app --factory --reload`.
   Verify: endpoint tests using FastAPI TestClient against a temporary DB seeded with the gold fixtures; `/docs` loads; the Ocado graph returns 8 argument nodes.

## Phase 6: frontend scaffold (depends on 5)

1. `npm create vite@latest frontend -- --template react-ts`
2. Dependencies: react-router, @tanstack/react-query, cytoscape plus react-cytoscapejs; dev dependency openapi-typescript.
3. `frontend/src/`:
   - `app/`: router, providers, layout
   - `api/`: generated `schema.d.ts` (script `npm run gen:api` pointing at http://localhost:8000/openapi.json) plus a thin typed fetch client
   - `components/`: shared UI
   - `features/documents`, `features/claims`, `features/graph`: one page each, read-only
4. Vite dev proxy: `/api` to `http://localhost:8000`.
   Verify: `npm run build` passes; with the API running, each page renders Ocado data.

## Deliberately out of scope / deferred

- Email pipeline repair and relocation (classes.py to ingestion/types.py, utils.py to core/validation.py, pipeline.py to ingestion/). The user will handle this.
- Merging ontology_new into ontology (needs a user decision on which is canonical).
- Reorganising data/ (db/, backups/, raw/) and moving research_emails_* (the storage default paths belong to the email pipeline).
- Final names for `research_nlp` and `models` (rename later by search-and-replace).
- Authentication, write endpoints, a graph database, deployment.
