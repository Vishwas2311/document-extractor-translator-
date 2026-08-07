# CareTranslate Studio Product Requirements Document

- **Product:** CareTranslate Studio

- **Phase:** P0/P1 local evaluation baseline; P2 Azure platform deferred until experiment evidence

- **Implementation baseline:** Current uncommitted evaluation tree; verify revision before release

- **Last reviewed:** 2026-08-06

- **Product owner:** To be assigned

- **Technical owner:** To be assigned

## 1. Purpose

This PRD defines the product problem, users, implemented local evaluation behavior, production requirements, success measures, and release boundaries for CareTranslate Studio. It is the source of truth for **what** the product must do and **why**.

- Implementation design belongs in [ARCHITECTURE.md](./ARCHITECTURE.md).
- The manager-facing processing options, security controls, and approval gates belong in [DATA-SECURITY.md](./DATA-SECURITY.md).
- Mandatory engineering and safety constraints belong in [RULES.md](./RULES.md).
- Stable current facts and decisions belong in [MEMORY.md](./MEMORY.md).
- The financial extraction implementation contract and diagrams belong in [FINANCIAL-EXTRACTION.md](./FINANCIAL-EXTRACTION.md).

### Requirement status

- **Implemented**: Present in the current repository.
- **Partially implemented**: Some behavior exists, but the complete product promise is not met.
- **Production target**: Approved production direction that is not current behavior.
- **Open decision**: Requires organizational, legal, product, or technical approval.

Status labels must be updated when behavior changes. Proposed features must never be described as implemented.

## 2. Product summary

CareTranslate Studio is a human-in-the-loop document intelligence workspace for youth-care teams. It accepts multilingual documents, extracts text and layout, translates eligible content into English, preserves page and source-format context, and presents synchronized financial review and export views. The current synthetic-only local baseline uses Azure Document Intelligence and Azure OpenAI. Azure OpenAI remains a planned production component for translation and future approved features, but the backend must select an approved data-security profile first. The normal Azure OpenAI-enabled route sends only the minimum pseudonymized content; raw confidential or restricted content is prohibited by default.

The product accelerates initial understanding and structured review. It does not make clinical, safeguarding, eligibility, legal, or care decisions. Machine extraction and translation remain subject to human verification.

## 3. Problem statement

Youth-care teams can receive documents in languages that reviewers do not read fluently. Manual transcription and initial translation can be slow and difficult to trace back to the original page. Risk increases when documents contain tables, identifiers, dates, names, handwriting, or low-quality scans.

The product must help an authorized reviewer answer:

1. What content was extracted from each page?
2. What is the corresponding English translation?
3. Where did each result originate on the source document?
4. Which results require human attention before use?

The product must provide assistance without presenting uncertain output as verified fact.

## 4. Product principles

1. **Human accountability** — people make care and safeguarding decisions.
2. **Source traceability** — every result remains linked to its source page and region.
3. **Structural fidelity** — reading order, tables, cells, IDs, and protected values are preserved.
4. **Visible uncertainty** — low-confidence or invalid output is clearly reviewable.
5. **Privacy by design** — collect, transmit, retain, and expose only what is required.
6. **Honest status** — security, connection, and processing claims reflect real system state.
7. **Recoverable processing** — extraction remains useful if translation fails.
8. **Versioned results** — schemas, prompts, processing attempts, corrections, and approvals are traceable.

9. **Default-deny data routing** — unclassified content or an unavailable approved route stops for review; it never falls back to a less restrictive service.

## 5. Users and roles

### Current local evaluation baseline

The local baseline has backend bearer-token authentication but no Entra identity, organization model, tenant isolation, assignment, or document-ownership authorization. Its token gate is a development containment control, not production RBAC.

### Production roles

1. **Role:** Caseworker
   - **Responsibilities:** Upload, monitor, review, request review, download approved results
   - **Access principle:** Authorized organizations and assigned cases only

2. **Role:** Translation reviewer
   - **Responsibilities:** Correct blocks/cells, comment, approve or reject
   - **Access principle:** Assigned review documents only

3. **Role:** Organization administrator
   - **Responsibilities:** Manage users, roles, policy, limits, retention, and integrations
   - **Access principle:** Metadata by default; content only when explicitly authorized

4. **Role:** Compliance auditor
   - **Responsibilities:** Inspect audit events, policy application, deletion evidence, and
     approvals
   - **Access principle:** Audit metadata by default

5. **Role:** Platform operator
   - **Responsibilities:** Maintain infrastructure and respond to incidents
   - **Access principle:** No routine content access; audited break-glass only

Backend authorization is mandatory. Hiding frontend controls is not authorization.

## 6. Goals

### Local evaluation goals

- Demonstrate page, paragraph, table, language, geometry, and confidence extraction.
- Demonstrate language-agnostic routing of valid detected non-English language tags to English translation, with unknown language routed to review.
- Demonstrate stable IDs and schema-constrained translation responses.
- Demonstrate synchronized source overlays and result cards.
- Produce page-wise JSON and complete extracted/bilingual exports.
- Preserve extracted content when translation fails.
- Provide a synthetic demo without Azure credentials.

### Production goals

- Authenticate and authorize approved organizations and users.
- Support correction, review, approval, rejection, and immutable history.
- Enforce residency, retention, deletion, audit, and security policies.
- Replace local persistence and in-process execution with durable managed services.
- Meet measurable reliability, performance, accessibility, and quality targets.
- Preview every format the product accepts.
- Assign and enforce a backend-controlled processing profile before any external content transmission.
- Keep raw confidential and restricted content out of generative LLMs by default.
- Support a secure pseudonymized Azure OpenAI route for approved classifications.
- Support managed no-LLM, restricted local-processing, and approved human-only alternatives when generative AI or cloud processing is prohibited.

