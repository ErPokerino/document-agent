"""Lab: evaluations over a dataset."""

import asyncio
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import HTTPException, Query, Response, APIRouter

from app.api import deps
from app.domain.billing import UsageDetail
from app.domain.models import (
    ClassificationResult,
    ClassScoreResult,
    EntityFormat,
    Evaluation,
    EvaluationDetail,
    EvaluationRequest,
    FieldMethods,
    MethodScore,
    MetricTally,
    ResolutionTrial,
)
from app.evaluation.classification import classification_report
from app.evaluation.methods import method_report, resimulate
from app.pipeline.resolution import ResolutionConfig
from app.evaluation.scoring import FieldOutcome
from app.evaluation.fingerprint import configuration_fingerprint, rule_record, rules_from_records
from app.evaluation.export import evaluation_to_csv
from app.pipeline.compiler import PipelineError, build_steps
from app.pipeline.definition import uses_model
from app.pipeline.store import InvalidPipelineName, UnknownPipeline
from app.services.document_ai import DocumentAiClient
from app.services.spreadsheet import content_disposition

router = APIRouter()


@router.get("/api/evaluations/{evaluation_id}/usage", response_model=UsageDetail)
async def get_evaluation_usage(evaluation_id: int):
    from app.services.billing import UsageStore
    if deps.evaluation_store.get_evaluation(evaluation_id) is None:
        raise HTTPException(status_code=404, detail="Evaluation not found.")
    return UsageStore(deps.DATABASE_PATH).detail(evaluation_id=evaluation_id)


@router.get("/api/evaluations", response_model=list[Evaluation])
async def list_evaluations(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_id: Annotated[int | None, Query(ge=1)] = None,
) -> list[Evaluation]:
    return [deps.evaluation_model(evaluation) for evaluation in deps.evaluation_store.list_evaluations(limit, before_id)]


@router.get("/api/evaluations/{evaluation_id}", response_model=EvaluationDetail)
async def get_evaluation(evaluation_id: int) -> EvaluationDetail:
    detail = deps.evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    summary = deps.evaluation_model(detail)
    return EvaluationDetail(
        **summary.model_dump(),
        prompts=detail.prompts,
        pipeline_definition=detail.pipeline_definition,
        has_dataset_snapshot=detail.dataset_snapshot is not None,
        has_register_snapshot=detail.register_snapshot is not None,
        documents=[asdict(document) for document in detail.documents],
        classification=classification_results(detail),
        methods=[
            FieldMethods(
                entity=tally.entity,
                documents=tally.documents,
                resolved_accuracy=tally.resolved_accuracy,
                oracle_accuracy=tally.oracle_accuracy,
                methods=[
                    MethodScore(method=m.method, documents=m.documents, answered=m.answered, correct=m.correct, accuracy=m.accuracy)
                    for m in tally.methods.values()
                ],
            )
            for tally in method_report(detail.prompts.entities, detail.documents)
        ],
    )


@router.post("/api/evaluations/{evaluation_id}/resolve", response_model=ResolutionTrial)
async def try_resolution(evaluation_id: int, config: ResolutionConfig) -> ResolutionTrial:
    """Score a stored run as if its candidates had been resolved under `config`."""
    detail = deps.evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    trial = resimulate(detail.prompts.entities, detail.documents, config)
    return ResolutionTrial(
        matched=trial.matched,
        total=trial.total,
        accuracy=trial.matched / trial.total if trial.total else None,
        per_entity={
            name: MetricTally(matched=matched, total=total, accuracy=matched / total if total else None)
            for name, (matched, total) in trial.per_entity.items()
        },
    )


