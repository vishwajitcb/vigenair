"""LangGraph-based variant generation pipeline.

Replaces the legacy 2-pass monolith in api/routes/segments.py:generate_variants
with a state machine of specialized agents:

    HookScout (LLM) -> HookSelector (Python) -> VariantBuilder (LLM, fan-out)
        -> Auditor (LLM, fan-out) -> Normalizer (Python) -> Validator (Python)

Toggled by config.USE_LANGGRAPH. The legacy path remains the default.

Public entry point: agents.runner.run_variant_pipeline.
"""