## 7. Non-goals

CareTranslate Studio does not:

- Diagnose a person, recommend treatment, or rank a person by risk.
- Make safeguarding, eligibility, legal, or care decisions.
- Replace a qualified translator or interpreter.
- Produce a certified translation without a separate approved process.
- Infer facts missing from the source document.
- Follow instructions found inside uploaded documents.
- Automatically update an official case record without authorized review.
- Act as the permanent system of record for source documents.

## 8. Supported scope

### File formats

Target formats are PDF, PNG, JPEG/JPG, TIFF/TIF (including multi-page TIFF), and BMP. The backend currently accepts all of them. Reliable live preview currently works for PDF only; image preview is a production requirement and a local-baseline gap.

### Languages

- **Implemented routing contract:** Azure Document Intelligence language spans supply a BCP 47 tag. Any syntactically valid detected non-English tag is eligible for the Azure OpenAI English-translation route; English is retained without translation.
- **Implemented script fallbacks:** Arabic and Han scripts are recognized when a provider hint is absent. Latin-script text without a provider hint is not guessed as English.
- **Implemented safety behavior:** `und`, invalid, and low-confidence language outcomes are not silently translated or passed through; they remain review-required.
- **Current automated fixtures:** Arabic, Simplified/Traditional Chinese routing, French, Hindi, Russian, Spanish, mixed text, English, numeric-only content, and unknown language.
- **Production constraint:** source-language routing is not the same as proven translation quality. Each advertised language and document family requires approved extraction, translation, protected-token, PII-detection, and reviewer-correction benchmarks before production enablement.

Use **Chinese**, **Simplified Chinese**, or **Traditional Chinese** for written-language labels. “Mandarin” is not sufficient as the only written-language label.

English is the only approved target language. Adding another target language requires a PRD, schema, prompt, UI, benchmark, and security review.

## 9. User journeys

### Explore the demo

1. The user opens the Studio without Azure credentials.
2. A clearly labelled synthetic three-page document appears.
3. The user navigates pages, zooms, rotates, toggles overlays, and switches among extracted, translated, and JSON views.
4. Source-region hover and selection synchronize with result cards.
5. Synthetic JSON can be downloaded.

### Process a document in local evaluation

1. The local user uploads or drops one accepted file.
2. The backend validates extension, size, signature, and extension/signature agreement.
3. The API returns `202 Accepted` with a document ID.
4. The browser polls processing status.
5. Azure Document Intelligence extracts layout and text.
6. The backend normalizes pages, blocks, tables, cells, languages, spans, and polygons.
7. Extracted page JSON is persisted before translation.
8. Eligible content is translated in bounded batches using structured output.
9. IDs, order, non-empty output, and protected tokens are validated.
10. Page JSON, exports, and a manifest are written.
11. The browser loads the review workspace.
12. If translation fails after extraction, extracted content remains available and the document is marked failed.

### Review and approve in production

1. An authenticated caseworker uploads an authorized document.
2. Ownership, policy, malware, file, and quota checks run in quarantine.
3. The backend assigns an approved processing profile from classification, jurisdiction, organization policy, and active exceptions.
4. The selected profile routes the document to managed services without a generative LLM, controlled-boundary containers, an approved pseudonymized generative-AI exception, or human-only review.
5. Processing creates a versioned machine result and an immutable content-free policy decision record.
6. Review-required results enter an assigned queue.
7. A reviewer corrects blocks/cells and records reasons.
8. The reviewer approves or rejects the document.
9. The system records an immutable version and audit event.
10. Approved exports become available to authorized users or an approved record-system integration.
11. Temporary and provider-side processing artifacts are deleted according to policy, with deletion evidence.

## 10. Functional requirements

### Ingestion and lifecycle

1. **ID:** FR-001
   - **Requirement:** Accept PDF, PNG, JPEG, TIFF, and BMP.
   - **Status:** Partially implemented — preview is PDF-only

2. **ID:** FR-002
   - **Requirement:** Validate extension, size, signature, and extension/signature agreement.
   - **Status:** Implemented

3. **ID:** FR-003
   - **Requirement:** Default the application upload limit to 50 MB.
   - **Status:** Implemented

4. **ID:** FR-004
   - **Requirement:** Default production page limit to 200, configurable downward per
     organization.
   - **Status:** Production target

5. **ID:** FR-005
   - **Requirement:** Malware-scan production uploads before extraction.
   - **Status:** Production target

6. **ID:** FR-006
   - **Requirement:** Store document ID, content hash, lifecycle state, timestamps, and
     processing attempt.
   - **Status:** Implemented

7. **ID:** FR-007
   - **Requirement:** Define organization-level duplicate-upload behavior.
   - **Status:** Open decision

8. **ID:** FR-008
   - **Requirement:** Prevent normal deletion while processing.
   - **Status:** Implemented

9. **ID:** FR-009
   - **Requirement:** Delete source and derived data through production policy and record
     deletion evidence.
   - **Status:** Production target

### Extraction and normalization

1. **ID:** FR-010
   - **Requirement:** Extract pages, text, roles, tables, spans, languages, polygons, and
     available confidence.
   - **Status:** Implemented

