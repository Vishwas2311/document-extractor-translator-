# Multilingual Translation Studio — Backend Architecture

- **Offer:** Backend / API platform only (customers bring their own UI)  
- **Style:** Enterprise solution architecture (Credit Memo Connect–class board)  
- **Visual:** [multilingual-translator-studio-backend-architecture.png](./multilingual-translator-studio-backend-architecture.png)

> **SA - Multilingual Translation Studio (Backend)** — full production Azure backend. Cream = new application components · Gray = existing / shared platform.

---

## 1. Board layout (how to read it)

| Zone | Contents |
|---|---|
| **Ingress** | API consumers → F5 → Azure Application Gateway |
| **MTS Backend Environment (CAT 3)** | NS1 API services · NS2 Orchestrator & processing · NS3 Workers & agents |
| **AI Hub (CAT 1)** | Reached via APIM + App Gateway — Document Intelligence, Azure OpenAI, Translator |
| **Data Storage Layer** | Service Bus · Blob · Postgres · Redis · AI Search · **CMK encryption** |
| **Identity** | Entra ID · Enterprise IDP / identity governance |
| **Platform row** | Key Vault · Entra · Monitor · Log Analytics/ELK · CI/CD · Artifact repo |

---

## 2. Namespaces (new application components)

### NS1 — API Gateway Services
- FastAPI `/api/v1`
- Upload, job status, pages, cancel/retry, artifact download
- JWT validation at the edge of the service

### NS2 — Orchestrator & Processing
- Central orchestrator (intake → extract → gateway → translate → export)
- Data Security Gateway + profile/rule library
- Profiles: `GENAI_PSEUDONYMIZED` · `MANAGED_NO_LLM` · `RESTRICTED_LOCAL` · `HUMAN_ONLY` · `BLOCKED`
- Inter-service JWT

### NS3 — Workers & Agents
- Page-range Document Intelligence worker
- Translation batch worker
- Retention / cleanup worker
- Prompt library + pseudonymization token service

---

## 3. AI Hub (CAT 1) — via APIM

| Service | Role |
|---|---|
| **Azure Document Intelligence 4.0** | Layout / OCR / languages / polygons |
| **Azure OpenAI** | Structured translation (approved minimized blocks) |
| **Azure AI Translator** | Non-LLM translation route |

Backend never exposes AI keys to consumers; all AI calls stay server-side through APIM + private networking.

---

## 4. Data Storage Layer

| Store | Use |
|---|---|
| **Service Bus** | Durable jobs, locks, DLQ, retries |
| **Blob Storage** | Quarantine, source, pages, exports, manifest |
| **Postgres** | Documents, jobs, leases, audit metadata |
| **Redis** | Hot status / session-less cache / rate assists |
| **AI Search** | Optional semantic/index retrieval |
| **CMK** | Server-side encryption with customer-managed keys |

---

## 5. Sellable API surface (no UI included)

| Capability | Endpoint family |
|---|---|
| Intake | `POST /documents` |
| Lifecycle | status · cancel · retry (`resume` / `retranslate` / `reprocess`) |
| Results | pages · page JSON · bilingual export · downloads |
| Auth | Entra + APIM product subscriptions |

Customers integrate their own front-end, mobile app, or BFF.

---

## 6. Mermaid (same topology)

```mermaid
flowchart TB
  Consumers["API Consumers"] --> F5["F5"] --> AGW["App Gateway"]
  AGW --> NS1["NS1 API Gateway Services"]
  NS1 --> NS2["NS2 Orchestrator & Processing"]
  NS2 --> NS3["NS3 Workers & Agents"]

  NS2 --> APIM["APIM"] --> AGW2["App Gateway"] --> AIHub["AI Hub CAT1<br/>DI · OpenAI · Translator"]

  NS1 --> Data["Data Storage Layer<br/>Service Bus · Blob · Postgres · Redis · AI Search · CMK"]
  NS2 --> Data
  NS3 --> Data

  Entra["AZ Entra ID"] -.-> AGW
  Entra -.-> APIM
```

---

## 7. Files

| File | Purpose |
|---|---|
| [Multilingual-Translation-Studio-Backend-Architecture.pptx](./Multilingual-Translation-Studio-Backend-Architecture.pptx) | **Editable PowerPoint** — Slide 1 polished board image · Slide 2 Azure-icon map · Slide 3 notes |
| [Multilingual-Translation-Studio-Backend-Architecture.drawio](./Multilingual-Translation-Studio-Backend-Architecture.drawio) | **Editable draw.io** (open in [diagrams.net](https://app.diagrams.net)) |
| [multilingual-translator-studio-backend-architecture.png](./multilingual-translator-studio-backend-architecture.png) | Static PNG board |
| `icons/png/*.png` | Official Azure architecture icons used in the PPT |

Regenerate:

```powershell
node scripts\convert_azure_icons.js
backend\.venv\Scripts\python.exe scripts\generate_backend_architecture_pptx.py
```
