# 0004 — Trained models are stored as data, never as pickles

**Context.** Models are trained here, exported, imported on other machines and,
later, moved between clouds. A pickle runs arbitrary code when it is loaded.

**Decision.** A model is a manifest plus files in declared formats only: JSON,
NumPy arrays read with `allow_pickle=False`, and each algorithm's own data
format (LightGBM text, XGBoost JSON, CatBoost `.cbm`). Its id is a hash of the
manifest and files. Import refuses any file the kind does not declare.

**Alternatives.** `joblib`/pickle — rejected for safety and portability.
ONNX — possible later for algorithms that export to it.

**Consequences.** Each algorithm implements save and load. A model whose
algorithm is not installed is listed and cannot run.