2. **ID:** FR-011
   - **Requirement:** Preserve page number, count, dimensions, units, and angle.
   - **Status:** Implemented

3. **ID:** FR-012
   - **Requirement:** Assign deterministic text-block IDs and reading order.
   - **Status:** Implemented

4. **ID:** FR-013
   - **Requirement:** Preserve structured tables/cells with stable IDs, row/column spans, and
     geometry.
   - **Status:** Implemented

5. **ID:** FR-014
   - **Requirement:** Never duplicate table-cell content as ordinary paragraph output.
   - **Status:** Implemented

6. **ID:** FR-015
   - **Requirement:** Persist extraction before translation.
   - **Status:** Implemented

7. **ID:** FR-016
   - **Requirement:** Handle empty or invalid geometry without breaking the viewer.
   - **Status:** Production target

### Language and translation

1. **ID:** FR-020
   - **Requirement:** Route any valid detected non-English BCP 47 source language, including mixed content, to English translation without a hard-coded source-language allowlist.
   - **Status:** Partially implemented — generic routing and structured translation are implemented; production quality/security approval remains language- and document-family-specific

2. **ID:** FR-021
   - **Requirement:** Preserve existing English without unnecessary translation.
   - **Status:** Implemented

3. **ID:** FR-022
   - **Requirement:** Route unknown language to review.
   - **Status:** Implemented

4. **ID:** FR-023
   - **Requirement:** Translate faithfully without summarizing, omitting, censoring, or adding
     facts.
   - **Status:** Implemented as a prompt rule; benchmark pending

5. **ID:** FR-024
   - **Requirement:** Preserve translation input IDs and order exactly.
   - **Status:** Implemented

6. **ID:** FR-025
   - **Requirement:** Preserve names, dates, numbers, case codes, URLs, emails, and protected
     tokens.
   - **Status:** Implemented

7. **ID:** FR-026
   - **Requirement:** Translate table cells independently without merging or duplication.
   - **Status:** Implemented

8. **ID:** FR-027
   - **Requirement:** Treat uploaded-document instructions as untrusted data.
   - **Status:** Implemented as a prompt rule; adversarial suite pending

9. **ID:** FR-028
   - **Requirement:** Respect translation batch limits.
   - **Status:** Implemented — 25 blocks/12,000 characters by default

10. **ID:** FR-029
   - **Requirement:** Record schema, processing, prompt, model deployment, and attempt versions.
   - **Status:** Partially implemented

### Validation and human review

1. **ID:** FR-030
   - **Requirement:** Reject empty successful translation for non-empty source.
   - **Status:** Implemented

2. **ID:** FR-031
   - **Requirement:** Mark text below the configured OCR threshold for review.
   - **Status:** Implemented — default 0.85

3. **ID:** FR-032
   - **Requirement:** Support OCR-confidence review for table cells.
   - **Status:** Production target

4. **ID:** FR-033
   - **Requirement:** Support block/cell corrections with reasons.
   - **Status:** Partially implemented — financial-cell corrections are append-only; translation/block corrections and object authorization remain targets

5. **ID:** FR-034
   - **Requirement:** Support Draft, Needs review, In review, Approved, and Rejected.
   - **Status:** Production target

6. **ID:** FR-035
   - **Requirement:** Record reviewer, timestamp, comment, correction, and decision.
   - **Status:** Partially implemented — financial reviewer, timestamp, note, correction, decision, processing version and result hash are persisted

7. **ID:** FR-036
   - **Requirement:** Never present machine output as certified without a separate approved
     process.
   - **Status:** Production target

### Review workspace

1. **ID:** FR-040
   - **Requirement:** Provide thumbnails, navigation, zoom, fit, rotation, and overlays.
   - **Status:** Implemented for PDF/demo

2. **ID:** FR-041
   - **Requirement:** Synchronize source overlays with result hover and selection.
   - **Status:** Implemented

3. **ID:** FR-042
   - **Requirement:** Provide extracted, translated, and page JSON views.
   - **Status:** Implemented

4. **ID:** FR-043
   - **Requirement:** Keep tables grouped and in page reading order.
   - **Status:** Implemented

5. **ID:** FR-044
   - **Requirement:** Indicate review status without relying only on color.
   - **Status:** Partially implemented

6. **ID:** FR-045
   - **Requirement:** Drive connection/security indicators from real state.
   - **Status:** Production target

7. **ID:** FR-046
   - **Requirement:** Preview every accepted file format.
   - **Status:** Production target

8. **ID:** FR-047
   - **Requirement:** Resume an authorized document after browser reload.
   - **Status:** Production target
9. **ID:** FR-048
   - **Requirement:** Present financial-only results as one ordered document stream that preserves headings, paragraphs, key-values, list items, table grids/spans, source pages, source text, translations, and separate normalized values.
   - **Status:** Implemented in `financial-result-1.4` with compatibility for stored table-only 1.1 results

10. **ID:** FR-049
   - **Requirement:** Preserve the immutable Document Intelligence table result while allowing
     a separately versioned effective table to join only complete, row-aligned orphan columns;
     retain source-block provenance and require explicit reviewer acceptance or rejection.
   - **Status:** Implemented for the bounded `aligned-orphan-columns-1.0` policy; broader
     continuation-table merging remains corpus-gated



### Retry and recovery

1. **ID:** FR-050
   - **Requirement:** Provide basic retry for failed/reviewable processing.
   - **Status:** Partially implemented

2. **ID:** FR-051
   - **Requirement:** Provide **Resume** using valid artifacts.
   - **Status:** Production target

