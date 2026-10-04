# DocuFlow

DocuFlow extracts structured fields from invoice PDFs, and is a bench for
finding the configuration that does it best: compose a pipeline, measure it
over labelled documents, compare it with others, and train models on the
labelled history.

It runs locally today — a FastAPI backend and a React frontend, with local
models through LM Studio and hosted ones through Gemini and Google Document AI —
and ships as provider-neutral containers for deployment on any cloud. The
`cloud` branch is deployed on Google Cloud: Cloud Run, Cloud SQL, and open
models served by llama.cpp ([deployment](docs/deployment.md#google-cloud)).

## What it does

| Section | What you do there | Read more |
|---|---|---|
| **Workspace** | Extract one PDF, see where each value sits on the page, correct and mark it reviewed | [Extraction](docs/features/extraction.md) |
| **Extraction** | Define the fields — text, dates, amounts, currencies, closed or open categories — and the prompts | [Extraction](docs/features/extraction.md) |
| **Pipelines** | Compose the steps: page images or text, OCR, a model or a Custom Extractor, rules, trained models, and how to choose among them | [Pipelines](docs/features/pipelines.md) |
| **Master Data** | Keep the supplier register and the corrections written for each supplier | [Extraction](docs/features/extraction.md#rules-for-one-supplier) |
| **Datasets** | Hold the labelled documents everything is measured against | [Lab](docs/features/lab.md) |
| **Lab** | Run a configuration over a dataset, or a grid of pipelines × models as an experiment; compare methods, classes and confidence | [Lab](docs/features/lab.md) |
| **Models** | Train models — nearest neighbour, logistic regression, LightGBM, XGBoost, CatBoost — on the datasets, compare them, use them in pipelines | [Models](docs/features/models.md) |
| **LLM**, **Processors** | Choose and load models; register Document AI processors | [Language models and processors](docs/features/llm-and-processors.md) |

## Getting started

Requirements: Python 3.13, Node.js 22.13+, and LM Studio for local models.

On Windows:

```powershell
.\setup.ps1
.\start.ps1 -OpenBrowser
```

On any OS, with Docker:

```bash
docker compose up --build
```

Then open http://localhost:3000. A fresh clone has no model, key or data; what
to provide, and how to run without the PowerShell scripts, is in
[docs/development.md](docs/development.md).

## Documentation

- [Documentation index](docs/README.md)
- [Architecture](docs/architecture.md) — how it is built, where the code lives
- [Development](docs/development.md) — setup, tests, CI, known traps
- [Deployment and cloud portability](docs/deployment.md)
- [Contributing](CONTRIBUTING.md) — workflow, conventions, keeping docs current
- [Roadmap](ROADMAP.md) — what comes next and why
- [Decision records](docs/decisions/README.md)

Coding agents start from [AGENTS.md](AGENTS.md).