def classification_results(detail: Any) -> list[ClassificationResult]:
    """Every categorical field the run scored, judged as a classifier."""
    outcomes = [
        FieldOutcome(
            entity=item.entity,
            expected=item.expected,
            actual=item.actual,
            confidence=item.confidence,
            matched=item.matched,
            score=item.score,
        )
        for document in detail.documents
        for item in document.items
    ]
    scored = {outcome.entity for outcome in outcomes}
    reports = []
    for entity in detail.prompts.entities:
        if entity.format is not EntityFormat.category or entity.name not in scored:
            continue
        report = classification_report(entity.name, outcomes)
        reports.append(
            ClassificationResult(
                **{key: getattr(report, key) for key in ("entity", "documents", "accuracy", "macro_f1", "labels", "confusion", "ranked_by")},
                classes=[
                    ClassScoreResult(
                        label=score.label,
                        support=score.support,
                        predicted=score.predicted,
                        true_positive=score.true_positive,
                        precision=score.precision,
                        recall=score.recall,
                        f1=score.f1,
                    )
                    for score in report.classes
                ],
                coverage=[asdict(point) for point in report.coverage],
            )
        )
    return reports


@router.get("/api/evaluations/{evaluation_id}/export.csv", response_class=Response)
async def export_evaluation(evaluation_id: int) -> Response:
    detail = deps.evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    filename = f"run-{evaluation_id}-{detail.dataset}.csv"
    return Response(
        content=evaluation_to_csv(detail),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": content_disposition("attachment", filename)},
    )


@router.get("/api/evaluations/{evaluation_id}/documents/{document}/file", response_class=Response)
async def read_evaluation_document(evaluation_id: int, document: str) -> Response:
    detail = deps.evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    snapshot = (detail.dataset_snapshot or {}).get(document)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="This evaluation has no stored input for that document")
    try:
        content = deps.evaluation_store.read_snapshot_document(snapshot["sha256"])
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=410, detail="The stored evaluation document is missing or damaged") from exc
    return Response(content=content, media_type="application/pdf")


@router.get("/api/lab/extraction-engine")
async def lab_extraction_engine():
    settings = deps.settings_store.read()
    return await deps.lab_extractor(settings, deps.selected_pipeline(settings))