3. **ID:** FR-052
   - **Requirement:** Provide **Retranslate** using extraction but bypassing translation cache.
   - **Status:** Production target

4. **ID:** FR-053
   - **Requirement:** Provide **Reprocess completely** as a fresh version.
   - **Status:** Partially implemented — derived artifacts are fail-closed invalidated; immutable multi-version result materialization remains a target

5. **ID:** FR-054
   - **Requirement:** Never silently overwrite an approved result.
   - **Status:** Partially implemented — approved financial results block reprocess; full-document approved-version handling remains a target

6. **ID:** FR-055
   - **Requirement:** Recover safely after worker/service restart.
   - **Status:** Production target

### Exports

1. **ID:** FR-060
   - **Requirement:** Download page-level canonical JSON.
   - **Status:** Implemented

2. **ID:** FR-061
   - **Requirement:** Provide complete extracted and bilingual JSON.
   - **Status:** Implemented in API

3. **ID:** FR-062
   - **Requirement:** Provide bilingual review PDF with machine/review status.
   - **Status:** Production target

4. **ID:** FR-063
   - **Requirement:** Provide editable DOCX with source references and version metadata.
   - **Status:** Production target

5. **ID:** FR-064
   - **Requirement:** Provide CSV/XLSX when structured tables exist.
   - **Status:** Partially implemented — financial table CSV/XLSX is implemented; reviewed-result materialization and general table export remain targets

6. **ID:** FR-065
   - **Requirement:** Provide an audit manifest with hashes and processing/review metadata.
   - **Status:** Production target

### Data-security and processing policy

1. **ID:** FR-070
   - **Requirement:** Classify every document and assign a server-side processing profile before
     any external content transmission.
   - **Status:** Production target

2. **ID:** FR-071
   - **Requirement:** Deny external processing when classification, jurisdiction, policy,
     provider approval, or required control evidence is unknown or invalid.
   - **Status:** Production target

3. **ID:** FR-072
   - **Requirement:** Persist the policy version, selected profile, provider, feature, region,
     deployment type, authentication/network mode, and exception ID for each attempt without
     copying document content into the audit record.
   - **Status:** Production target

4. **ID:** FR-073
   - **Requirement:** Provide `GENAI_PSEUDONYMIZED`: regional/private Document Intelligence with
     immediate result deletion, then server-side minimization, multilingual PII detection,
     deterministic tokenization and approved blocks sent to a hardened single-region Azure
     OpenAI deployment.
   - **Status:** Open decision — recommended Azure OpenAI-enabled production route

5. **ID:** FR-074
   - **Requirement:** Provide `RESTRICTED_LOCAL`: approved connected/disconnected Document
     Intelligence and Translator containers, or authorized human review, when content cannot
     leave the controlled boundary.
   - **Status:** Production target

6. **ID:** FR-075
   - **Requirement:** Provide `MANAGED_NO_LLM` using regional/private Document Intelligence and
     Azure AI Translator when generative AI is prohibited, and prohibit raw
     confidential/restricted Azure OpenAI processing unless a valid `GENAI_RAW_EXCEPTION`
     explicitly permits the exact data class, purpose and period.
   - **Status:** Open decision — recommended production rule

7. **ID:** FR-076
   - **Requirement:** Call the Document Intelligence Delete Analyze Result operation immediately
     after successful retrieval, retry failures, alert on overdue deletion, and retain
     content-free evidence.
   - **Status:** Production target

8. **ID:** FR-077
   - **Requirement:** For `GENAI_PSEUDONYMIZED`, minimize and deterministically pseudonymize
     content locally, protect the mapping separately, validate multilingual leakage, and fail
     closed below the approved confidence threshold.
   - **Status:** Production target

9. **ID:** FR-078
   - **Requirement:** Prevent the frontend, a retry, an outage, or a lower-privileged user from
     selecting or downgrading a processing profile.
   - **Status:** Production target

10. **ID:** FR-079
   - **Requirement:** Prohibit silent fallback to another provider, region, model, deployment
     type, or less restrictive profile.
   - **Status:** Production target

11. **ID:** FR-080
   - **Requirement:** For every sensitive Azure OpenAI profile, prohibit unapproved stateful,
     Batch, fine-tuning, preview, Global, and DataZone features/deployments.
   - **Status:** Production target

12. **ID:** FR-081
   - **Requirement:** Provide a provider/profile kill switch that stops new external processing
     while preserving authorized recovery and deletion operations.
   - **Status:** Production target

13. **ID:** FR-082
   - **Requirement:** Serve sensitive browser responses with explicit no-store behavior and
     exclude document content from client analytics, session replay, URLs, and error reporting.
   - **Status:** Production target

14. **ID:** FR-083
   - **Requirement:** Include policy enforcement, forbidden-provider, egress, deletion,
     logging/caching, tenant-isolation, and downgrade tests in release evidence.
   - **Status:** Production target

## 11. Non-functional requirements

### Security and privacy

1. **Control ID:** NFR-SEC-01
   - **Control area:** Authentication
   - **Product requirement:** Authenticate production users with Microsoft Entra ID or an
     approved equivalent
   - **LLM exposure effect:** Prevents anonymous initiation of AI processing
   - **Status:** Production target

2. **Control ID:** NFR-SEC-02
   - **Control area:** Authorization
   - **Product requirement:** Enforce authorization at API and data layers for every content
     operation
   - **LLM exposure effect:** Prevents unauthorized users from causing or viewing AI processing
   - **Status:** Production target

