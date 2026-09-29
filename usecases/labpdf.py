"""Build a lab report PDF naming a given patient, for the live document tests.

The committed eval fixture names a fictional patient. That is right for the gate, where no chart
is involved, and wrong for a live test that files the document under a real one: the module reads
the name printed on a report and refuses to file a document that names someone else. A test that
means to exercise the persist path therefore has to hand it a report that names the patient it is
filed under -- otherwise it only ever exercises the refusal, and would go on passing while the
thing it was written to check quietly stopped happening.

The PDF shape is the fixtures' own, reused rather than copied, so what these tests feed the model
is what the gate's cases were recorded from.
"""

import sys
from pathlib import Path

from conftest import db_query

FIXTURES = Path(__file__).resolve().parent.parent / "copilot" / "evals" / "stage2" / "fixtures" / "documents"
sys.path.insert(0, str(FIXTURES))

from make_fixtures import build_pdf  # noqa: E402


def patient_name(pid: int) -> str:
    return db_query(f"SELECT CONCAT(fname, ' ', lname) FROM patient_data WHERE pid = {pid}")[0][0]


def lab_report(pid: int, provider: str = "Dana Reyes") -> bytes:
    """A two-page report for this patient: three results on page 1, two on page 2."""
    name = patient_name(pid)
    header = "Test                    Result      Units      Reference Range    Flag"
    return build_pdf([
        [
            "METRO CLINICAL LABS", "1200 Harbor Street, Springfield", "LABORATORY REPORT",
            "",
            f"Patient: {name}        DOB: 1981-07-04        Sex: M",
            f"Ordering provider: {provider}",
            "Collected: 2026-09-17 08:10        Reported: 2026-09-18 14:22",
            "Specimen: Serum        Accession: MCL-26-118204",
            "",
            header,
            "Potassium               5.4         mmol/L     3.5-5.0            H",
            "Sodium                  140         mmol/L     135-145",
            "Creatinine              1.3         mg/dL      0.6-1.2            H",
            "",
            "Continued on page 2",
        ],
        [
            f"METRO CLINICAL LABS        {name}        Accession: MCL-26-118204        Page 2",
            "",
            header,
            "Glucose                 112         mg/dL      70-99              H",
            "Hemoglobin A1c          7.4         %          4.0-5.6            H",
            "",
            "Comment: Hemolysis index within limits.",
            "Reviewed by: Metro Clinical Labs, CLIA 99D9999999",
            "End of report",
        ],
    ])
