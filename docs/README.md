# DocuFlow documentation

| Page | What it answers |
|---|---|
| [Architecture](architecture.md) | How the system is put together, and where each thing lives in the code |
| [Development](development.md) | Setting up, running, testing, CI, generated files, known traps |
| [Deployment and cloud portability](deployment.md) | Containers, configuration, mapping onto GCP / AWS / Azure, what is not portable yet |
| [Contributing](../CONTRIBUTING.md) | Workflow, code conventions, which page to update for which change |
| [Roadmap](../ROADMAP.md) | What is next, what is decided but postponed, and why |

## Features

| Page | Section of the app |
|---|---|
| [Extraction](features/extraction.md) | Workspace and Extraction: fields (including categories), readers, value locations, confidence, supplier rules |
| [Pipelines](features/pipelines.md) | Pipelines: the visual editor, and several methods per field |
| [Lab](features/lab.md) | Lab: runs, retries, accounting, stored readings, analytics, experiments |
| [Models](features/models.md) | Models: algorithms, training, validation, the model registry, fine-tuning data |
| [Language models and processors](features/llm-and-processors.md) | LLM and Processors: local and hosted models, loading, the Document AI catalog |

## Decisions and history

- [Decision records](decisions/README.md) — choices with real alternatives, and why.
- [History](history/README.md) — dated review notes, kept as they were.

## Keeping these pages current

Documentation changes in the same commit as the behaviour it describes; the
table in [CONTRIBUTING](../CONTRIBUTING.md#keeping-the-documentation-current)
says which page. A page states what is true now. When a page grows past one
subject, split it and add it to the tables above.
