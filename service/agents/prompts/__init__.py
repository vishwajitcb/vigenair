"""Per-agent prompts for the v2 variant-construction chain.

Each module exports an `assemble(...)` helper that returns a fully-substituted
prompt string. Prompts are deliberately small and focused — each agent has
one job and is asked exactly one question.
"""
