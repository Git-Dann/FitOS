"""FitOS Temporal workers: ingestion, mapping and detectors.

Workflow bodies are deterministic — no wall-clock time, no randomness, no
I/O. Those belong in activities (docs/adr/0003-workflow-engine.md).

Phase A scaffolds the package only; the Temporal client, workflows and
activities land in Phase C.
"""

__version__ = "0.0.0"