async def prepare_evaluation(
    dataset: str,
    settings: Any,
    *,
    reuse_readings: bool,
    claim: bool,
    experiment_id: int | None = None,
    experiment_cell: int | None = None,
) -> int:
    """Snapshot, compile and record one Lab run, ready to be run.

    Shared by a single run and by every cell of an experiment, so a cell is an
    ordinary run in every respect: the same snapshot, pinning, fingerprint and
    refusals. `claim` takes the Lab just before the run is recorded; an
    experiment holds it for all its cells and passes False.

    Everything the run needs is recorded on its row, so whoever runs it —
    this process or a worker elsewhere — rebuilds it from there
    (`run_recorded_evaluation`).
    """
    documents: list[tuple[str, dict[str, Any]]] = []
    dataset_snapshot: dict[str, Any] = {}
    for document in deps.dataset_store.list_documents(dataset):
        if not document.labelled:
            continue
        label_file = deps.dataset_store.read_labels(dataset, document.name)
        if label_file is not None:
            documents.append((document.name, label_file.labels))
            digest = deps.evaluation_store.snapshot_document(deps.dataset_store.read_document(dataset, document.name))
            dataset_snapshot[document.name] = {"sha256": digest, "labels": label_file.labels}
    if not documents:
        raise HTTPException(
            status_code=400,
            detail="This dataset has no labelled documents. Add ground truth before running a test.",
        )

    # Compiled before anything is claimed: a pipeline that cannot run must
    # not leave the backend marked busy.
    pipeline_definition = deps.selected_pipeline(settings)
    from app.services.extraction_engine import resolve_extractor
    from app.services.document_ai import DocumentAiClient
    for step in pipeline_definition.steps:
        if step.kind.value in ("document_ai_ocr", "document_ai_layout"):
            config = step.config
            client = DocumentAiClient(deps.GCP_CREDENTIALS_PATH, config["project_id"], config["location"])
            identity = await resolve_extractor(client, config["processor_id"])
            if identity["version"]:
                config["processor_id"] = identity["processor_id"] + "/processorVersions/" + identity["version"]
    deps.refuse_seen_documents(pipeline_definition, dataset, dataset_snapshot)
    register_rows = deps.master_data_store.rows("suppliers")
    rule_list = deps.supplier_rule_store.all()
    rule_records = [rule_record(rule) for rule in rule_list]
    try:
        steps = build_steps(
            pipeline_definition,
            prompts=settings.prompts,
            entities=settings.prompts.entities,
            gcp=settings.gcp,
            register_rows=register_rows,
            frozen_rules=rule_list,
            artifacts=deps.artifact_store,
        )
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    extraction_engine = await deps.lab_extractor(settings, pipeline_definition)
    if extraction_engine:
        # Pin every extractor independently; a pipeline may contain more than one.
        identities = [extraction_engine, *extraction_engine["additional_processors"]]
        definitions = [step for step in pipeline_definition.steps if step.kind.value == "document_ai_extract"]
        executables = [step for step in steps if type(step).__name__ == "ExtractWithCustomExtractor"]
        for identity, definition, executable in zip(identities, definitions, executables, strict=True):
            processor = str(definition.config.get("processor_id") or settings.gcp.custom_extractor_processor_id)
            if identity["version"]:
                processor = identity["processor_id"] + "/processorVersions/" + identity["version"]
            definition.config["processor_id"] = processor
            executable.processor_id = processor

    selected_model = await deps.ensure_model_ready(settings, pipeline_definition)
    execution_profile = deps.execution_profile(settings, pipeline_definition, selected_model)
    recorded_model, recorded_provider = deps.recorded_model(settings, pipeline_definition)
    fingerprint = configuration_fingerprint(
        dataset_snapshot=dataset_snapshot,
        prompts=settings.prompts,
        pipeline=pipeline_definition,
        execution_profile=execution_profile,
        register_rows=register_rows,
        rules=rule_records,
    )

    if claim:
        deps.claim_lab()
    return deps.evaluation_store.start(
        dataset=dataset,
        model=recorded_model,
        prompts=settings.prompts,
        total_documents=len(documents),
        max_pages=pipeline_definition.page_limit,
        pipeline=settings.pipeline,
        provider=recorded_provider,
        steps=[step.kind.value for step in pipeline_definition.steps],
        pipeline_definition=pipeline_definition,
        execution_profile=execution_profile,
        dataset_snapshot=dataset_snapshot,
        extraction_engine=extraction_engine,
        fingerprint=fingerprint,
        register_snapshot=register_rows,
        rules_snapshot=rule_records,
        reuse_readings=reuse_readings,
        experiment_id=experiment_id,
        experiment_cell=experiment_cell,
    )


async def run_recorded_evaluation(evaluation_id: int, cancelled: asyncio.Event, *, resumed: bool) -> None:
    """Run, from what its row recorded, every document of a run not yet scored.

    A new run and a retry are the same thing here: the documents that have not
    succeeded, on the terms the run started with — its pinned pipeline, its
    prompts, its register and rules, its model and its choice about cached
    readings. Today's settings supply only what a run does not record: keys,
    addresses and the Google Cloud project.
    """
    detail = deps.evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise ValueError(f"No evaluation with id {evaluation_id}")
    if detail.dataset_snapshot is None:
        raise ValueError("This evaluation has no snapshot of its original documents and labels.")
    settings = deps.settings_store.read()
    steps = recorded_steps(detail, settings)
    definition = recorded_definition(detail)
    run_settings = (
        settings.model_copy(update={"provider": detail.provider, "model": detail.model})
        if uses_model(definition)
        else settings
    )
    attempted = deps.evaluation_store.attempted_documents(evaluation_id)
    documents = [
        (name, snapshot["labels"])
        for name, snapshot in detail.dataset_snapshot.items()
        if attempted.get(name) != "ok"
    ]
    snapshot = detail.dataset_snapshot
    try:
        await deps.run_evaluation(
            evaluation_id=evaluation_id,
            evaluations=deps.evaluation_store,
            datasets=deps.dataset_store,
            run_store=deps.run_store,
            dataset=detail.dataset,
            documents=documents,
            entities=detail.prompts.entities,
            prompts=detail.prompts,
            model=detail.model,
            provider=detail.provider,
            steps=steps,
            pipeline_name=detail.pipeline,
            pipeline_steps=detail.steps,
            execution_profile=detail.execution_profile,
            # The run finishes on the terms it started with, cached readings included.
            make_context=lambda name, content: deps.pipeline_context(
                run_settings, name, content, reuse_readings=detail.reuse_readings, recorded_profile=detail.execution_profile
            ),
            cancelled=cancelled,
            read_document=lambda name: deps.evaluation_store.read_snapshot_document(snapshot[name]["sha256"]),
            resumed=resumed,
        )
    except asyncio.CancelledError:
        deps.evaluation_store.finish(evaluation_id, "cancelled")
        raise