3. **Control ID:** NFR-SEC-03
   - **Control area:** Ownership
   - **Product requirement:** Check organization/document ownership on every read, write,
     export, retry and delete
   - **LLM exposure effect:** Prevents cross-tenant content from entering another tenant's
     workflow
   - **Status:** Production target

4. **Control ID:** NFR-SEC-04
   - **Control area:** Workload identity
   - **Product requirement:** Use managed identity and least privilege for production service
     access
   - **LLM exposure effect:** Restricts which workload may call Document Intelligence or Azure
     OpenAI
   - **Status:** Production target

5. **Control ID:** NFR-SEC-05
   - **Control area:** Secrets
   - **Product requirement:** Store secrets in Key Vault or an approved secret store
   - **LLM exposure effect:** Prevents credential leakage; source content is prohibited in the
     secret store
   - **Status:** Production target

6. **Control ID:** NFR-SEC-06
   - **Control area:** Encryption
   - **Product requirement:** Encrypt source and derived content in transit and at rest
   - **LLM exposure effect:** Protects copies before and after any approved model call
   - **Status:** Production target

7. **Control ID:** NFR-SEC-07
   - **Control area:** Telemetry
   - **Product requirement:** Exclude document text and PII from logs, analytics, traces and
     errors
   - **LLM exposure effect:** Prevents secondary LLM/content exposure through observability
     tools
   - **Status:** Production target

8. **Control ID:** NFR-SEC-08
   - **Control area:** Lifecycle
   - **Product requirement:** Enforce automatic retention and verifiable deletion
   - **LLM exposure effect:** Limits persistence of source, prompts, results and mappings
   - **Status:** Production target

9. **Control ID:** NFR-SEC-09
   - **Control area:** Product claims
   - **Product requirement:** Do not display security assurances until controls are active
   - **LLM exposure effect:** Prevents unsupported statements about exposure or protection
   - **Status:** Production target

10. **Control ID:** NFR-SEC-10
   - **Control area:** Local evaluation data
   - **Product requirement:** Do not use real youth records until formal approval
   - **LLM exposure effect:** Current raw Azure OpenAI route remains synthetic/de-identified
     only
   - **Status:** Current mandatory constraint

11. **Control ID:** NFR-SEC-11
   - **Control area:** Governance
   - **Product requirement:** Follow the profiles, controls, management decisions and evidence
     gates in [DATA-SECURITY.md](./DATA-SECURITY.md)
   - **LLM exposure effect:** Centralizes LLM-exposure approval
   - **Status:** Production target

12. **Control ID:** NFR-SEC-12
   - **Control area:** Raw LLM data
   - **Product requirement:** Default to no raw confidential or restricted document content in a
     generative LLM
   - **LLM exposure effect:** Raw LLM exposure prohibited unless `GENAI_RAW_EXCEPTION` is valid
   - **Status:** Proposed production rule

13. **Control ID:** NFR-SEC-13
   - **Control area:** Fail closed
   - **Product requirement:** Stop when the approved route or its control evidence is
     unavailable
   - **LLM exposure effect:** Prevents silent downgrade to a weaker LLM route
   - **Status:** Production target

The proposed production protection chain is summarized below. The complete configuration matrix and manager approval decisions are in [DATA-SECURITY.md](./DATA-SECURITY.md).

1. **Protection point:** Identity and edge
   - **Required technology:** Entra ID, Front Door Premium WAF, API Management
   - **Data handled:** Identity/request metadata; upload traffic transits approved edge/API
     services
   - **Microsoft-managed processing?:** Yes
   - **Exposed to generative LLM?:** No
   - **Product requirement/status:** Only authenticated, authorized and rate-limited requests
     reach the private API — Production target

2. **Protection point:** File intake
   - **Required technology:** Blob quarantine, Defender for Storage, strict validation
   - **Data handled:** Complete uploaded file
   - **Microsoft-managed processing?:** Yes
   - **Exposed to generative LLM?:** No
   - **Product requirement/status:** No unscanned upload reaches extraction or review —
     Production target

3. **Protection point:** Extraction
   - **Required technology:** Private regional Document Intelligence with managed identity
   - **Data handled:** Complete source and extraction result temporarily
   - **Microsoft-managed processing?:** Yes
   - **Exposed to generative LLM?:** No; DI does not automatically call Azure OpenAI
   - **Product requirement/status:** Retrieve only required results and immediately request
     provider deletion — Production target

4. **Protection point:** Data Security Gateway
   - **Required technology:** Backend policy, PII detection, minimization, deterministic
     tokenization, Key Vault/Managed HSM
   - **Data handled:** Raw extracted text inside controlled application boundary
   - **Microsoft-managed processing?:** Azure hosts the application compute; company logic
     controls content
   - **Exposed to generative LLM?:** No; it decides what may be sent
   - **Product requirement/status:** Raw/excess content cannot enter the normal Azure OpenAI
     request; uncertain decisions fail closed — Production target

5. **Protection point:** Generative processing
   - **Required technology:** Dedicated private single-region Azure OpenAI
   - **Data handled:** Normally minimum pseudonymized blocks
   - **Microsoft-managed processing?:** Yes
   - **Exposed to generative LLM?:** **Yes**
   - **Product requirement/status:** Accept only approved-profile requests; raw content requires
     `GENAI_RAW_EXCEPTION` — Open decision/production target

