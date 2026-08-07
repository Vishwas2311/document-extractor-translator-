const { Resvg } = require("../frontend/node_modules/@resvg/resvg-js");
const fs = require("fs");
const path = require("path");

const root = path.resolve(
  __dirname,
  "../docs/diagrams/icons/azure/Azure_Public_Service_Icons/Icons",
);
const outdir = path.resolve(__dirname, "../docs/diagrams/icons/png");
fs.mkdirSync(outdir, { recursive: true });

const mapping = {
  "app-gateway": "networking/10076-icon-service-Application-Gateways.svg",
  apim: "integration/10042-icon-service-API-Management-Services.svg",
  "service-bus": "integration/10836-icon-service-Azure-Service-Bus.svg",
  blob: "storage/10086-icon-service-Storage-Accounts.svg",
  "key-vault": "security/10245-icon-service-Key-Vaults.svg",
  monitor: "management + governance/00001-icon-service-Monitor.svg",
  aks: "compute/10023-icon-service-Kubernetes-Services.svg",
  postgres: "databases/10131-icon-service-Azure-Database-PostgreSQL-Server.svg",
  redis: "databases/10137-icon-service-Cache-Redis.svg",
  search: "ai + machine learning/10044-icon-service-Cognitive-Search.svg",
  openai: "ai + machine learning/03438-icon-service-Azure-OpenAI.svg",
  translator: "ai + machine learning/00800-icon-service-Translator-Text.svg",
  "doc-intel": "ai + machine learning/00819-icon-service-Form-Recognizers.svg",
  entra: "identity/10230-icon-service-Users.svg",
  "identity-gov": "identity/10235-icon-service-Identity-Governance.svg",
};

const ok = [];
const missing = [];
for (const [name, rel] of Object.entries(mapping)) {
  const svgPath = path.join(root, rel);
  if (!fs.existsSync(svgPath)) {
    missing.push(`${name}:${rel}`);
    continue;
  }
  const svg = fs.readFileSync(svgPath);
  const resvg = new Resvg(svg, { fitTo: { mode: "width", value: 128 } });
  fs.writeFileSync(path.join(outdir, `${name}.png`), resvg.render().asPng());
  ok.push(name);
}
console.log("ok", ok.join(","));
if (missing.length) console.log("missing", missing.join(" | "));
