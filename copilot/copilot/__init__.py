"""Clinical Co-Pilot agent: a patient-scoped, evidence-grounded assistant for hospitalists.

The package is deliberately small and legible. Each module is explainable in a sentence:

- schemas.py        typed contracts: the chart the PHP gateway sends, claims, citations, response states
- config.py         settings and the model-provider allowlist (fail closed)
- reference_data.py versioned demo tables: lab reference ranges, allergy classes, interaction pairs, dose limits
- normalize.py      turns raw records into what the model may see (status from dates, de-duplication, "none recorded")
- constraints.py    the bounded deterministic rule engine (pass / flag / unable to evaluate / engine failure)
- tools.py          typed, patient-scoped tools the model can call
- verify.py         the claim verifier: every displayed claim must cite a record of the active patient
- agent.py          brief generation and the follow-up loop (max 5 iterations)
- session.py        per-user session memory with prefetch, bound to user and patient, expiring
- telemetry.py      PHI-safe structured events, correlation IDs, LangSmith tracing
- service/app.py    the FastAPI gateway the OpenEMR module calls over the private network
"""

__version__ = "0.1.0"