def recorded_definition(detail: Any) -> Any:
    # New runs carry the complete definition. Legacy rows fall back to the
    # saved pipeline because the earlier schema retained only its name.
    definition = (
        detail.pipeline_definition.model_copy(deep=True)
        if detail.pipeline_definition is not None
        else deps.pipeline_store.read(detail.pipeline)
    )
    definition.page_limit = detail.max_pages or definition.page_limit
    return definition


def recorded_steps(detail: Any, settings: Any) -> list[Any]:
    """The run's pipeline compiled as it was recorded, pinned versions included."""
    definition = recorded_definition(detail)
    # A run that recorded the register replays that copy. A run from before
    # the snapshot existed has nothing to replay, so it uses the tables as
    # they are now.
    if detail.register_snapshot is not None and detail.rules_snapshot is not None:
        return build_steps(
            definition,
            prompts=detail.prompts,
            entities=detail.prompts.entities,
            gcp=settings.gcp,
            register_rows=detail.register_snapshot,
            frozen_rules=rules_from_records(detail.rules_snapshot),
            artifacts=deps.artifact_store,
        )
    return build_steps(
        definition,
        prompts=detail.prompts,
        entities=detail.prompts.entities,
        gcp=settings.gcp,
        master_data=deps.master_data_store,
        supplier_rules=deps.supplier_rule_store,
        artifacts=deps.artifact_store,
    )


async def run_evaluation_job(job: Any, cancelled: asyncio.Event) -> None:
    """The work of an `evaluation` job: one Lab run, new or resumed."""
    evaluation_id = int(job.payload["evaluation_id"])
    try:
        await run_recorded_evaluation(evaluation_id, cancelled, resumed=bool(job.payload.get("resumed")))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # run_evaluation records a failure it meets itself; this covers one
        # met before it started, and leaves a run it already closed alone.
        deps.evaluation_store.finish(evaluation_id, "failed", error=str(exc))
        raise
    finally:
        deps.release_lab()


async def dispatch_evaluation(evaluation_id: int, *, resumed: bool) -> None:
    """Hand a recorded run to whatever runs jobs here; close it if nothing can."""
    try:
        await deps.start_job(
            "evaluation", f"Lab run {evaluation_id}", {"evaluation_id": evaluation_id, "resumed": resumed},
            subject_id=evaluation_id,
        )
    except Exception as exc:
        deps.evaluation_store.finish(evaluation_id, "failed", error=str(exc))
        deps.release_lab()
        raise


@router.post("/api/evaluations", response_model=Evaluation, status_code=202)
async def start_evaluation(request: EvaluationRequest) -> Evaluation:
    deps.require_dataset(request.dataset)
    evaluation_id = await prepare_evaluation(
        request.dataset, deps.settings_store.read(), reuse_readings=request.reuse_readings, claim=True,
    )
    await dispatch_evaluation(evaluation_id, resumed=False)
    return deps.evaluation_model(deps.evaluation_store.get_evaluation(evaluation_id))


@router.delete("/api/evaluations/{evaluation_id}", status_code=204, response_class=Response)
async def delete_evaluation(evaluation_id: int) -> Response:
    detail = deps.evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    if detail.status == "running":
        raise HTTPException(status_code=409, detail="Cancel that evaluation before deleting it.")
    deps.evaluation_store.delete(evaluation_id)
    return Response(status_code=204)


