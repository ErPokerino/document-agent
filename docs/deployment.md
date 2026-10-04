# Deployment and cloud portability

DocuFlow runs on a developer machine today. It is meant to run on more than one
cloud, starting with Google Cloud, without depending on any one of them. This
page is the contract that keeps that true, and the list of what still stands in
the way.

## Principles

1. **One image, configured by the environment.** The backend and frontend are
   plain OCI images (`deploy/`). Nothing in them names a cloud; storage,
   allowed origins and credentials come from `DOCUFLOW_*` variables.
2. **Every external service behind one module.** A provider is an adapter
   behind an interface ([architecture](architecture.md#where-vendor-specific-code-lives)).
   Callers never import a cloud SDK directly.
3. **Managed services are a choice per deployment, not a dependency of the
   code.** Google Document AI and Gemini are providers DocuFlow can use, the way
   LM Studio is; using them on GCP is natural, and the same pipeline vocabulary
   must be able to name an alternative elsewhere.
4. **State is portable data.** Models are JSON and arrays, datasets are PDFs and
   JSON labels, the database is SQL. Nothing is a pickle or a provider-specific
   format a move would strand.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `DOCUFLOW_DATA_DIR` | `backend/data` | Settings, database, datasets, models, caches |
| `DOCUFLOW_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Origins allowed to call the API |
| `DOCUFLOW_GCP_CREDENTIALS` | `<data dir>/gcp-service-account.json` | Document AI service-account key |
| `PORT` | `8000` backend, `3000` frontend | Port inside the container |
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | API address the browser calls; fixed at frontend build time |

## Running the containers

```bash
docker compose up --build
```

The backend keeps its state on the `docuflow-data` volume. LM Studio stays on
the host: in **LLM**, set its URL to `http://host.docker.internal:1234`. CI
builds both images and starts them on every push.

## Mapping onto a cloud

The same two images; each platform supplies a container runtime, a volume or
bucket for the data folder, a secret store for keys, and a way to restrict who
reaches the app.

| Need | Google Cloud (first target) | AWS | Azure |
|---|---|---|---|
| Run the containers | Cloud Run or GKE | ECS on Fargate or EKS | Container Apps or AKS |
| Data folder | Filestore (NFS) volume | EFS | Azure Files |
| Secrets (API keys, service account) | Secret Manager, mounted as files or variables | Secrets Manager | Key Vault |
| Restricting access | IAP or a load balancer with OIDC | ALB with OIDC / Cognito | Easy Auth / Entra ID |
| Hosted language models | Gemini (API or Vertex AI) | Bedrock | Azure OpenAI |
| OCR and layout | Document AI | Textract | Document Intelligence |

## What is not portable yet

Honest gaps, in the order a first cloud deployment would meet them. Each is a
seam to cut, not a rewrite.

1. **No authentication.** The API trusts whoever reaches it. Until DocuFlow
   has users, a deployment must sit behind the platform's identity-aware
   access (the *Restricting access* row above).
2. **One instance.** Lab runs, experiments and training jobs run as tasks
   inside the API process, and the model-operation lock is in memory. Two
   instances would each think they were alone. Run a single instance until
   jobs move to a queue (Cloud Tasks / Pub/Sub, SQS, Service Bus — behind one
   job interface).
3. **SQLite.** Right for one machine; on network storage its locking is not
   reliable, and object-storage mounts (Cloud Storage FUSE, S3 mounts) do not
   support it at all. Keep the data folder on a file-system volume, or move the
   stores to PostgreSQL (Cloud SQL, RDS, Azure Database) behind the same store
   classes.
4. **Files on a file system.** Datasets, evaluation inputs, models and caches
   are files under the data folder. A storage interface over local files and
   object storage (GCS, S3, Blob) would let the folder become a bucket.
5. **Vendor names in the pipeline vocabulary.** Step kinds such as
   `document_ai_ocr` name Google. Generic reader kinds (`ocr`, `layout`,
   `field_extractor`) bound to a provider in the processor catalog would let one
   pipeline run on Textract or Document Intelligence; existing pipelines would
   migrate by mapping the old kinds.
6. **Credentials as a key file.** Document AI is reached with a
   service-account key. On Google Cloud the runtime's own identity (Application
   Default Credentials / workload identity) should be used instead, with the key
   file kept for other hosts.
7. **Local inference is LM Studio only.** In a cloud, models are served by a
   provider (Gemini, Bedrock, Azure OpenAI) or self-hosted behind an
   OpenAI-compatible endpoint; the `ExtractionProvider` interface is where such
   a provider joins.
8. **The frontend's API address is fixed at build time.** Serving both
   behind one origin, or reading the address at run time, would let one
   frontend image serve every environment.

The order to tackle them is in the [roadmap](../ROADMAP.md#cloud-deployment).
