"""Every domain model, from one import.

The models live in topic modules — extraction, runtime, settings, master_data,
datasets, pipelines, evaluation, training — so a reader finds a subject in one
file. Code may import from those modules or from here; both stay valid, and
`lib/types.ts` is generated from the API schema, not from where a class sits.
"""

from app.domain.billing import *  # noqa: F401,F403
from app.domain.datasets import *  # noqa: F401,F403
from app.domain.evaluation import *  # noqa: F401,F403
from app.domain.extraction import *  # noqa: F401,F403
from app.domain.master_data import *  # noqa: F401,F403
from app.domain.pipelines import *  # noqa: F401,F403
from app.domain.runtime import *  # noqa: F401,F403
from app.domain.settings import *  # noqa: F401,F403
from app.domain.training import *  # noqa: F401,F403
