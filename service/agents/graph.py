"""LangGraph wiring for the variant-generation pipeline.

Linear pipeline (no branches, no loops at the graph level — the per-variant
judge retry loop is internal to the variant_pipeline node):

    HookScout -> HookSelector -> VariantPipeline -> CrossVariantValidator -> END

The variant_pipeline node runs the full per-variant chain — Analyst → Story
→ Cliffhanger → CutEditor → Judge (with one retry) → Auditor → Normalizer
→ per-variant duration check → push to MongoDB — in parallel across all
seeded variants via asyncio.gather. Each surviving variant lands in Mongo
the moment it's ready, so the polling frontend sees them appear live.

The cross_variant_validator runs once at the end to drop dupes by
hook_scene or angle (the only check that needs a global view).
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes.cross_variant_validator import cross_variant_validator
from .nodes.hook_scout import hook_scout
from .nodes.hook_selector import hook_selector
from .nodes.variant_pipeline import variant_pipeline
from .state import PipelineState


def build_graph():
    """Compile and return the variant-generation graph."""
    graph = StateGraph(PipelineState)

    graph.add_node("hook_scout", hook_scout)
    graph.add_node("hook_selector", hook_selector)
    graph.add_node("variant_pipeline", variant_pipeline)
    graph.add_node("cross_variant_validator", cross_variant_validator)

    graph.set_entry_point("hook_scout")
    graph.add_edge("hook_scout", "hook_selector")
    graph.add_edge("hook_selector", "variant_pipeline")
    graph.add_edge("variant_pipeline", "cross_variant_validator")
    graph.add_edge("cross_variant_validator", END)

    return graph.compile()