6. **Protection point:** Output assurance
   - **Required technology:** Schema, coverage, token and leakage validators plus assigned human
     review
   - **Data handled:** Model output and authorized restoration data
   - **Microsoft-managed processing?:** Application-controlled
   - **Exposed to generative LLM?:** No additional exposure
   - **Product requirement/status:** Invalid, incomplete or leaky output cannot become approved
     — Production target

7. **Protection point:** Storage and evidence
   - **Required technology:** Private Blob/PostgreSQL, Monitor/Sentinel, retention/deletion
     worker
   - **Data handled:** Approved artifacts and content-free operational metadata
   - **Microsoft-managed processing?:** Yes
   - **Exposed to generative LLM?:** No
   - **Product requirement/status:** Enforce tenant isolation, content-free audit, alerting and
     verifiable deletion — Production target

### Performance targets

These targets are provisional until representative benchmarking:

- **Maximum upload size:** 50 MB by default

- **Maximum page count:** 200 by default

- **Upload acceptance after transfer:** Under 2 seconds at P95

- **Status API:** Under 500 ms at P95

- **Typical workload:** Up to 20 pages

- **Typical processing:** Under 90 seconds P50; under 5 minutes P95

- **Maximum processing timeout:** 20 minutes

- **Monthly API availability:** 99.9%

### Reliability

- Use a durable production queue.
- Make stages idempotent or explicitly versioned.
- Use bounded exponential retries and dead-letter handling.
- Approve RPO and RTO before production.
- Test backup and restore for approved exports and audit records.

### Accessibility

- Target WCAG 2.2 AA.
- Support keyboard operation and visible focus.
- Do not rely only on color for state.
- Implement complete tab semantics.
- Provide extracted text as an accessible alternative to canvas/PDF content.
- Respect reduced-motion preferences.

### Observability and cost

- Record structured, content-free operational logs.
- Measure latency, failures, queue depth, stage duration, dependencies, validation failures, and review rate.
- Correlate API requests and processing attempts without prompt/source content.
- Alert on availability, backlog, failure rate, throttling, storage, and retention failures.
- Attribute page/model usage to organization and processing attempt.
- Enforce quotas before avoidable downstream cost.

## 12. Retention decisions

### Local evaluation baseline

- Synthetic or formally anonymized documents only.
- Delete test documents after the demonstration or test cycle.
- The local baseline is not an approved system of record.

### Production default

- Temporary processing workspace: 30 days.
- Organization-configurable range: 1–90 days, subject to policy and law.
- Authorized earlier deletion where policy permits.
- Approved exports move to the official record system.
- Audit metadata default: one year, without document text.
- Call Azure Document Intelligence result deletion immediately after retrieval, verify it, retry failures, and record content-free evidence. Its documented 24-hour automatic deletion window is a provider maximum, not the product retention period.

These defaults are product decisions, not a claim of legal sufficiency. Records, Legal, Privacy, Security, and the data owner must approve the deployment-specific schedule, including caches, queues, soft delete, versions, backups, disaster-recovery copies, and legal holds.

## 13. Success measures

- 100% source page-count preservation for supported benchmark documents.
- 100% block/cell ID and order preservation through translation.
- Zero table-cell duplication in paragraph results.
- 100% canonical JSON schema validation.
- 100% protected-token preservation in accepted results.
- Zero accepted results with missing, duplicate, or reordered IDs.
- Human correction rate by language, document type, OCR quality, and version.
- Processing success/failure rate and P50/P95 duration by stage.
- Retry success rate by mode.
- Time from upload to human approval.
- Accessibility and usability completion results.

## 14. Benchmark dataset

Maintain synthetic approved fixtures for:

- Clear/degraded scans across every proposed production source language.
- Arabic and right-to-left text; Simplified and Traditional Chinese; Latin, Cyrillic, and Indic-script fixtures.
- Mixed-language text, English pass-through, numeric-only content, invalid tags, and unknown-language review routing.
- Tables, headers, merged cells, and multi-page tables.
- Rotation, unusual page sizes, handwriting, and low confidence.
- Multi-page PDF/TIFF and PNG/JPEG/BMP preview.
- Empty, mismatched, oversized, and password-protected files.
- Prompt-injection instructions inside source text.
- Names, dates, numbers, codes, URLs, emails, and Unicode numerals.
- Azure throttling, timeout, refusal, malformed output, and partial failure.

No real youth record may enter the shared test suite.

## 15. Risks

1. **Risk:** Incorrect translation affects a decision
   - **Current mitigation:** Review flags and source comparison
   - **Production requirement:** Approval workflow, evaluation, clear notices, qualified review

2. **Risk:** Low OCR quality
   - **Current mitigation:** Block confidence threshold
   - **Production requirement:** Table confidence, quality rules, review queue

3. **Risk:** Prompt injection
   - **Current mitigation:** Source labelled untrusted
   - **Production requirement:** Adversarial tests and constrained output

4. **Risk:** PII exposure
   - **Current mitigation:** Backend keys and ignored runtime data
   - **Production requirement:** Auth/RBAC, private persistence/network, retention, audit,
     incident response

5. **Risk:** Raw content reaches a generative LLM without approval
   - **Current mitigation:** Local-baseline synthetic-only restriction
   - **Production requirement:** Default-deny policy engine, egress allowlist, profile-negative
     tests, alerts

6. **Risk:** Incorrect region or deployment type
   - **Current mitigation:** Manually configured Azure resources
   - **Production requirement:** IaC allowlist, Azure Policy, private endpoints, captured
     deployment evidence, drift alerting

