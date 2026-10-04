# 0008 — One model server that loads the selected model, as LM Studio does

**Context.** A deployment needs several open models to compare, chosen from
the ones used locally in LM Studio. The first deployment served one fixed
model; serving another meant a redeploy.

**Decision.** One Cloud Run service runs llama.cpp in router mode over every
model in a bucket, holding one at a time (`--models-max 1`, no autoload).
DocuFlow treats it the way it treats LM Studio: it lists every model with
whether it is loaded, loads the selected one explicitly and warms it before
any document is timed, and an experiment loads each model once. The models
are a list in the deployment's env file; a script copies their files to the
bucket and writes the router's presets and a catalog of what each model is.

**Alternatives.**
- *One Cloud Run service per model* — rejected: ten models would be ten
  services to deploy and keep in step, for a bench that uses one model at a
  time. It would let two models answer at once, which nothing here needs yet.
- *A fixed model per deployment* — rejected: changing model would be a
  redeploy.
- *Loading on the first request (autoload)* — rejected: the load would land
  inside the first document's timer, which is what explicit loading exists to
  prevent.

**Consequences.** The service is sized for the largest model; on CPUs Cloud
Run caps an instance at 32 GiB, so larger models need GPUs. Switching models
reloads gigabytes from the bucket. When the service scales to zero the loaded
model is gone, and LLM says so. CPU stays allocated while an instance is up,
so a load can finish between requests.
