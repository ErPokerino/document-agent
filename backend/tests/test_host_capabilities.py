"""Deciding how to load a model from the host, not from constants.

The thresholds this replaces — 8 GiB of file, 20 billion parameters — were
measured on one laptop with an integrated Intel adapter. They are correct
there and meaningless anywhere else: on a workstation with 24 GB of dedicated
VRAM they would hold a model on the processor that the card fits comfortably,
and nothing in the app would ever notice.

So the question asked here is the one that actually matters on any machine:
does this model's working set fit what the accelerator can give it?
"""

from app.services.host import (
    Accelerator,
    HostCapabilities,
    estimated_working_set_bytes,
    parse_survey,
)
from app.services.lm_studio import requires_cpu_safe_profile


GIB = 1024**3

INTEGRATED_SURVEY = """Survey by llama.cpp-win-x86_64-vulkan-avx2 (2.29.1)
GPU/ACCELERATORS                             VRAM     
Intel(R) UHD Graphics (Vulkan, Integrated)   19.82 GiB

CPU: x86_64 (AVX, AVX2)
RAM: 39.64 GiB
"""

CPU_ONLY_SURVEY = """Survey by llama.cpp-win-x86_64-avx2 (2.29.1)
No GPUs detected

CPU: x86_64 (AVX, AVX2)
RAM: 39.64 GiB
"""

DEDICATED_SURVEY = """Survey by llama.cpp-win-x86_64-nvidia-cuda-avx2 (2.29.1)
GPU/ACCELERATORS                      VRAM     
NVIDIA GeForce RTX 4090 (CUDA)        23.99 GiB

CPU: x86_64 (AVX, AVX2)
RAM: 63.85 GiB
"""


# -- reading the machine ------------------------------------------------------


def test_an_integrated_adapter_is_recognised_as_one() -> None:
    host = parse_survey(INTEGRATED_SURVEY)
    assert len(host.accelerators) == 1
    adapter = host.accelerators[0]
    assert "UHD" in adapter.name
    assert adapter.integrated is True
    assert round(adapter.memory_bytes / GIB, 2) == 19.82
    assert round(host.ram_bytes / GIB, 2) == 39.64


def test_a_dedicated_card_is_told_apart_from_an_integrated_one() -> None:
    host = parse_survey(DEDICATED_SURVEY)
    assert host.accelerators[0].integrated is False
    assert round(host.accelerators[0].memory_bytes / GIB, 2) == 23.99


def test_a_processor_only_runtime_reports_no_accelerator() -> None:
    host = parse_survey(CPU_ONLY_SURVEY)
    assert host.accelerators == ()
    assert host.offload_budget_bytes == 0


def test_an_unreadable_survey_claims_no_hardware_rather_than_guessing() -> None:
    for text in ("", "something else entirely", "GPU/ACCELERATORS\n"):
        assert parse_survey(text).accelerators == ()


# -- what the machine can actually lend a model -------------------------------


def test_an_integrated_adapter_is_budgeted_below_what_it_advertises() -> None:
    """Its VRAM figure is a slice of system RAM, not memory it can all use."""
    host = parse_survey(INTEGRATED_SURVEY)
    assert host.offload_budget_bytes < host.accelerators[0].memory_bytes
    # It lands where the hand-measured 8 GiB threshold used to sit, which is
    # the only evidence available for what this class of adapter tolerates.
    assert 7 * GIB < host.offload_budget_bytes < 9 * GIB


def test_a_dedicated_card_is_budgeted_close_to_its_real_memory() -> None:
    host = parse_survey(DEDICATED_SURVEY)
    assert host.offload_budget_bytes > 20 * GIB


# -- what a model needs -------------------------------------------------------


def test_a_small_file_holding_a_large_model_is_sized_by_its_parameters() -> None:
    """bonsai-27b is 27B in a 4.4 GB Q1_0 file, and the file lies.

    The runtime still allocates activations, KV cache and a vision projector
    for 27 billion parameters, which is what used to lose the Vulkan device.
    """
    assert estimated_working_set_bytes(int(4.4 * GIB), "27B") > 10 * GIB


def test_a_large_file_is_sized_by_the_file() -> None:
    assert estimated_working_set_bytes(int(16.5 * GIB), "27B") >= int(16.5 * GIB)


def test_an_unknown_size_is_not_treated_as_empty() -> None:
    assert estimated_working_set_bytes(None, "35B-A3B") > 0
    assert estimated_working_set_bytes(0, None) == 0


# -- the decision, on real models ---------------------------------------------

INTEGRATED = parse_survey(INTEGRATED_SURVEY)
DEDICATED = parse_survey(DEDICATED_SURVEY)
CPU_ONLY = parse_survey(CPU_ONLY_SURVEY)

# name, size, params, quant
CATALOGUE = [
    ("qwen3.5-0.8b", int(0.97 * GIB), "0.8B", "Q8_0", False),
    ("qwen3-vl-4b", int(3.1 * GIB), "4B", "Q4_K_M", False),
    ("ling-3.0-tiny", int(4.2 * GIB), "128x1.0B", "Q4_K_S", False),
    ("bonsai-27b", int(4.4 * GIB), "27B", "Q1_0", True),
    ("qwen3.8-27b", int(16.5 * GIB), "27B", "Q4_K_M", True),
    ("qwen3.6-35b-a3b", int(20.6 * GIB), "35B-A3B", "Q4_K_M", True),
]


def test_this_machine_still_gets_exactly_the_decisions_it_had() -> None:
    """The rewrite must not change what happens on the machine it was tuned on."""
    for name, size, params, quant, expected in CATALOGUE:
        assert requires_cpu_safe_profile(quant, size, params, INTEGRATED) is expected, name


def test_a_workstation_offloads_what_its_card_can_hold() -> None:
    decisions = {
        name: requires_cpu_safe_profile(quant, size, params, DEDICATED)
        for name, size, params, quant, _ in CATALOGUE
    }
    # The whole point of the change: 16.5 GB of model fits 24 GB of VRAM.
    assert decisions["qwen3.8-27b"] is False
    assert decisions["bonsai-27b"] is False
    assert decisions["qwen3.5-0.8b"] is False


def test_a_runtime_with_no_accelerator_keeps_everything_on_the_processor() -> None:
    for name, size, params, quant, _ in CATALOGUE:
        assert requires_cpu_safe_profile(quant, size, params, CPU_ONLY) is True, name


def test_an_iq_quant_is_only_held_back_where_it_was_seen_to_fail() -> None:
    """The IQ signal came from one integrated Vulkan driver, so it stays there."""
    small_iq = (int(2 * GIB), "3B", "IQ3_XS")
    assert requires_cpu_safe_profile(small_iq[2], small_iq[0], small_iq[1], INTEGRATED) is True
    assert requires_cpu_safe_profile(small_iq[2], small_iq[0], small_iq[1], DEDICATED) is False


def test_an_unknown_host_is_treated_as_the_careful_case() -> None:
    """Reading the machine can fail. Offloading blind is what breaks runs."""
    assert requires_cpu_safe_profile("Q4_K_M", int(20.6 * GIB), "35B-A3B", None) is True
