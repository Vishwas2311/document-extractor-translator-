# CareTranslate Studio Project Memory

**Purpose:** concise, durable context for humans and AI tools
**Deployment target:** Microsoft Azure (Azure Document Intelligence, Azure OpenAI, Azure Database for PostgreSQL, Azure Blob Storage, Azure Key Vault, Azure Container Apps)
**Last reviewed:** 2026-08-09
**Code baseline:** `main`

> This file records current facts and approved decisions. It is not a session transcript, task backlog, or place for secrets. Verify volatile facts against the code and deployment before acting.

## 1. Source-of-truth order

Use the repository in this order:

1. `docs/PRD.md` — product scope, users, requirements, and release gates.
2. `docs/DATA-SECURITY.md` — proposed processing options, control baseline, management decisions, and evidence gates.
3. `docs/ARCHITECTURE.md` — current and target system design.
4. `docs/RULES.md` — mandatory engineering, privacy, and AI-working rules.
5. Architecture Decision Records, when added — approved technical decisions.
6. `AGENTS.md` — contributor workflow.
7. This file — stable current-state memory and known limitations.
8. Code and tests — actual implemented behavior at the checked-out revision.

If code differs from the documents, report the difference. Do not silently rewrite a requirement to match an implementation defect.

## 2. Project identity

- **Product name:** CareTranslate Studio.
- **Repository name:** `document-extractor-translator-`.
- **Repository URL:** `https://github.com/Vishwas2311/document-extractor-translator-.git`.
- **Application root:** repository root (`backend/`, `frontend/`, `docs/`, `scripts/`).
- **Purpose:** extract structured content from multilingual case documents, translate supported source content to English, preserve layout/provenance, and provide reviewable results.
- **Current intended data:** synthetic or de-identified test documents only.
- **Production intent:** harden the current Azure-integrated implementation into a secure, auditable, human-reviewed Azure document-processing service.

## 3. Status vocabulary

- **Implemented:** present in the codebase and verified by inspection or test.
- **Partially implemented:** some code exists, but behavior or validation is incomplete.
- **Production target:** approved direction, not proof of deployment.
- **Open decision:** requires organizational, legal, security, product, or operational approval.

Never describe a production target as implemented.

## 4. Current processing flow

1. A user selects or drops a supported file in the web UI.
2. The frontend sends a multipart upload to the FastAPI backend.
3. The backend validates the request, writes the original file to artifact storage, and creates a document record in Azure Database for PostgreSQL.
4. In-process background work sends the file to Azure AI Document Intelligence using `prebuilt-layout`.
5. The mapper creates an immutable provider extraction artifact containing pages, ordered blocks,
   and provider tables; a separate versioned reconciliation stage may derive an effective table
   from complete row-aligned orphan columns while preserving source-block provenance.
6. The pipeline determines source language and prepares translatable blocks.
7. Azure OpenAI translates non-English content to English in batches.
8. Validation checks identifiers, coverage, ordering, and protected content.
9. JSON artifacts and status are persisted locally.
10. The frontend polls status and presents preview, extraction, and translation results.

The core ordering invariant is: **upload → extract → normalize → detect language → translate → validate → persist → review/export**.

The default LLM path uses the backend Data Security Gateway with
`GENAI_PSEUDONYMIZED` (deterministic token replacement for emails/phones/URLs/IDs).
`GENAI_SYNTHETIC_POC` may still send raw synthetic text when
`ALLOW_SYNTHETIC_RAW_LLM=true`. Confidential/restricted data cannot use the
synthetic raw path. Document API routes require `Authorization: Bearer` when
`AUTH_REQUIRED=true` (default). Full Entra/APIM/private networking remains a
production target, not a local claim.

## 5. Current technology snapshot

### Backend

- Python 3.12.
- FastAPI and Pydantic.
- SQLAlchemy, targeting Azure Database for PostgreSQL (async engine; portable across drivers by
  connection string).
- Artifact storage behind a swappable protocol; the Azure Blob Storage adapter is a release gate
  (see [ARCHITECTURE.md §4.5](./ARCHITECTURE.md) and §26).
- In-process background task execution (`InProcessJobRunner`) — see the scaling note in
  [ARCHITECTURE.md §26](./ARCHITECTURE.md).