@router.post("/api/evaluations/{evaluation_id}/retry", status_code=202, response_model=Evaluation)
async def retry_evaluation(evaluation_id: int) -> Evaluation:
    """Fill in the documents a run never scored, inside the same run.

    The retry deliberately reuses the prompts, the model, the pipeline and the
    page limit the run was started with. Finishing a run with today's
    configuration would make its single accuracy number the average of two
    different experiments.
    """

    detail = deps.evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    if detail.status == "running":
        raise HTTPException(status_code=409, detail="That evaluation is already running.")
    if detail.dataset_snapshot is None:
        raise HTTPException(status_code=409, detail="This evaluation has no snapshot of its original documents and labels. Its inputs cannot be recovered for a retry.")

    settings = deps.settings_store.read()
    engine = detail.extraction_engine
    explicit_locations = detail.pipeline_definition is not None and all("project_id" in step.config and "location" in step.config for step in detail.pipeline_definition.steps if step.kind.value.startswith("document_ai_"))
    if engine and not explicit_locations and (engine.get("project_id") != settings.gcp.project_id or engine.get("location") != settings.gcp.location):
        raise HTTPException(status_code=409, detail="This evaluation used a different Document AI project or location.")
    try:
        # Compiled here so a run that can no longer be built is refused now,
        # not by a worker after the run was reopened.
        definition = recorded_definition(detail)
        recorded_steps(detail, settings)
    except (UnknownPipeline, InvalidPipelineName) as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This run used the pipeline '{detail.pipeline}', which no longer exists. "
                "Recreate it to finish the run."
            ),
        ) from exc
    except PipelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Which model is selected matters only to a pipeline that asks one. Read
    # after the pipeline, because a Custom Extractor run scores the same
    # whatever is loaded, and refusing to finish it over an unused model would
    # leave it half done for no reason.
    if uses_model(definition) and (
        settings.provider != detail.provider or settings.model != detail.model
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"This run used {detail.provider}/{detail.model}; the active selection is "
                f"{settings.provider}/{settings.model}. The retry was not started."
            ),
        )

    selected_model = await deps.ensure_model_ready(settings, definition)
    current_profile = deps.execution_profile(settings, definition, selected_model)
    if detail.execution_profile is not None and current_profile != detail.execution_profile:
        raise HTTPException(
            status_code=409,
            detail=(
                "The active model execution profile differs from the one recorded for this run. "
                "The retry was not started."
            ),
        )

    attempted = deps.evaluation_store.attempted_documents(evaluation_id)
    if all(attempted.get(name) == "ok" for name in detail.dataset_snapshot):
        raise HTTPException(
            status_code=400,
            detail="This run has nothing left to process: every labelled document already succeeded.",
        )

    deps.claim_lab()
    deps.evaluation_store.reopen(evaluation_id)
    await dispatch_evaluation(evaluation_id, resumed=True)
    return deps.evaluation_model(deps.evaluation_store.get_evaluation(evaluation_id))


@router.post("/api/evaluations/{evaluation_id}/cancel", status_code=202, response_model=Evaluation)
async def cancel_evaluation(evaluation_id: int) -> Evaluation:
    detail = deps.evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    if detail.status != "running":
        raise HTTPException(status_code=409, detail="That evaluation is not running.")
    # Recorded on the job, where the work looks for it at document
    # boundaries and every few seconds; in process the task is also cancelled
    # at once, which propagates into the provider request so a slow document
    # does not keep running for minutes after the user pressed Cancel. A run
    # inside an experiment stops the experiment with it.
    deps.evaluation_store.finish(evaluation_id, "cancelled")
    if detail.experiment_id is not None:
        deps.experiment_store.finish(detail.experiment_id, "cancelled")
        deps.cancel_job("experiment", detail.experiment_id)
    deps.cancel_job("evaluation", evaluation_id)
    return deps.evaluation_model(deps.evaluation_store.get_evaluation(evaluation_id))
