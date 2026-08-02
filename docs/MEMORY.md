# CareTranslate Studio Project Memory

**Purpose:** concise, durable context for humans and AI tools
**Current phase:** functional POC; production readiness work remains
**Last reviewed:** 2026-08-02
**Code baseline:** commit `14518cc` on `main`

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
- **Application root:** `document-intelligence-platform/` in the current repository.
- **Purpose:** extract structured content from multilingual case documents, translate supported source content to English, preserve layout/provenance, and provide reviewable results.
- **Current intended data:** synthetic or de-identified test documents only.
- **Production intent:** evolve the POC into a secure, auditable, human-reviewed document-processing service.

## 3. Status vocabulary

- **Implemented:** present in the baseline and verified by inspection or test.
- **Partially implemented:** some code exists, but behavior or validation is incomplete.
- **Production target:** approved direction, not proof of deployment.
- **Open decision:** requires organizational, legal, security, product, or operational approval.

Never describe a production target as implemented.

## 4. Current POC flow

1. A user selects or drops a supported file in the web UI.
2. The frontend sends a multipart upload to the FastAPI backend.
3. The backend validates the request, writes the original file to local storage, and creates a SQLite document record.
4. In-process background work sends the file to Azure AI Document Intelligence using `prebuilt-layout`.
5. The mapper creates a normalized extraction artifact containing pages and ordered blocks.
6. The pipeline determines source language and prepares translatable blocks.
7. Azure OpenAI translates non-English content to English in batches.
8. Validation checks identifiers, coverage, ordering, and protected content.
9. JSON artifacts and status are persisted locally.
10. The frontend polls status and presents preview, extraction, and translation results.

The core ordering invariant is: **upload → extract → normalize → detect language → translate → validate → persist → review/export**.

The current Azure OpenAI request batches contain the full extracted source text selected for translation. There is no production classification/policy gateway or pseudonymization boundary. This is one reason the POC remains restricted to synthetic or explicitly approved de-identified data.

## 5. Current technology snapshot

### Backend

- Python 3.12.
- FastAPI and Pydantic.
- SQLAlchemy with SQLite for the POC.
- Local filesystem artifact storage.
- In-process background task execution.
- Azure AI Document Intelligence with the `prebuilt-layout` model.
- Azure OpenAI chat completion deployment configured for `gpt-5-mini` in the current POC setup.
- Alembic is present, but production migration discipline is not yet established.

### Frontend

- React `19.2.6`.
- Next-compatible application structure using Next `16.2.6` and Vinext `0.0.50`.
- Vite `8.0.13` toolchain.
- PDF.js-based PDF preview.
- Browser polling for processing state.

These versions are a baseline snapshot, not a permanent constraint. Recheck lockfiles before an upgrade or security conclusion.

## 6. Stable processing constants

- **Artifact schema version:** `1.0`.
- **Processing version:** `poc-1`.
- **Translation prompt version:** `translation-v2-table-aware`.
- **OCR confidence review threshold:** `0.85`.
- **Translation batch limit:** 25 blocks.
- **Translation text limit per batch:** approximately 12,000 characters.
- **POC file-size ceiling:** 50 MB.
- **Production page-count target:** 200 pages.

Any change that affects persisted structure, interpretation, or translation output must follow the versioning rules in `docs/RULES.md`.

## 7. Supported product scope

### Inputs

- PDF.
- JPEG/JPG.
- PNG.
- TIFF/TIF.
- BMP.

The backend accepts these formats in the current POC. DOCX and XLSX are production export targets, not accepted input formats. The preview experience is not yet equally complete for all accepted formats; PDF preview is the clearest implemented path.

### Languages

- Arabic to English.
- Simplified Chinese to English.
- Traditional Chinese to English.
- English content should pass through without unnecessary translation.
- Mixed-language documents require block-level handling and review where confidence is low.

### Output and review direction