- Azure AI Document Intelligence with the `prebuilt-layout` model.
- Azure OpenAI chat completion deployment configured for `gpt-4.1`.
- Alembic migrations are the schema-change mechanism; 8 revisions exist. A startup-time
  `create_all()`/ad hoc column-patch path also exists behind `USE_CREATE_ALL` and should not be
  used for production schema changes — see [RULES.md §11](./RULES.md).

### Frontend

- React `19.2.8`.
- Next-compatible application structure using Next `16.3.0` and Vinext `1.0.0-beta.5`.
- Vite `8.2.1` toolchain.
- PDF.js-based PDF preview.
- Browser polling for processing state.

These versions are a baseline snapshot, not a permanent constraint. Recheck lockfiles before an upgrade or security conclusion.

## 6. Stable processing constants

- **Artifact schema version:** `1.0`.
- **Processing version:** `prd-local-4` for newly created documents; prior stored attempts retain their original version. (The version-string prefix predates the current Azure-only deployment framing; it is a stable identifier, not a description of where the app runs.)
- **Translation prompt version:** `translation-v3-multilingual-format-aware`.
- **OCR confidence review threshold:** `0.85`.
- **Translation batch limit:** 40 blocks.
- **Translation text limit per batch:** 16,000 characters.
- **Translation concurrency:** up to 12 concurrent Azure OpenAI batch calls per document.
- **Document Intelligence page-range size:** 50 pages per range above the threshold, up to 4
  ranges analyzed concurrently per document (§8.1 of ARCHITECTURE.md).
- **Upload file-size ceiling:** 150 MB.
- **Document page-count ceiling:** 300 pages.

Any change that affects persisted structure, interpretation, or translation output must follow the versioning rules in `docs/RULES.md`.

## 7. Supported product scope

### Inputs

- PDF.
- JPEG/JPG.
- PNG.
- TIFF/TIF.
- BMP.

The backend accepts these formats today. DOCX and XLSX are production export targets, not accepted input formats. The preview experience is not yet equally complete for all accepted formats; PDF preview is the clearest implemented path.

### Languages

- Any syntactically valid Azure-detected non-English BCP 47 source tag is eligible for English translation; there is no hard-coded Arabic/Chinese source allowlist.
- Arabic and Han script fallbacks remain for missing provider hints, including Simplified/Traditional Chinese normalization.
- English content passes through without unnecessary translation.
- Latin script without a provider hint is `und`, not guessed as English.
- Mixed-language content is translated at block/cell level; unknown or invalid language remains review-required.
- Routing capability does not prove universal quality. Production languages and document families require approved multilingual extraction, translation, protected-token, PII, and correction-rate benchmarks.

### Output and review direction

- Current primary machine-readable result: JSON artifacts.
- Production-required exports: JSON, PDF, DOCX, CSV/XLSX for tabular data, and an audit/provenance manifest.
- Production review roles: Caseworker and Reviewer, with administrative, audit, and operations roles separated.

## 8. Persisted artifacts and state

Artifact storage (target: Azure Blob Storage) holds original uploads and derived JSON artifacts under a path scheme rooted at server-generated document identifiers; user file names must not become trusted paths.

Conceptually, each document retains:

- Original upload metadata and storage reference.
- Extraction artifact and schema version.
- Translation artifact and prompt/model version.
- Processing state and errors.
- Timing, provider, and confidence metadata where available.

Expected lifecycle states are documented in `docs/ARCHITECTURE.md`. Do not introduce new status strings outside that state model.

Production will replace local-only coordination with Blob Storage, PostgreSQL, Service Bus, and independently scalable workers while retaining immutable versioned artifacts.

## 9. Local development commands

Always check the repository README and package scripts for changes.

### Backend checks

