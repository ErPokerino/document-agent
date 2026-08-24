"""What the machine running DocuFlow can actually lend a model.

The app used to decide how to load a model from two constants: a file bigger
than 8 GiB, or more than 20 billion parameters, meant "hold it on the
processor". Both numbers were measured on one laptop with an integrated Intel
adapter. They are right there and arbitrary anywhere else — on a workstation
with 24 GB of dedicated VRAM they would keep a model off a card that fits it
comfortably, and nothing in the app would ever catch the mistake.

So the numbers are derived here instead, from what LM Studio reports about the
host. `lms runtime survey` is the only source: it answers for the *selected*
runtime, which is what makes it the right one — a processor-only build honestly
reports no accelerator at all, and that is precisely when nothing can be
offloaded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


GIB = 1024**3

# An integrated adapter has no memory of its own. The figure it reports is a
# slice of system RAM, and a single allocation cannot rely on all of it: this
# machine advertises 19.82 GiB and lost the Vulkan device well below that.
# The fraction is set so the budget lands on the 8 GiB threshold that was
# measured by hand here, which is the only evidence anyone has for what this
# class of adapter tolerates.
INTEGRATED_USABLE_FRACTION = 0.40
# Dedicated VRAM is real and exclusive, but the runtime still needs room for
# the context and its own buffers.
DEDICATED_USABLE_FRACTION = 0.90
# Activations, KV cache and a vision projector scale with the parameter count,
# not with how tightly the weights were quantized. bonsai-27b is 27B in a
# 4.4 GB Q1_0 file: the file says "small" and the runtime allocates for 27
# billion parameters anyway.
BYTES_PER_BILLION_PARAMETERS = int(0.40 * GIB)

_SIZE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>GiB|MiB|GB|MB)", re.IGNORECASE)
_UNITS = {"gib": GIB, "gb": 10**9, "mib": 1024**2, "mb": 10**6}


@dataclass(frozen=True)
class Accelerator:
    name: str
    memory_bytes: int
    # Shared-memory adapters are the ones whose advertised size overstates
    # what a single allocation can hold.
    integrated: bool


@dataclass(frozen=True)
class HostCapabilities:
    accelerators: tuple[Accelerator, ...] = ()
    ram_bytes: int = 0

    @property
    def offload_budget_bytes(self) -> int:
        """How much model the best accelerator here can be trusted with.

        Zero when there is none, which is the honest answer for a
        processor-only runtime and the reason nothing gets offloaded to it.
        """
        if not self.accelerators:
            return 0
        best = max(self.accelerators, key=lambda adapter: adapter.memory_bytes)
        fraction = (
            INTEGRATED_USABLE_FRACTION if best.integrated else DEDICATED_USABLE_FRACTION
        )
        return int(best.memory_bytes * fraction)

    @property
    def has_integrated_only(self) -> bool:
        return bool(self.accelerators) and all(a.integrated for a in self.accelerators)


def _bytes_from(text: str) -> int:
    match = _SIZE.search(text)
    if match is None:
        return 0
    return int(float(match.group("value")) * _UNITS[match.group("unit").lower()])


def parse_survey(output: str) -> HostCapabilities:
    """Read `lms runtime survey`. Anything unreadable reads as no hardware.

    Claiming an accelerator that is not there is the failure that costs a run;
    claiming none only costs speed, so that is the way this errs.
    """
    accelerators: list[Accelerator] = []
    in_table = False
    for line in (output or "").splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("GPU/ACCELERATORS"):
            in_table = True
            continue
        if in_table:
            if not stripped or stripped.upper().startswith(("CPU:", "RAM:")):
                in_table = False
                continue
            memory = _bytes_from(stripped)
            if memory <= 0:
                continue
            name = _SIZE.sub("", stripped).strip()
            accelerators.append(
                Accelerator(
                    name=name,
                    memory_bytes=memory,
                    integrated="integrated" in stripped.lower(),
                )
            )

    ram = 0
    for line in (output or "").splitlines():
        if line.strip().upper().startswith("RAM:"):
            ram = _bytes_from(line)
            break
    return HostCapabilities(accelerators=tuple(accelerators), ram_bytes=ram)


def parameter_billions(params_string: str | None) -> float | None:
    """LM Studio's `params_string` as a number of billions, or None.

    "35B-A3B" is a 35B model with 3B active, and the allocation follows the
    total. "128x1.0B" is 128 experts of 1B, and it is the expert that is held.
    """
    if not params_string:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*([BM])\b", params_string, re.IGNORECASE)
    if match is None:
        return None
    value = float(match.group(1))
    return value if match.group(2).upper() == "B" else value / 1000


def estimated_working_set_bytes(size_bytes: int | None, params_string: str | None) -> int:
    """What loading this model actually asks the accelerator for.

    The larger of the two things that can dominate: the weights as they sit on
    disk, and what the parameter count needs regardless of quantization.
    """
    from_file = int(size_bytes or 0)
    parameters = parameter_billions(params_string)
    from_parameters = int(parameters * BYTES_PER_BILLION_PARAMETERS) if parameters else 0
    return max(from_file, from_parameters)
