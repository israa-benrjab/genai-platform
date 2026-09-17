# GenAI Platform 🚀

> A production-style GenAI platform running on Azure + Kubernetes with a complete GitOps CI/CD pipeline. Local + cloud LLM inference, RAG over uploaded documents, per-user isolation, RBAC, and full observability.

![Backend CI/CD](https://github.com/israa-benrjab/genai-platform/actions/workflows/backend-ci.yaml/badge.svg)
![Argo CD](https://img.shields.io/badge/ArgoCD-Synced-success)
![Kubernetes](https://img.shields.io/badge/Kubernetes-1.37-326CE5?logo=kubernetes&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![Azure](https://img.shields.io/badge/Azure-Cloud-0078D4?logo=microsoftazure&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

---

## 📋 Table of Contents

- [Why This Project](#-why-this-project)
- [At a Glance](#-at-a-glance)
- [Overview](#-overview)
- [Architecture](#️-architecture)
- [Tech Stack](#️-tech-stack)
- [Quick Start](#-quick-start)
- [API Endpoints](#-api-endpoints)
- [CI/CD Pipeline](#-cicd-pipeline)
- [Observability](#-observability)
- [Performance](#-performance)
- [Azure Container Registry](#️-azure-container-registry-acr)
- [Azure Blob Storage](#-azure-blob-storage)
- [Security (Defense in Depth)](#-security-defense-in-depth)
- [Cost Breakdown](#-cost-breakdown)
- [Project Structure](#-project-structure)
- [Testing](#-testing)
- [Troubleshooting](#-troubleshooting)
- [Lessons Learned](#-lessons-learned)
- [FAQ](#-faq)
- [Roadmap](#️-roadmap)
- [Contributing](#-contributing)
- [Author](#-author)
- [License](#-license)

---

## 🎯 Why This Project

Most "GenAI demo" repos stop at a Jupyter notebook calling an API. This one goes further: it answers the question "what does it actually take to run an LLM-powered service in production?"

That means real infrastructure decisions — CPU-only inference when there's no GPU budget, per-user data isolation instead of a shared vector store, RBAC instead of a single API key, GitOps instead of manual `kubectl apply`, and a defense-in-depth security posture instead of "it's just a demo." It also means real production-shaped failures — a crashed control plane, a leaked secret, a broken Helm chart — diagnosed and fixed the way they'd be fixed on a real team.

---

## 📊 At a Glance

| Metric | Value |
|---|---|
| Endpoints | 25+ REST endpoints |
| Namespaces | 5 (`backend`, `ai`, `data`, `monitoring`, `argocd`) |
| Roles | 3 (admin / analyst / user) with enforced RBAC |
| Inference | Local (Llama 3.2 1B, CPU) + Cloud (Groq gpt-oss-20b) |
| CI/CD | `git push` → live pod in under 5 minutes |
| Security layers | 4 (cloud, cluster, application, supply chain) |
| Dashboard panels | 16 (Grafana, live Prometheus data) |
| Infra as code | 100% — every resource defined in YAML, applied via GitOps |

---

## 📖 Overview

This project is a full-stack GenAI platform deployed on a Kubernetes cluster running on an Azure VM. It provides:

- 25+ REST endpoints for document intelligence, RAG chat, summarization, translation, classification, and report generation
- Hybrid LLM inference — local Llama 3.2 for privacy, Groq API for high-throughput
- Role-based access control with 3 roles (admin / analyst / user)
- Per-user document isolation with Qdrant vector search
- Full observability with Prometheus, Grafana, and Loki
- GitOps CI/CD — every commit triggers build → scan → push → auto-deploy
- Defense-in-depth security across cloud, cluster, application, and supply chain layers

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Developer                                │
│                              │                                    │
│                              ├──► git push origin main            │
│                              ▼                                    │
│                       GitHub Actions                              │
│                              ├──► docker build                    │
│                              ├──► trivy scan                      │
│                              ├──► push to Azure Container Registry│
│                              └──► auto-commit new image tag       │
│                                   to k8s/backend.yaml              │
│                              ▼                                    │
│                       Argo CD (watches repo)                      │
│                              └──► auto-sync → zero-downtime       │
│                                   rollout                          │
│                              ▼                                    │
│              Kubernetes (Minikube on Azure VM)                    │
│              ├── backend/     FastAPI + JWT + RBAC                │
│              ├── ai/          llama.cpp (Llama 3.2 1B) + Groq     │
│              ├── data/        Qdrant vector DB                    │
│              ├── monitoring/  Prometheus + Grafana + Loki         │
│              └── argocd/      GitOps controller                   │
│                              ▼                                    │
│               User request → FastAPI → LLM → response             │
│                                                                     │
│  Side channels:                                                   │
│    Azure Blob Storage      ◄── raw uploaded documents             │
│    Azure Container Registry ◄── backend images                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

**Cloud & Infrastructure**
- Azure VM — Standard_D4s_v3 (4 vCPU / 16 GB RAM), Ubuntu 24.04, France Central
- Azure Container Registry — `genaiplatform2026.azurecr.io`
- Azure Blob Storage — durable archive for uploaded documents
- 128 GB data disk mounted at `/data` for model storage

**Orchestration**
- Kubernetes 1.37 via Minikube (Docker driver)
- 5 namespaces — `backend`, `ai`, `data`, `monitoring`, `argocd`
- Kubernetes NetworkPolicies — default-deny with explicit allow rules

**Backend**
- FastAPI + Python 3.11 + Pydantic
- Uvicorn ASGI server on port 8001
- JWT authentication via python-jose
- Prometheus instrumentation via prometheus-fastapi-instrumentator

**AI / ML**
- llama-cpp-python — serving Llama 3.2 1B GGUF (CPU-only, no GPU)
- Groq API — cloud fallback (`openai/gpt-oss-20b`)
- Smart model routing — sensitive work → local, high-throughput → cloud
- SentenceTransformers — BAAI/bge-small-en-v1.5 (384-dim)
- Qdrant — vector DB for RAG

**File Parsing**
- pypdf, python-docx, python-pptx, pandas, Pillow

**Observability**
- Prometheus — metrics collection with custom scrape config
- Grafana — 16-panel executive dashboard
- Loki + Promtail — centralized log aggregation
- Trivy — container image vulnerability scanning
- Falco — eBPF-based runtime threat detection

**CI/CD**
- GitHub Actions — build, scan, push, update manifest
- Argo CD — GitOps continuous delivery

---

## 🚀 Quick Start

### Prerequisites
- Azure subscription (or any cloud VM with 16 GB RAM)
- Docker
- Minikube + kubectl
- Helm
- GitHub account with Actions enabled
- ACR registry

### 1. Provision the VM
```bash
az vm create \
  --resource-group myCloudProject \
  --name genai-vm \
  --image Ubuntu2404 \
  --size Standard_D4s_v3 \
  --admin-username genai \
  --generate-ssh-keys

az vm disk attach \
  --resource-group myCloudProject \
  --vm-name genai-vm \
  --name genai-vm-data \
  --size-gb 128 \
  --new
```

### 2. Set up the environment
```bash
sudo mkfs.ext4 /dev/sdc
sudo mkdir -p /data
sudo mount /dev/sdc /data
echo '/dev/sdc /data ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab

sudo apt-get update
sudo apt-get install -y docker.io
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/kubectl
```

### 3. Start Minikube
```bash
minikube start --driver=docker --cpus=2 --memory=6144

kubectl create namespace backend
kubectl create namespace ai
kubectl create namespace data
kubectl create namespace monitoring
kubectl create namespace argocd
```

### 4. Copy the LLM model
```bash
mkdir -p /data/models
# Download Llama 3.2 1B GGUF (~771MB) from Hugging Face
minikube cp /data/models/llama3.2-1b.gguf /data/models/llama3.2-1b.gguf
```

### 5. Create secrets
```bash
kubectl -n backend create secret generic app-secrets \
  --from-literal=SECRET_KEY="$(openssl rand -base64 32)"

kubectl -n backend create secret generic groq-secret \
  --from-literal=GROQ_API_KEY='gsk_your_key_here'

kubectl -n backend create secret docker-registry acr-secret \
  --docker-server=genaiplatform2026.azurecr.io \
  --docker-username=<ACR_USER> \
  --docker-password=<ACR_PASS>
```

### 6. Deploy the stack
```bash
kubectl apply -f k8s/backend.yaml
kubectl apply -f k8s/qdrant.yaml
kubectl apply -f k8s/llama-cpp.yaml
kubectl apply -f k8s/network-policies.yaml
```

### 7. Install Argo CD
```bash
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
sleep 120
kubectl -n argocd get pods
```

### 8. Install monitoring
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add falcosecurity https://falcosecurity.github.io/charts
helm repo update

helm install prometheus prometheus-community/prometheus -n monitoring
helm install grafana grafana/grafana -n monitoring
helm install loki grafana/loki-stack -n monitoring
helm install falco falcosecurity/falco \
  -n monitoring \
  --set driver.kind=modern_ebpf \
  --set falcosidekick.enabled=false \
  --set resources.requests.memory=128Mi \
  --set resources.limits.memory=256Mi
```

### 9. Verify
```bash
kubectl get pods -A
kubectl -n backend port-forward svc/fastapi 8001:8001 &
curl http://localhost:8001/health
# {"status":"ok"}
```

---

## 📡 API Endpoints

### Auth & Meta
| Method | Endpoint | Description | Roles |
|---|---|---|---|
| POST | `/auth/login` | JWT login | public |
| GET | `/health` | Liveness probe | public |
| GET | `/models` | List available models | public |
| GET | `/tasks` | Role-allowed tasks | auth |

### Document Management
| Method | Endpoint | Description | Roles |
|---|---|---|---|
| POST | `/documents/upload` | Upload + embed file | admin, analyst, user |
| GET | `/documents` | List user's documents | admin, analyst, user |
| DELETE | `/documents/{doc_id}` | Delete document | admin, analyst, user |

### Text Tasks
| Method | Endpoint | Description | Roles |
|---|---|---|---|
| POST | `/summarize` | Summarize text | admin, analyst, user |
| POST | `/translate` | Translate text | admin, analyst, user |
| POST | `/classify` | Classify text | admin, analyst |
| POST | `/action-items` | Extract action items | admin, analyst |
| POST | `/reports` | Generate reports | admin, analyst |

### RAG
| Method | Endpoint | Description | Roles |
|---|---|---|---|
| POST | `/chat` | RAG chat with citations | admin, analyst, user |

### File Processing
| Method | Endpoint | Description | Roles |
|---|---|---|---|
| POST | `/process-file` | Upload + run task | admin, analyst, user |
| GET | `/files` | List processed files | admin, analyst, user |
| GET | `/files/{id}` | Download file | admin, analyst, user |
| DELETE | `/files/{id}` | Delete file | admin |

### Analytics
| Method | Endpoint | Description | Roles |
|---|---|---|---|
| GET | `/stats` | Role-based statistics | auth |
| GET | `/history` | User action history | auth |
| POST | `/compare` | Compare two documents | admin, analyst, user |
| POST | `/compare-models` | Compare two LLMs | admin, analyst, user |

### Admin
| Method | Endpoint | Description | Roles |
|---|---|---|---|
| GET | `/admin/users` | List all users | admin |
| GET | `/admin/usage` | Usage statistics | admin |
| POST | `/prompts/validate` | Prompt-injection check | auth |

### Observability
| Method | Endpoint | Description |
|---|---|---|
| GET | `/metrics` | Prometheus metrics |
| GET | `/docs` | Swagger UI |

---

## 🔄 CI/CD Pipeline

### Flow
```
1. Developer pushes to main
       ↓
2. GitHub Actions (backend-ci.yaml)
   • checkout
   • docker buildx
   • login to ACR
   • build + push image:sha-<7char>
   • Trivy scan (report only)
   • sed replace image tag in k8s/backend.yaml
   • git commit + push
       ↓
3. Argo CD detects manifest change
       ↓
4. Sync → rolling update → zero downtime
       ↓
5. New pod running new image
```

### Argo CD Application
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: genai-backend
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/israa-benrjab/genai-platform.git
    targetRevision: main
    path: k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: backend
  syncPolicy:
    automated:
      prune: false
      selfHeal: false
```

---

## 📊 Observability

### Prometheus scrape config
```yaml
- job_name: fastapi-backend
  scrape_interval: 15s
  metrics_path: /metrics
  static_configs:
    - targets:
        - fastapi.backend.svc.cluster.local:8001
```

### Grafana Dashboard
16 panels across 4 rows:
- **Key Metrics** — Request Rate, Error Rate (5xx), 95th Latency, Memory Usage
- **Traffic Analysis** — Request Rate by Status Code, Status Code Distribution (donut), Top Endpoints (bar gauge)
- **Performance & Resources** — Latency Percentiles (p50/p95/p99), CPU Usage, Memory Over Time, Total Requests, Avg Latency, Uptime
- **Live Logs** — FastAPI log stream via Loki

<!-- Add screenshots here once captured, e.g.: -->
<!-- ![Grafana Dashboard](docs/screenshots/grafana-dashboard.png) -->

---

## ⚡ Performance

Numbers captured from a sustained 4-minute load test against the live cluster (single-node Minikube, CPU-only inference):

| Metric | Value |
|---|---|
| Requests processed | 7,740+ |
| Endpoints exercised | 18 of 25+ |
| Fast endpoints (`/health`, `/models`, `/tasks`) | < 50 ms p95 |
| Auth (`/auth/login`) | < 100 ms p95 |
| RAG chat (`/chat`, local Llama 3.2) | 5–15 s (CPU-bound, no GPU) |
| Summarization (`/summarize`, local) | 5–12 s |
| Full CI/CD loop | `git push` → new pod live in ~5 min |
| GitHub Actions build time | ~3m 30s (cold), faster with layer cache |

**Interpretation:** Fast, structural endpoints (auth, listing, stats) perform at typical REST API latency. LLM-bound endpoints are the bottleneck — expected on CPU-only inference with no GPU. This is the realistic trade-off documented in Lessons Learned: a GPU-backed deployment (or Groq routing for latency-sensitive paths) would bring RAG/summarization latency down to sub-second.

---

## ☁️ Azure Container Registry (ACR)

All backend images are built and pushed to Azure Container Registry. The Kubernetes cluster pulls from ACR using a `docker-registry` secret.

### Registry details
| Field | Value |
|---|---|
| Registry | `genaiplatform2026.azurecr.io` |
| Repository | `genai-backend` |
| Admin user | enabled (demo) |
| SKU | Basic |
| Region | France Central |

### Image tagging strategy
Every push to `main` triggers GitHub Actions, which tags the image three ways:

| Tag | Purpose |
|---|---|
| `latest` | Most recent build |
| `v38` | Semantic version tag for milestones |
| `sha-<7char>` | Immutable per-commit tag (e.g. `sha-dcc20a6`) |

The `sha-<7char>` tag is referenced in `k8s/backend.yaml` — it guarantees deterministic deploys (same commit → same image).

### Kubernetes integration
```bash
ACR_USER=$(az acr credential show -n genaiplatform2026 --query username -o tsv)
ACR_PASS=$(az acr credential show -n genaiplatform2026 --query "passwords[0].value" -o tsv)

kubectl -n backend create secret docker-registry acr-secret \
  --docker-server=genaiplatform2026.azurecr.io \
  --docker-username="$ACR_USER" \
  --docker-password="$ACR_PASS"
```

### Inspect the registry
```bash
az acr repository list -n genaiplatform2026 -o table

az acr repository show-tags -n genaiplatform2026 \
  --repository genai-backend --orderby time_desc -o table

az acr manifest list-metadata \
  -r genaiplatform2026 -n genai-backend -o table
```

---

## 📦 Azure Blob Storage

Raw uploaded files are optionally archived to Azure Blob Storage before processing, giving a durable, cost-effective cold-storage copy independent of the ephemeral pod filesystem.

### Configuration
| Env var | Purpose |
|---|---|
| `AZURE_STORAGE_CONNECTION_STRING` | Full connection string for the storage account |
| `AZURE_CONTAINER_NAME` | Blob container name (default: `uploaded-docs`) |

### Blob path convention
```
container: uploaded-docs
   └── <username>/<doc_id>_<original-filename>

Example:
   uploaded-docs/admin/5425a73f-0a29-4d94-a3f1-34cb559b1662_quarterly-report.pdf
```

The `<username>` prefix gives namespace-like isolation — even at the storage layer, one user's files can't be browsed by another.

**Design decision:** Blob upload is best-effort. If it fails, the request still succeeds (the file is embedded into Qdrant regardless). The upload is skipped entirely if the env vars aren't set — the platform works with or without Blob Storage.

---

## 🔒 Security (Defense in Depth)

This platform follows a defense-in-depth approach across four layers — cloud, cluster, application, and supply chain.

### Layer 1 — Cloud (Azure)
| Control | Implementation |
|---|---|
| Network isolation | NSG with explicit inbound rules for 22, 80, 443, and app ports |
| Private registry | ACR with admin auth — no public Docker Hub dependency |
| Disk isolation | 128 GB data disk at `/data`, separated from OS disk |
| Secret separation | Storage strings and API keys in Kubernetes Secrets, never in code |

### Layer 2 — Kubernetes cluster
| Control | Implementation |
|---|---|
| Non-root execution | `runAsNonRoot: true`, `runAsUser: 1000`, `runAsGroup: 1000` |
| Read-only root filesystem | `readOnlyRootFilesystem: true` |
| Capability dropping | All Linux capabilities dropped: `capabilities: { drop: ["ALL"] }` |
| No privilege escalation | `allowPrivilegeEscalation: false` |
| Writable-path isolation | `emptyDir` volumes for `/tmp`, `/app/uploads`, `/app/history`, `/app/hf-cache` |
| Default-deny networking | `NetworkPolicy` deny-all in the backend namespace |
| Explicit allow rules | `allow-backend-egress`, `allow-dns-egress`, `allow-prometheus-scrape` |
| Runtime threat detection | Falco (eBPF-based syscall monitoring) |
| Secret management | Kubernetes Secrets for `SECRET_KEY`, `GROQ_API_KEY`, ACR creds |
| Image pull authentication | `imagePullSecrets` bound to a dedicated docker-registry secret |

### Layer 3 — Application
| Control | Implementation |
|---|---|
| JWT authentication | HS256-signed tokens, 30 min expiry |
| Role-based authorization | `require_role()` dependency — 3 roles with endpoint-level enforcement |
| Per-user document isolation | Qdrant payload filter on `owner=<username>` |
| PII scanning | Regex detection of emails, phone numbers, API keys, IP addresses |
| Prompt-injection detection | `/prompts/validate` rejects known jailbreak patterns |
| Request timeouts | 300s LLM timeout, 10s Qdrant timeout |
| Secret hygiene | `SECRET_KEY` loaded from env; fails fast if missing |

### Layer 4 — Supply chain & CI/CD
| Control | Implementation |
|---|---|
| Image vulnerability scanning | Trivy on every CI build |
| Secret scanning | GitHub Push Protection enabled on the repository |
| Immutable image tags | Every deploy uses `sha-<7char>` — no `latest` in production |
| Least-privilege CI | Workflow uses `permissions: contents: write` only when needed |
| Rollback-ready | Argo CD keeps revision history |

### Continuous verification
```bash
# Pod security context
kubectl -n backend get deployment fastapi-deployment \
  -o jsonpath='{.spec.template.spec.securityContext}' | jq

# Network policies
kubectl -n backend get networkpolicy

# No secrets in repo
git ls-files | grep -iE "\.env|secret|key|pem|credential" || echo "CLEAN"

# Image scan
trivy image genaiplatform2026.azurecr.io/genai-backend:sha-dcc20a6

# Falco runtime detection
kubectl -n monitoring logs -l app.kubernetes.io/name=falco --tail=50
```

---

## 💰 Cost Breakdown

Approximate monthly cost for the infrastructure as configured (Azure, France Central, pay-as-you-go). Actual costs depend on usage and any free-tier/student credits applied.

| Resource | Spec | Approx. cost/month |
|---|---|---|
| Azure VM | Standard_D4s_v3 (4 vCPU, 16 GB RAM) | ~$140 |
| Data disk | 128 GB Standard SSD | ~$10 |
| OS disk | 30 GB Premium SSD | ~$5 |
| Container Registry | Basic SKU | ~$5 |
| Blob Storage | Cool tier, low volume | < $1 |
| Public IP | Static | ~$3 |
| **Total** | | **~$160–165/month** |

Cost-reduction options for a learning/demo environment:
- Use a Spot VM instance (up to 80% cheaper, with eviction risk)
- Stop the VM outside active development hours (`az vm deallocate`)
- Downsize to `Standard_D2s_v3` if not running the full monitoring stack simultaneously
- Use Azure Student credits ($100) or free-tier resources where eligible

---

## 📁 Project Structure

```
genai-platform/
├── .github/
│   └── workflows/
│       └── backend-ci.yaml          # GitHub Actions pipeline
├── k8s/
│   ├── backend.yaml                 # FastAPI service + deployment
│   ├── qdrant.yaml                  # Vector DB
│   ├── llama-cpp.yaml               # Local LLM inference
│   ├── network-policies.yaml        # Defense-in-depth networking
│   └── argocd/
│       └── backend-app.yaml         # Argo CD Application
├── fastapi-backend.py               # Main application
├── Dockerfile                       # Backend image
├── Dockerfile.vllm                  # vLLM image (unused, kept for reference)
├── .gitignore
└── README.md
```

---

## 🧪 Testing

```bash
# Port-forward the backend
kubectl -n backend port-forward svc/fastapi 8001:8001 &

# Run all endpoint tests
~/test-all-endpoints.sh

# Generate traffic for dashboard
~/traffic.sh 120
```

---

## 🐛 Troubleshooting

**Minikube control plane crashes**
```bash
docker ps -a | grep minikube
docker exec minikube systemctl start containerd
docker exec minikube systemctl start kubelet

NEW_PORT=$(docker port minikube 8443/tcp | awk -F: '{print $2}')
kubectl config set-cluster minikube --server=https://127.0.0.1:$NEW_PORT --insecure-skip-tls-verify=true
```

**Argo CD OutOfSync after push**
```bash
kubectl -n argocd patch application genai-backend --type merge \
  -p '{"operation":{"sync":{"revision":"HEAD"}}}'
```

**Prometheus target down**
```bash
kubectl -n monitoring get configmap prometheus-server -o yaml | grep -A5 fastapi
kubectl -n monitoring rollout restart deployment prometheus-server
```

**Image pull errors**
```bash
kubectl -n backend get secret acr-secret
kubectl -n backend get deployment fastapi-deployment -o jsonpath='{.spec.template.spec.imagePullSecrets}'
```

---

## 📈 Lessons Learned

Real production-shaped problems solved while building this:

- vLLM crashed on CPU-only → rebuilt the inference layer with llama-cpp-python
- Minikube control plane died 4+ times → wrote a recovery script and diagnosed via systemctl/crictl/journald
- Docker image pull failed → the `ggerganov` org moved to `ggml-org` → corrected the manifest
- Prometheus scrape targets missing → patched the configmap live and upgraded the Helm release
- Argo CD secret chicken-and-egg on fresh install → manually seeded `argocd-secret`
- Falco Helm chart breaking change → `falco.grpc` removed upstream → migrated to `driver.kind=modern_ebpf`

Each was a real infrastructure problem, not a tutorial exercise.

---

## ❓ FAQ

**Why CPU-only inference instead of a GPU?**
Cost. This runs on a student/demo Azure budget with no GPU quota. The architecture supports swapping in a GPU-backed vLLM deployment or a managed inference endpoint without changing the API contract — only the `ai/` namespace deployment would change.

**Why Minikube instead of AKS?**
Minikube on a single VM keeps the whole stack (compute, model storage, registry auth) inside one cost boundary, which matters for a self-funded learning project. The manifests are standard Kubernetes YAML, so migrating to AKS is a `kubectl apply` away — no rewrite needed.

**Why both a local LLM and Groq?**
To demonstrate hybrid routing: sensitive or offline-capable workloads stay local (privacy, no external dependency), while latency- or quality-sensitive workloads can route to a larger cloud model. It's the same pattern production systems use to balance cost, latency, and data sensitivity.

**Is this actually production-ready?**
It's production-patterned — RBAC, GitOps, defense-in-depth, observability, and CI/CD are all real and functional. What's missing for a true production deployment: persistent storage (currently `emptyDir`), a managed Kubernetes control plane (AKS instead of Minikube), and horizontal scaling / load balancing across multiple nodes. These are called out explicitly in the Roadmap.

**Why Argo CD instead of just a `kubectl apply` step in CI?**
GitOps decouples "what should be running" (declared in Git) from "what actually deploys it" (Argo CD's reconciliation loop). This means the cluster self-heals from drift, every change is auditable via Git history, and rollback is a Git revert rather than a manual intervention.

---

## 🗺️ Roadmap

- [ ] Persistent storage for Qdrant + uploaded files (replace `emptyDir` with PVC)
- [ ] Multi-model pool with automatic failover
- [ ] LangGraph agent workflows
- [ ] Helm chart for the entire stack
- [ ] Terraform for Azure provisioning
- [ ] Renovate/Dependabot for automated dependency updates
- [ ] Frontend (Docuvo) integration
- [ ] Migrate from Minikube to AKS for multi-node scaling
- [ ] Horizontal Pod Autoscaler based on Prometheus custom metrics

---

## 🤝 Contributing

This started as a solo learning project, but suggestions and issues are welcome.

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-improvement`)
3. Commit your changes with clear messages
4. Open a pull request describing what changed and why

Please don't commit secrets — the CI pipeline has push protection enabled, and it will block the push.

---

## 👤 Author

**Israa Benrjab**
Cloud Engineering student — ESPRIT
GitHub: [@israa-benrjab](https://github.com/israa-benrjab)
LinkedIn: [linkedin.com/in/israa-ben-rjab](https://linkedin.com/in/israa-ben-rjab)

---

## 📄 License

MIT
