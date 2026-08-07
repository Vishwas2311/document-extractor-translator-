# CareTranslate Studio frontend

The browser review workspace for the CareTranslate Studio production-oriented local evaluation
baseline. It runs in a complete synthetic demo mode without credentials and connects to the
Python API through a same-origin server proxy. `NEXT_PUBLIC_API_BASE_URL` contains only the
browser-safe proxy path; `BACKEND_API_BASE_URL` and `API_AUTH_TOKEN` remain server-only.

From this directory:

    Copy-Item .env.local.example .env.local
    npm ci
    npm run dev

Open http://localhost:3000. Azure keys belong only in backend/.env.

Security boundary:

1. **Browser security rule:** The frontend is not an authorization or data-classification
   boundary; the production backend enforces both
   - **Data/LLM effect:** Browser controls cannot authorize or downgrade an Azure OpenAI route
   - **Status:** Production target

2. **Browser security rule:** Use only synthetic or explicitly approved de-identified data in
   the current local evaluation baseline
   - **Data/LLM effect:** Current raw extracted text may reach Azure OpenAI
   - **Status:** Current mandatory constraint

3. **Browser security rule:** Never place Azure credentials, document content, prompts or
   pseudonym mappings in `NEXT_PUBLIC_*`, analytics, session replay, URLs or client error
   reporting
   - **Data/LLM effect:** Prevents browser/telemetry copies and direct provider access
   - **Status:** Mandatory

4. **Browser security rule:** Serve sensitive responses with explicit no-store behavior and
   approved telemetry
   - **Data/LLM effect:** Limits local/browser retention; does not itself change the model route
   - **Status:** Production target

The proposed production browser boundary is:

1. **Protection boundary:** Entra ID session
   - **Data handled in browser:** Identity token/session metadata
   - **Exposed to generative LLM by this boundary?:** No
   - **Frontend responsibility:** Obtain the approved user token, protect session state and
     never infer authorization from visible controls
   - **Status:** Production target

2. **Protection boundary:** Front Door WAF + API Management
   - **Data handled in browser:** Upload traffic and request metadata
   - **Exposed to generative LLM by this boundary?:** No
   - **Frontend responsibility:** Call only the approved API origin; do not bypass edge/token
     controls or embed provider endpoints
   - **Status:** Production target

3. **Protection boundary:** Backend policy/Data Security Gateway
   - **Data handled in browser:** Profile/status returned to the browser
   - **Exposed to generative LLM by this boundary?:** No; backend controls any later handoff
   - **Frontend responsibility:** Display the server-selected profile/blocked state; never
     select, downgrade, tokenize or approve a provider route in browser code
   - **Status:** Production target

4. **Protection boundary:** Azure OpenAI
   - **Data handled in browser:** No direct browser data flow is permitted
   - **Exposed to generative LLM by this boundary?:** Browser must never expose content directly
     to the LLM
   - **Frontend responsibility:** Never call Azure OpenAI directly; the backend normally sends
     only approved minimized/pseudonymized blocks
   - **Status:** Mandatory production boundary

5. **Protection boundary:** Review and download
   - **Data handled in browser:** Authorized page images, source text and results
   - **Exposed to generative LLM by this boundary?:** No additional exposure
   - **Frontend responsibility:** Enforce no-store, clear view state where feasible, use
     short-lived server-authorized downloads and show machine output as unapproved
   - **Status:** Production target

6. **Protection boundary:** Telemetry
   - **Data handled in browser:** Approved content-free interaction metadata
   - **Exposed to generative LLM by this boundary?:** No
   - **Frontend responsibility:** Exclude page images, source text, translations, tokens,
     filenames and identifiers unless explicitly approved
   - **Status:** Mandatory

Useful checks:

    npm run lint
    npm run build
    npm test

See ../README.md for setup and API workflow, and ../docs/DATA-SECURITY.md for the readable production diagram, service-protection matrix, security profiles and approval gates.
