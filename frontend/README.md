# CareTranslate Studio frontend

The browser review workspace for the CareTranslate Studio POC. It runs in a complete demo mode without credentials and connects to the Python API when NEXT_PUBLIC_API_BASE_URL is configured.

From this directory:

    Copy-Item .env.local.example .env.local
    npm ci
    npm run dev

Open http://localhost:3000. Azure keys belong only in backend/.env.

Useful checks:

    npm run lint
    npm run build
    npm test

See ../README.md for the full architecture, Azure configuration, and API workflow.