- Current primary machine-readable result: JSON artifacts.
- Production-required exports: JSON, PDF, DOCX, CSV/XLSX for tabular data, and an audit/provenance manifest.
- Production review roles: Caseworker and Reviewer, with administrative, audit, and operations roles separated.

## 8. Persisted artifacts and state

The POC uses local directories for original uploads and derived JSON artifacts. Server-generated document identifiers must control paths; user file names must not become trusted paths.

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
- Local storage root.
- CORS origin configuration.
- Backend API base URL exposed to the frontend only when it is safe to be public.
- Logging level and development mode.

Store names and placeholders in documentation, never real values. Never open or print a developer's `.env` merely to summarize the project.

## 11. Approved product decisions

- **Documentation scope:** Describe both the implemented POC and production roadmap.

- **POC data:** Synthetic or de-identified approved test data only.

- **Production data:** Real records only after privacy, security, legal, and operational gates
  are approved.

- **User roles:** Caseworker, Reviewer, Administrator, Auditor, System Operator.

- **Chinese scope:** Support Simplified and Traditional Chinese.

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

## 12. Known limitations at the baseline

1. There is no production authentication or role-based authorization.
2. The POC uses SQLite and local disk, which are not appropriate for horizontally scaled production workloads.
3. Processing runs in the API process rather than through a durable queue.
4. Retry behavior is not yet the versioned three-mode production design.
5. Reviewer correction and approval workflow is incomplete.
6. Retention, legal hold, deletion orchestration, and audit retention are not implemented end to end.
7. Preview capability does not fully match all accepted file types.
8. Some UI security or service-status language is static and must not be treated as deployment evidence.
9. Production observability, cost controls, alerts, and operational runbooks are missing.
10. CI release gates, SBOM generation, container scanning, and deployment evidence are not established.
11. Dependency reproducibility and vulnerability handling need production hardening.
12. Tenant isolation, object-level authorization, and production audit trails are not implemented.
13. There is no document classification, server-side processing-policy gateway, immutable profile decision, or provider/profile kill switch.
14. The current Azure OpenAI translation path receives full extracted source text; no PII tokenization or pseudonymization boundary exists.
15. Immediate Document Intelligence analyze-result deletion, deletion evidence, and provider-retention alerting are not implemented.
16. Azure AI Translator and connected/disconnected Document Intelligence/Translator container routes are not implemented.
17. Managed identity enforcement, private endpoints, outbound egress allowlisting, allowed-region/deployment policy, and modified-abuse-monitoring verification are not implemented.

## 13. Quality baseline from the 2026-08-02 review

The following results describe the inspected revision only:

- Backend tests: 21 of 21 passed.
- Ruff: one known line-length finding in `backend/app/storage/local.py`.
- Mypy: stopped with an internal error under the installed `2.3.0` environment; this is inconclusive and requires toolchain investigation.
- Frontend lint: five errors and 162 warnings; one error concerns application memoization and four arise from vendored PDF.js code.
- Frontend build: inconclusive in the inspected sandbox because process creation returned `spawn EPERM`; do not report this as a confirmed application build failure.
- Repository CI: no authoritative CI workflow was identified at the baseline.

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

1. Obtain the management/security/privacy/legal decisions in `docs/DATA-SECURITY.md`; keep the POC synthetic-only meanwhile.
2. Close current quality-gate findings and establish CI.
3. Make service status and product claims reflect real runtime state.
4. Implement authentication, authorization, tenant boundaries, audit events, classification, and the fail-closed policy gateway.
5. Implement private networking, managed identity, egress controls, allowed-region/deployment policy, and content-free telemetry tests.
6. Move to PostgreSQL, Blob Storage, Service Bus, and separate workers.
7. Build and red-team the `GENAI_PSEUDONYMIZED` Data Security Gateway, hardened Azure OpenAI adapter, and multilingual leakage benchmark.
8. Add `MANAGED_NO_LLM`, immediate provider-result deletion, and the required restricted-local container proof of capability.
9. Add versioned reviewer correction and approval.
10. Implement all retry modes with idempotent processing and no profile downgrade.
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
