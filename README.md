# CareTranslate Studio

A runnable proof of concept for youth-care teams to upload Arabic or Mandarin PDFs/images, extract document structure with Azure Document Intelligence, translate non-English content with Azure OpenAI GPT-5-mini, and review page-wise English JSON in a studio-style interface.

The app opens in a complete three-page demo, so the UI can be evaluated before Azure credentials are added.

## What is included

- Python 3.12 FastAPI backend with async SQLAlchemy and SQLite
- Azure Document Intelligence prebuilt-layout extraction with language detection and bounding polygons
- Azure OpenAI GPT-5-mini translation through the Azure v1 API and Structured Outputs
- Deterministic block IDs, protected-token validation, retries, and review flags
- One JSON artifact per page plus extracted and bilingual document exports
- Next.js/TypeScript review studio with thumbnails, zoom, rotation, selectable overlays, and synchronized result cards
- Extracted, Translated, and page-wise JSON tabs
- PDF.js rendering for real documents and a no-credentials demo mode
- Alembic migration, local file storage, Docker API option, tests, and PowerShell setup/run scripts

## Architecture


```text
Upload → Validate and store → Azure Document Intelligence → Normalize page/block geometry → Detect language → Batch non-English blocks → Azure OpenAI GPT-5-mini → Validate IDs and protected tokens → Write page JSON/exports → Review in Studio
```

Azure credentials are used only by the Python backend. They are never sent to the browser.

## Prerequisites

- Windows PowerShell 5.1 or PowerShell 7
- Python 3.12
- Node.js 22.13 or newer
- An Azure Document Intelligence resource
- An Azure OpenAI resource with a GPT-5-mini deployment

## Quick start

From the project root:


```text
PowerShell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

Edit backend/.env and enter the Azure values described below. Then start both services:


```text
PowerShell -ExecutionPolicy Bypass -File .\scripts\run-poc.ps1
```

Open:

- Studio: http://localhost:3000
- API documentation: http://localhost:8000/docs
- API readiness: http://localhost:8000/api/v1/health/ready

If Azure values are still empty, the Studio demo remains fully usable and the readiness endpoint reports both Azure dependencies as unconfigured.

## Azure configuration

Copy backend/.env.example to backend/.env if the setup script has not already done so.

Required Azure Document Intelligence values:


```text
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://YOUR-DOCUMENT-INTELLIGENCE-RESOURCE.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_API_KEY=YOUR_KEY
AZURE_DOCUMENT_INTELLIGENCE_MODEL_ID=prebuilt-layout
```

Required Azure OpenAI values:


```text
AZURE_OPENAI_BASE_URL=https://YOUR-AZURE-OPENAI-RESOURCE.openai.azure.com/openai/v1/
AZURE_OPENAI_API_KEY=YOUR_KEY
AZURE_OPENAI_DEPLOYMENT=YOUR_GPT_5_MINI_DEPLOYMENT_NAME
AZURE_OPENAI_REASONING_EFFORT=minimal
```

Important: AZURE_OPENAI_DEPLOYMENT is the deployment name created in Azure, not necessarily the catalog model name.

The frontend only needs this browser-safe value in frontend/.env.local:


```text
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
```

Never place either Azure key in frontend/.env.local or any NEXT_PUBLIC variable.

## Run services separately

Backend:


```text
PowerShell -ExecutionPolicy Bypass -File .\scripts\start-backend.ps1
```

Frontend:


```text
PowerShell -ExecutionPolicy Bypass -File .\scripts\start-frontend.ps1
```

## Docker API option

After creating backend/.env:


```text
docker compose up --build api
```

The frontend is still started with scripts/start-frontend.ps1. Runtime database and artifacts are written to data/ and storage/ on the host.

## Processing flow

1. Upload accepts PDF, PNG, JPEG, TIFF, or BMP and checks both extension and file signature.
2. The original file is stored under storage/documents/<document-id>/source.
3. Azure Document Intelligence prebuilt-layout returns pages, paragraphs, words, tables, languages, spans, and polygons.
4. The mapper creates deterministic block IDs and page-aware geometry.
5. English blocks are retained; Arabic, Simplified/Traditional Chinese, and mixed blocks are batched for translation.
6. GPT-5-mini returns a strict structured response keyed by the original block IDs.
7. Validation checks exact IDs/order, empty translations, and protected values such as dates, case codes, URLs, email addresses, and numbers.
8. The backend writes one canonical JSON file per page plus extracted and bilingual exports.
9. The Studio loads the source document, renders its overlays, and synchronizes selection with the result panel.

## Page-wise JSON

Each completed page is available at:


```text
GET /api/v1/documents/{document_id}/pages/{page_number}
```

Example shape:


```text
{
  "schema_version": "1.0",
  "document_id": "...",
  "document_status": "completed",
  "page": {
    "page_number": 1,
    "page_count": 3,
    "width": 8.5,
    "height": 11,
    "unit": "inch",
    "source_text": "...",
    "translated_text": "..."
  },
  "blocks": [
    {
      "block_id": "b000001",
      "reading_order": 1,
      "source_text": "...",
      "source_language": "ar",
      "translated_text": "...",
      "translation_status": "translated",
      "bounding_regions": [
        { "page_number": 1, "polygon": [{ "x": 1.0, "y": 1.2 }] }
      ],
      "ocr_confidence": 0.97,
      "review_required": false
    }
  ],
  "tables": [],
  "warnings": []
}
```

Downloads:

- GET /api/v1/documents/{id}/downloads/page?page=1
- GET /api/v1/documents/{id}/downloads/extracted
- GET /api/v1/documents/{id}/downloads/bilingual

## Main API routes

- POST /api/v1/documents — upload and queue a document
- GET /api/v1/documents/{id} — status and document metadata
- GET /api/v1/documents/{id}/source — inline original document
- GET /api/v1/documents/{id}/pages — page summaries
- GET /api/v1/documents/{id}/pages/{page} — canonical page JSON
- POST /api/v1/documents/{id}/retry — retry failed or reviewable work
- DELETE /api/v1/documents/{id} — delete a terminal document and its artifacts
- GET /api/v1/health/ready — service and Azure configuration readiness

## Verification

Backend:


```text
cd backend
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Frontend:


```text
cd frontend
npm run lint
npm run build
```

## POC boundaries

This POC deliberately uses SQLite, local artifact storage, and an in-process worker. Before production use with youth-care or other sensitive records, add organization authentication and role-based access, Azure Blob Storage, a durable queue/worker, Key Vault or managed identity, private networking, malware scanning, retention/deletion policy, encryption controls, audit logging, monitoring, human-review workflow, and a formal privacy/security assessment. Do not use real personal or clinical data until those controls are approved.
