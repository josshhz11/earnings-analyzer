"""CLI entry point for the Earnings Analyzer pipeline.

This is the personal inspection tool for stepping through each pipeline stage
(ingestion -> extraction -> eval -> revision -> report) — see CLAUDE.md's core
engineering principles ("Personal inspection tooling before any UI").

Status: stub. No pipeline logic yet — this is scaffolding only (Prompt 0).
Implementation starts with Phase 1 of memory/ROADMAP.md, beginning with
deterministic ingestion (Prompt 2).
"""

import argparse


def main() -> None:
    """Parse CLI args and dispatch to pipeline stages. Not yet implemented."""
    parser = argparse.ArgumentParser(
        description="Run the Earnings Analyzer pipeline on a transcript."
    )
    parser.add_argument("--input", type=str, required=True, help="Path to input transcript PDF.")
    parser.parse_args()
    raise NotImplementedError(
        "Pipeline not implemented yet — scaffolding only. See memory/STATE.md for next steps."
    )


if __name__ == "__main__":
    main()