7. **Risk:** Provider result is retained unnecessarily
   - **Current mitigation:** Automatic provider expiry
   - **Production requirement:** Immediate delete request, retry queue, aging alert, deletion
     evidence

8. **Risk:** Pseudonymization misses multilingual identifiers
   - **Current mitigation:** Not implemented
   - **Production requirement:** Approved multilingual benchmark, confidence threshold,
     independent review, fail closed

9. **Risk:** Policy fallback or downgrade
   - **Current mitigation:** Not implemented
   - **Production requirement:** Immutable backend selection, no implicit fallback,
     authorization and chaos tests

10. **Risk:** Duplicate table output
   - **Current mitigation:** Backend/UI deduplication
   - **Production requirement:** Broader regression suite

11. **Risk:** Worker/data loss
   - **Current mitigation:** Local restart recovery
   - **Production requirement:** Durable queue, leases, idempotency, managed persistence

12. **Risk:** Misleading assurance
   - **Current mitigation:** README local-evaluation boundary
   - **Production requirement:** Live status and approved UI language

13. **Risk:** Dependency vulnerability
   - **Current mitigation:** Manual review
   - **Production requirement:** Automated scanning, upgrade SLA, CI gates

## 16. Release gates

### Local evaluation baseline

- Synthetic demo works without credentials.
- Configured backend/frontend quality checks pass.
- No secrets or runtime documents are tracked.
- Current limitations are documented.
- Real youth records remain prohibited.

### Controlled pilot

- Authentication and backend authorization.
- Approved test/anonymized data unless formally approved otherwise.
- Malware scanning, rate limits, managed secrets, monitoring, and audit.
- Durable production-like storage and queue.
- Defined support, incident, retention, and deletion processes.
- Security, privacy, accessibility, and dependency reviews completed.
- Approved processing profile, provider, region, contract, data-flow assessment, and deployment-specific security plan.
- A proven `GENAI_PSEUDONYMIZED` route, Data Security Gateway leakage evidence, hardened Azure OpenAI configuration, and immediate Document Intelligence result-deletion evidence before any Azure OpenAI-enabled confidential-record pilot.
- A proven `MANAGED_NO_LLM` route before piloting classifications that prohibit generative AI.
- No raw confidential/restricted Azure OpenAI route unless a separately approved `GENAI_RAW_EXCEPTION` meets every gate in `DATA-SECURITY.md`.

### Production

- Jurisdiction and lawful use approved.
- Real-record use explicitly approved.
- Target architecture implemented and threat-modelled.
- RBAC, tenant isolation, encryption, private access, retention, deletion, audit, backup, and recovery verified.
- Human correction and approval workflow implemented.
- Performance, reliability, security, accessibility, and quality targets met with evidence.
- Runbook, ownership, and incident response approved.
- Processing-profile enforcement, egress denial, service-region restrictions, provider deletion, content-free telemetry, and kill-switch behavior independently verified.

## 17. Roadmap

### Phase 1 — Stabilize the local evaluation baseline

- Make all quality checks green and add CI.
- Upgrade affected dependencies.
- Implement image preview or temporarily narrow the UI promise.
- Replace static connected/secure indicators with actual state.
- Clarify retry behavior and expose extracted export.
- Add API, storage, worker, security-negative, and interactive frontend tests.

### Phase 2 — Production foundation

- Entra authentication and backend authorization.
- Organization and role model.
- Azure Container Apps API and worker.
- Service Bus, Blob Storage, PostgreSQL, Key Vault, and managed identity.
- Malware scanning, rate limits, audit, monitoring, and retention worker.
- CI/CD, infrastructure as code, dependency scanning, and promotion controls.
- Server-side classification and policy gateway with immutable decision evidence.
- Data Security Gateway with minimization, multilingual PII detection, deterministic tokenization, separately protected mappings, leakage validation, and fail-closed policy enforcement.
- A dedicated private single-region Azure OpenAI adapter for `GENAI_PSEUDONYMIZED`, with managed identity, verified modified abuse-monitoring status, stateless APIs, prohibited-feature controls, and a kill switch.
- Regional/private Document Intelligence and Azure AI Translator adapters for `MANAGED_NO_LLM`.
- Immediate Document Intelligence result deletion, private endpoints, egress controls, and Azure Policy deny rules.
- A container proof of capability for `RESTRICTED_LOCAL` when required by customer policy.

### Phase 3 — Review and governance

- Corrections, comments, version history, approval, and rejection.
- Review queues and assignment.
- Bilingual PDF, DOCX, table exports, and audit manifest.
- Approved retention, legal-hold, and deletion workflows.

### Phase 4 — Production validation

- Translation/OCR benchmark.
- Threat-model closure and security testing.
- Accessibility conformance review.
- Load, resilience, backup, and disaster-recovery testing.
- Controlled pilot and production approval.

## 18. Approved decisions

1. Documentation covers the implemented local baseline and production roadmap.
2. Production roles are caseworker, translation reviewer, organization administrator, compliance auditor, and platform operator.
3. Real youth records are prohibited in the local baseline.
4. Jurisdiction is deployment-specific and a production release blocker.
5. English is the only target language; production-enabled source languages are controlled by approved language/document-family benchmark gates, not by a hard-coded application allowlist.
6. Every advertised format must ultimately have reliable preview.
7. Workspace retention defaults to 30 days with an approved 1–90 day range.
8. Retry modes are Resume, Retranslate, and Reprocess completely.
9. Production includes correction and approval with immutable history.
10. Target backend hosting is Azure Container Apps with separate API and worker.
11. Initial limits are 50 MB and 200 pages, subject to benchmarking.
12. Production exports include JSON, bilingual PDF, DOCX, table CSV/XLSX, and an audit manifest.

