"""The DocuFlow API: the app, its middleware, and one router per subject.

The endpoints live in `app.api.routes`, one module per section of the UI;
what they share — stores, runtime state, helpers — lives in `app.api.deps`.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.services.errors import ProviderError
from app.api.routes import models, settings, documents, pipelines, master_data, datasets, runs, evaluations, processors, training, experiments

app = FastAPI(title="DocuFlow API", version="0.1.0")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ProviderError)
async def provider_failed(request, exc: ProviderError) -> JSONResponse:
    """A service behind the request failed; the request itself was fine.

    One answer for every provider, so a new call site cannot forget one of
    them and turn Google's message into a bare 500.
    """
    return JSONResponse(status_code=502, content={"detail": str(exc)})


app.include_router(models.router)
app.include_router(settings.router)
app.include_router(documents.router)
app.include_router(pipelines.router)
app.include_router(master_data.router)
app.include_router(datasets.router)
app.include_router(runs.router)
app.include_router(evaluations.router)
app.include_router(processors.router)
app.include_router(training.router)
app.include_router(experiments.router)