```powershell
cd backend
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app tests
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

### Frontend checks

```powershell
cd frontend
npm ci
npm run lint
npm run build
npm test
```

Start commands should follow the root `README.md`; do not invent alternative ports or environment names without documenting them.

## 10. Configuration names

The exact set is controlled by the backend and frontend example environment files. Common configuration categories include:

- Azure AI Document Intelligence endpoint and credential.
- Azure OpenAI endpoint, credential, API version, and deployment name.
- Database URL.
- Artifact storage root (Blob container/prefix in production).
- CORS origin configuration.
- Backend API base URL exposed to the frontend only when it is safe to be public.
- Logging level and development mode.

Store names and placeholders in documentation, never real values. Never open or print a developer's `.env` merely to summarize the project.

## 11. Approved product decisions

- **Documentation scope:** Describe both the current implementation and production roadmap.

- **Current test data:** Synthetic or de-identified approved test data only.

- **Production data:** Real records only after privacy, security, legal, and operational gates
  are approved.

- **User roles:** Caseworker, Reviewer, Administrator, Auditor, System Operator.

- **Language scope:** English is the only target. Application routing accepts any valid detected non-English BCP 47 source tag; production enablement remains language/document-family benchmark-gated.

- **Preview:** Every advertised format needs a preview; otherwise narrow and disclose the
  supported preview scope.

- **Retention:** Production default 30 days, configurable from 1 to 90 days; audit metadata one
  year without document text, subject to jurisdiction.

- **Retry modes:** Resume, Retranslate, and Reprocess completely.

- **Human review:** Reviewers can correct and approve translations with versioned audit history.

- **Production platform:** Azure Container Apps for API and worker services.

- **Production limits:** Initial target: 50 MB and 200 pages per document, with measured
  processing-time SLOs.

- **Exports:** JSON, PDF, DOCX, CSV/XLSX for tables, and audit/provenance manifest.

Jurisdiction, exact compliance profile, identity tenant design, final SLOs, and cost budgets remain deployment-specific decisions.

## 11.1 Proposed security direction pending approval

1. **Decision/profile:** Production default
   - **Data route:** No raw confidential or restricted content in a generative LLM
   - **Exposed to generative LLM?:** Raw exposure prohibited by default
   - **Approval/implementation status:** Proposed organizational rule

2. **Decision/profile:** Azure OpenAI platform role
   - **Data route:** Retained for approved translation and future features
   - **Exposed to generative LLM?:** Yes only through an approved profile
   - **Approval/implementation status:** Production target

3. **Decision/profile:** `GENAI_PSEUDONYMIZED`
   - **Data route:** Regional/private DI → immediate result deletion → local minimization/PII
     detection/tokenization → private single-region Azure OpenAI
   - **Exposed to generative LLM?:** Yes; minimum pseudonymized blocks only
   - **Approval/implementation status:** Proposed normal Azure OpenAI-enabled route

4. **Decision/profile:** `MANAGED_NO_LLM`
   - **Data route:** Regional/private DI → immediate result deletion → regional/private Azure AI
     Translator
   - **Exposed to generative LLM?:** No
   - **Approval/implementation status:** Required alternative when generative AI is prohibited

5. **Decision/profile:** `RESTRICTED_LOCAL`
   - **Data route:** Approved connected/disconnected containers or authorized human fallback
   - **Exposed to generative LLM?:** No
   - **Approval/implementation status:** Proposed when content cannot leave the controlled
     boundary

6. **Decision/profile:** `GENAI_RAW_EXCEPTION`
   - **Data route:** Exact raw fields to hardened Azure OpenAI under written approval
   - **Exposed to generative LLM?:** Yes; approved raw scope only
   - **Approval/implementation status:** Exceptional, time-bounded and not a fallback

7. **Decision/profile:** Unknown/missing control
   - **Data route:** Quarantine or authorized human review
   - **Exposed to generative LLM?:** No new exposure
   - **Approval/implementation status:** Must fail closed

8. **Decision/profile:** Formal approval
   - **Data route:** ADR after management, Security, Privacy, Legal and data-owner approval
   - **Exposed to generative LLM?:** Depends on approved profile
   - **Approval/implementation status:** Not proof of implementation until evidence exists

1. **Target sequence:** 1
   - **Service boundary:** Entra ID + edge protection
   - **Data handled:** Identity and request metadata
   - **Exposed to generative LLM?:** No

2. **Target sequence:** 2
   - **Service boundary:** Quarantine + Defender malware scanning
   - **Data handled:** Complete uploaded file
   - **Exposed to generative LLM?:** No

3. **Target sequence:** 3
   - **Service boundary:** Private regional Document Intelligence
   - **Data handled:** Complete document and temporary extraction result
   - **Exposed to generative LLM?:** No

4. **Target sequence:** 4
   - **Service boundary:** Data Security Gateway
   - **Data handled:** Raw extracted text inside controlled boundary
   - **Exposed to generative LLM?:** No; it controls the handoff

5. **Target sequence:** 5
   - **Service boundary:** Private single-region Azure OpenAI
   - **Data handled:** Approved minimum pseudonymized blocks
   - **Exposed to generative LLM?:** **Yes**

6. **Target sequence:** 6
   - **Service boundary:** Validation + human review
   - **Data handled:** Model output and authorized source context
   - **Exposed to generative LLM?:** No additional exposure

7. **Target sequence:** 7
   - **Service boundary:** Encrypted storage + audit + retention
   - **Data handled:** Approved artifacts and content-free evidence
   - **Exposed to generative LLM?:** No

The readable diagram and complete service-control matrix are in `docs/DATA-SECURITY.md`.

## 12. Known limitations

1. Authentication is a bearer-token registry, not Entra ID; a real (if non-federated)
   organization/ownership/role authorization layer is implemented on top of it (see
   [ARCHITECTURE.md §2.1](./ARCHITECTURE.md)).
2. The Azure Blob Storage artifact-storage adapter is not yet built (protocol exists, filesystem
   implementation is the only concrete adapter today); Azure Database for PostgreSQL is supported
   by the existing SQLAlchemy async engine but not yet operationally validated in a deployed
   environment.
3. Processing runs in the API process rather than through a durable queue.
4. Resume, retranslate, and reprocess are implemented locally, but durable distributed delivery,
   dead-lettering, and multi-worker recovery remain production targets.
5. Financial correction, reconstruction decisions, and result approval are implemented;
   translation/block correction, assignment, organization ownership, and reviewed-export
   materialization remain incomplete.
6. Retention, legal hold, deletion orchestration, and audit retention are not implemented end to end.
7. Preview capability does not fully match all accepted file types.
8. Some UI security or service-status language is static and must not be treated as deployment evidence.
9. Production observability, cost controls, alerts, and operational runbooks are missing.
10. CI (lint, type check, test, build on every push/PR via GitHub Actions, with branch protection
    requiring both jobs to pass before merge to `main`) is established. SBOM generation, container
    scanning, and a deployed-Azure-environment gate are not yet established.
11. Frontend and Python production dependencies have reviewed lock artifacts, but CI SBOM/container
    vulnerability gates are not established. `npm audit` reports 2 high-severity findings
    (GHSA-w3rx-r6r6-pgpr, GHSA-5p2g-fcmc-qvqq) in `image-size`, a transitive dependency of `vinext`.
    No patched version exists upstream as of 2026-08-08 (both advisories report
    `first_patched_version: null`), and `npm audit` will keep reporting them regardless of the fix
    below, since it checks the declared package version, not patched file contents. The vulnerable
    code (vinext's file-based `app/icon.*`/`app/favicon.*`/`app/apple-icon.*` metadata-route
    generation) is not reachable in this app — no such files exist under `frontend/app/`; the
    favicon is a plain static path (`frontend/app/layout.tsx`) instead — but as defense-in-depth the
    actual infinite-loop bugs in `image-size`'s ICNS/HEIF/JXL parsers are patched via
    `frontend/patches/image-size+2.0.2.patch` (`patch-package`, auto-applied on `npm install` via
    the `postinstall` script). Do not run `npm audit fix --force` to "fix" this — it downgrades
    `vinext` to `0.0.45`, well below the version this project requires. Re-check `npm audit` on the
    next dependency update pass; once a real upstream fix ships, drop the patch and bump the
    version instead.
12. Object-level authorization (organization boundary, ownership, assignment) and an append-only
    audit trail are implemented (`core/authorization.py`, `audit_events` table); what's missing is
    Entra ID federation and a WORM-grade guarantee on the audit store beyond normal database row
    protection.
13. The backend enforces a processing profile and implements optional financial classification,
    but the production policy service, deployment allowlist, and operational kill switch are not
    established.
14. The pseudonymized route implements a lightweight regex-based tokenization gateway; approved
    multilingual PII detection and benchmark evidence remain production requirements.
15. Document Intelligence deletion is attempted immediately when a result ID is available, but
    durable deletion receipts, retry orchestration, deadline alerts, and deployment evidence are
    not implemented.
16. Azure AI Translator and connected/disconnected Document Intelligence/Translator container routes are not implemented.
17. Managed identity enforcement, private endpoints, outbound egress allowlisting, allowed-region/deployment policy, and modified-abuse-monitoring verification are not implemented.

## 13. Quality baseline from the 2026-08-06 review

The following results describe the inspected revision only:

- Current backend gate: Ruff passed, Mypy passed for 74 source files, and 119 tests passed.
- Current frontend gate: production build passed; two rendered HTML tests passed; lint had zero errors and two existing image-element warnings.
- Current frontend production dependency audit (2026-08-08, after upgrading `vinext` to
  `1.0.0-beta.5` and Next.js/lint config to 16.3.0): 2 high-severity `npm audit` findings in
  `image-size` (transitive via `vinext`), no upstream patch available; confirmed unreachable in
  this app's build — see section 12, item 11.
- Alembic upgraded from base through `0007_financial_structure_reviews` and downgraded to base successfully on a disposable SQLite database.
- Repository CI is established (GitHub Actions, §12 item 10); Azure deployment evidence is not.

Re-run all relevant checks after copying these documents or changing code. Replace this section when a newer verified baseline exists; do not simply append an ever-growing test diary.

## 14. Production architecture direction

1. **Architecture area:** Edge
   - **Selected direction:** Azure Front Door or approved equivalent
   - **Data/LLM effect:** Protects entry; no intended LLM exposure
   - **Status:** Production target

2. **Architecture area:** Compute
   - **Selected direction:** Azure Container Apps stateless API + separate workers
   - **Data/LLM effect:** Company application logic controls provider handoff
   - **Status:** Production target

3. **Architecture area:** Identity
   - **Selected direction:** Microsoft Entra ID
   - **Data/LLM effect:** Identity metadata only; no LLM exposure
   - **Status:** Production target

4. **Architecture area:** Queue
   - **Selected direction:** Azure Service Bus
   - **Data/LLM effect:** IDs/policy metadata only; no document content
   - **Status:** Production target

5. **Architecture area:** Policy
   - **Selected direction:** Backend classification and immutable processing-profile gateway
   - **Data/LLM effect:** Prevents unauthorized LLM route selection
   - **Status:** Production target

6. **Architecture area:** Data Security Gateway
   - **Selected direction:** Minimization, multilingual PII detection, deterministic
     tokenization, protected mappings, leakage validation and fail closed
   - **Data/LLM effect:** Keeps raw text out of the normal Azure OpenAI request
   - **Status:** Production target

7. **Architecture area:** Artifact storage
   - **Selected direction:** Private Azure Blob Storage
   - **Data/LLM effect:** Stores originals/versioned artifacts; no LLM exposure by storage
     itself
   - **Status:** Production target

8. **Architecture area:** Metadata
   - **Selected direction:** Azure Database for PostgreSQL
   - **Data/LLM effect:** Stores jobs/review/audit metadata; no LLM exposure
   - **Status:** Production target

9. **Architecture area:** Workload credentials
   - **Selected direction:** Managed identities + Key Vault
   - **Data/LLM effect:** Keys/secrets only; no source text
   - **Status:** Production target

10. **Architecture area:** Managed non-LLM route
   - **Selected direction:** Regional/private DI + Azure AI Translator
   - **Data/LLM effect:** No generative LLM exposure
   - **Status:** `MANAGED_NO_LLM` target

11. **Architecture area:** Controlled-boundary route
   - **Selected direction:** DI/Translator containers
   - **Data/LLM effect:** No managed-cloud document or LLM exposure for content
   - **Status:** `RESTRICTED_LOCAL` target

12. **Architecture area:** Generative route
   - **Selected direction:** Private single-region Azure OpenAI
   - **Data/LLM effect:** Pseudonymized blocks normally; raw only under `GENAI_RAW_EXCEPTION`
   - **Status:** Approval pending

13. **Architecture area:** Monitoring
   - **Selected direction:** Azure Monitor + Application Insights
   - **Data/LLM effect:** Content-free telemetry only
   - **Status:** Production target

14. **Architecture area:** Lifecycle
   - **Selected direction:** Scheduled retention/deletion worker
   - **Data/LLM effect:** Deletes artifacts/mappings and enforces legal holds
   - **Status:** Production target

These rows describe a production target, not the current deployment state.

## 15. Next engineering priorities

1. Run the controlled synthetic/de-identified extraction experiment (up to the 300-page ceiling) and approve recall/cost thresholds; keep the current implementation synthetic-only meanwhile.
2. Close current quality-gate findings and establish CI.
3. Add optional active provider probes or recent-call status without confusing configuration with
   provider health; the UI now labels configuration presence accurately.
4. Implement authentication, authorization, tenant boundaries, audit events, classification, and the fail-closed policy gateway.
5. Implement private networking, managed identity, egress controls, allowed-region/deployment policy, and content-free telemetry tests.
6. Move to PostgreSQL, Blob Storage, Service Bus, and separate workers.

## Financial extraction current state

- **Implemented:** versioned financial schemas (`financial-result-1.4`, `financial-validation-1.3`, `table-reconciliation-1.0`), page decisions, multilingual currency/term layout fallback, immutable provider tables plus bounded aligned-column reconstruction, an ordered page-scoped financial-only stream preserving headings/paragraphs/key-values/lists/tables, semantic cell typing before contextual currency-aware Decimal normalization, monetary-only correction gates, validation reports, formula-safe CSV, XLSX, JSON, page filters, source-page provenance, and focused automated tests.
- **Implemented but configuration-dependent:** Azure Document Intelligence custom-classifier call and selective bounded-range extraction. Enable with `FINANCIAL_EXTRACTION_MODE=selective` and an approved `FINANCIAL_CLASSIFIER_MODEL_ID`.
- **Current local default:** `post_extract`; it provides financial artifacts but still performs layout extraction over the full source.
- **Implemented P1 review:** append-only financial corrections, reconstructed-table accept/reject decisions, and result approve/reject decisions bound to the exact processing version and result SHA-256; approval requires every active reconstruction to be accepted and cannot clear unrelated OCR/translation review.
- **Implemented retry/reprocess safety:** all retry modes adopt the current processing contract;
  approved financial results block every retry mode; reprocess adds manifest-first invalidation,
  complete derived-artifact cleanup, and stale-artifact denial.
- **Production target:** labeled classifier corpus and quality gates, Entra/tenant authorization, malware quarantine, private Azure networking, Blob/PostgreSQL/Service Bus adapters, durable deletion evidence, and reviewed-export materialization.
- **Schema migrations:** `0005_financial_extraction` adds financial summary fields and mode; `0006_financial_reviews` adds result hashes, review summaries, constraints, and append-only reviews; `0007_financial_structure_reviews` persists reconstruction decisions.
- **Detailed specification:** [FINANCIAL-EXTRACTION.md](./FINANCIAL-EXTRACTION.md).
7. Build and red-team the `GENAI_PSEUDONYMIZED` Data Security Gateway, hardened Azure OpenAI adapter, and multilingual leakage benchmark.
8. Add `MANAGED_NO_LLM`, durable provider-deletion receipts/retry/alerting (including a documented
   classifier-result retention decision), and the required restricted-local container proof.
9. Extend the implemented financial review overlay to translation/block corrections, assignment, reviewed exports, and production authorization.
10. Move the implemented retry modes to durable Service Bus delivery with dead-letter evidence.
11. Complete or honestly narrow preview support.
12. Implement retention, deletion, quarantine, malware scanning, legal hold, and deletion evidence.
13. Complete security, privacy, accessibility, resilience, and operational readiness gates.

The full roadmap and exit criteria are in `docs/PRD.md`.

## 16. How to maintain this memory

Update this file only when a stable fact changes, such as:

- Current phase or verified baseline revision.
- Supported formats or languages.
- Schema, processing, or prompt versions.
- Standard commands.
- Approved product decisions.
- Architecture that has actually been implemented.
- Known limitations whose status materially changed.

Do not store:

- Secrets, credentials, endpoints containing secrets, or personal data.
- Temporary task plans or conversational history.
- Speculation presented as a decision.
- Unverified deployment claims.
- Long debugging logs better suited to an issue or runbook.

When updating, remove stale facts rather than accumulating contradictions.