## 19. Organization-level decisions still required

- Named product, technical, security, privacy, and operations owners.
- Deploying organization, jurisdiction, lawful basis, consent, safeguarding, residency, and data-subject policy.
- Approved Azure region and deployment types.
- Whether Microsoft-managed regional Document Intelligence and Translator processing is permitted for each classification and jurisdiction.

### 19.1 Financial-only extraction increment

#### Implemented local capability

- Generate a page-level financial classification manifest for every enabled document.
- Preserve original source page numbers, geometry, table coordinates, raw values, normalized values, processing provenance, and ordered semantic formats for financial headings, paragraphs, key-values, list items, and tables.
- Normalize financial amounts with decimal arithmetic and flag ambiguous separators.
- Validate selected pages without financial content, duplicate cell coordinates, ambiguous numeric formats, and mixed explicit currencies.
- Translate financial content present on selected financial/uncertain pages from any valid detected non-English language tag; numeric-only cells remain unchanged and unknown language is review-required.
- Present an ordered source/English financial document view plus Financial, Review, and All page modes; export financial JSON, formula-safe CSV, and XLSX.

#### Production acceptance requirements

1. `selective` mode MUST use a versioned, approved Azure Document Intelligence custom classifier and MUST fail closed when its ID or policy approval is unavailable.
2. Unknown or low-confidence pages MUST be selected for extraction and review; precision optimization MUST NOT silently reduce the approved recall threshold.
3. The release corpus MUST include representative synthetic/de-identified 100–200-page PDFs, scanned pages, mixed document bundles, continuation tables, ambiguous units, and multilingual labels.
4. Page-recall, table/cell accuracy, numeric-preservation, latency, and cost gates MUST be approved per supported document family before production use.
5. `post_extract` is a full-layout evaluation fallback and MUST NOT be represented as cost-selective extraction.
6. Financial reviewer corrections and approvals are partially implemented as append-only records bound to the exact processing version and result hash. Entra identity, object authorization, assignment, reviewed-export materialization, and production audit evidence remain P2/P3 targets.

#### P0/P1 implementation acceptance

- Locale-safe amount parsing never emits a normalized guess for ambiguous single-separator values.
- Only ambiguous monetary values are normalization-review blockers; measurements, percentage
  ranges, phone numbers, dates, account numbers, identifiers, and quantities remain source data.
- The approval API rejects corrections for cells that are not explicitly marked as correctable
  monetary values.
- Spreadsheet formula neutralization applies to raw and normalized values.
- Financial evidence above the include threshold cannot be suppressed by competing non-financial evidence.
- Empty selection completes with valid empty financial artifacts and exports.
- Reprocess invalidates the manifest before deleting every derived artifact family.
- Resume, Retranslate, and Reprocess are all prohibited after financial approval; unapproved
  retries adopt the current persisted processing contract.
- Provider tables remain atomic across page-selection boundaries.
- Provider extraction remains immutable; a separate `table-reconciliation-1.0` artifact records
  every reconstructed candidate, source block, evidence score, policy fingerprint, and proposed
  dimension change.
- Reconstructed cells retain source block IDs and geometry, are visually distinguished, and
  keep the result in review until the active candidate is explicitly accepted or rejected.
- The shared yen/yuan symbol uses explicit page currency evidence when available and otherwise
  remains currency-ambiguous; it is never silently labeled JPY or CNY.
- Financial review history is append-only and bound to the active result SHA-256.
- Financial approval cannot clear an independent OCR or translation review requirement.
- The ordered financial content stream preserves headings, paragraphs, key-values, list items, and provider table grids in source reading order.
- Non-financial narrative blocks are excluded deterministically; the nearest preceding heading is retained only as context for a financial signal or table.
- The source view never replaces source text with a normalized value; normalization is shown as separate derived provenance.
- Legacy `financial-result-1.1` table-only artifacts remain readable, while reprocessing emits `financial-result-1.4`.

Detailed contracts and diagrams: [FINANCIAL-EXTRACTION.md](./FINANCIAL-EXTRACTION.md).

### 19.2 Remaining organization decisions

- Approval of the proposed default: no raw confidential or restricted content to a generative LLM.
- Approval of `GENAI_PSEUDONYMIZED` as the normal Azure OpenAI-enabled route and the exact data classes/jurisdictions permitted to use it.
- Whether a `GENAI_RAW_EXCEPTION` may ever exist and, if so, who can approve it and which narrowly defined purposes can qualify.
- Whether modified abuse monitoring is mandatory for all sensitive production Azure OpenAI profiles; this plan recommends that it is.
- Whether connected or disconnected processing containers are required and who funds and operates them.
- Final retention, audit retention, legal hold, and deletion policy.
- Support hours, incident severity, RPO, and RTO.
- Case-record-system integration.
- Any separate certified-translation process.

## 20. References

- Project root `README.md`
- [Architecture](./ARCHITECTURE.md)
- [Data security and AI processing plan](./DATA-SECURITY.md)
- [Rules](./RULES.md)
- [Memory](./MEMORY.md)
- [Azure Document Intelligence limits](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits?view=doc-intel-4.0.0)
- [Azure Document Intelligence data, privacy, and security](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/document-intelligence/data-privacy-security)
- [Azure OpenAI data, privacy, and security](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/openai/data-privacy)
- [Azure OpenAI structured outputs](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/structured-outputs)
