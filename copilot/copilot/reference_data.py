"""Versioned demo reference tables used by the deterministic rule engine.

These are *demo* tables reviewed for the synthetic dataset in this repository. They are
not a clinical knowledge base. Every flag derived from them is labelled with the table
version and the words "demo reference", never presented as coming from the record
(USER.md NG-7; PRD "Laboratory range" boundary; AUDIT D5).

Codes are the LOINC codes actually present in procedure_result (measured 2026-09-15).
"""

from __future__ import annotations

RULES_VERSION = "demo-rules-2026.09.1"

# LOINC code -> (low, high, unit). Adult, non-pregnant, general reference intervals as
# commonly printed on demo lab reports. Serum/plasma and whole-blood variants share limits.
REFERENCE_RANGES: dict[str, tuple[float, float, str]] = {
    # Basic metabolic panel (blood and serum variants)
    "2339-0": (70, 99, "mg/dL"), "2345-7": (70, 99, "mg/dL"),        # glucose (fasting)
    "6299-2": (7, 20, "mg/dL"), "3094-0": (7, 20, "mg/dL"),          # urea nitrogen
    "38483-4": (0.6, 1.2, "mg/dL"), "2160-0": (0.6, 1.2, "mg/dL"),   # creatinine
    "49765-1": (8.5, 10.5, "mg/dL"), "17861-6": (8.5, 10.5, "mg/dL"), # calcium
    "2947-0": (135, 145, "mmol/L"), "2951-2": (135, 145, "mmol/L"),  # sodium
    "6298-4": (3.5, 5.0, "mmol/L"), "2823-3": (3.5, 5.0, "mmol/L"),  # potassium
    "2069-3": (98, 107, "mmol/L"), "2075-0": (98, 107, "mmol/L"),    # chloride
    "20565-8": (22, 29, "mmol/L"), "2028-9": (22, 29, "mmol/L"),     # total CO2
    "33914-3": (60, 200, "mL/min/{1.73_m2}"),                        # eGFR (MDRD): low is the flag
    # Lipids
    "2093-3": (0, 200, "mg/dL"),   # total cholesterol
    "2571-8": (0, 150, "mg/dL"),   # triglycerides
    "18262-6": (0, 130, "mg/dL"),  # LDL (direct)
    "2085-9": (40, 100, "mg/dL"),  # HDL: low is the flag
    # CBC
    "718-7": (12.0, 17.5, "g/dL"),    # hemoglobin
    "4544-3": (36, 52, "%"),          # hematocrit
    "6690-2": (4.0, 11.0, "10*3/uL"), # leukocytes
    "777-3": (150, 450, "10*3/uL"),   # platelets
    "789-8": (4.0, 6.0, "10*6/uL"),   # erythrocytes
    "787-2": (80, 100, "fL"),         # MCV
    "785-6": (27, 33, "pg"),          # MCH
    "786-4": (32, 36, "g/dL"),        # MCHC
    # Hepatic
    "1742-6": (7, 56, "U/L"),        # ALT
    "1920-8": (10, 40, "U/L"),       # AST
    "6768-6": (44, 147, "U/L"),      # alkaline phosphatase
    "1975-2": (0.1, 1.2, "mg/dL"),   # total bilirubin
    "1751-7": (3.5, 5.0, "g/dL"),    # albumin
    "2885-2": (6.0, 8.3, "g/dL"),    # total protein
    # Coagulation and cardiac
    "5902-2": (11, 13.5, "s"),       # PT
    "6301-6": (0.8, 1.2, "{INR}"),   # INR
    "89204-2": (0, 4, "{score}"),    # PHQ-9 teen (screening cut-off, informational only)
    "89579-7": (0, 14, "pg/mL"),     # hs-troponin I
}

# Screening scores are not lab values: the engine reports them but never flags them.
SCREENING_SCORE_CODES = {"55758-7", "70274-6", "82667-7", "75626-2", "76504-0", "44261-6", "89204-2", "59460-6"}

# Recorded allergy -> drug name fragments that conflict with it. Matching is on the
# lower-cased medication name. "possible" marks a cross-reactivity, not a direct match.
ALLERGY_CLASSES: list[dict[str, object]] = [
    {"allergen": "penicillin", "class": "penicillins",
     "drugs": ["penicillin", "amoxicillin", "ampicillin", "clavulanate", "piperacillin", "dicloxacillin"], "possible": []},
    {"allergen": "sulfamethoxazole", "class": "sulfonamide antibiotics",
     "drugs": ["sulfamethoxazole", "sulfadiazine", "sulfasalazine"], "possible": []},
    {"allergen": "aspirin", "class": "salicylates",
     "drugs": ["aspirin", "salicyl"], "possible": ["ibuprofen", "naproxen", "ketorolac", "diclofenac"]},
    {"allergen": "cephalosporin", "class": "cephalosporins",
     "drugs": ["cefazolin", "cephalexin", "ceftriaxone", "cefuroxime"], "possible": ["penicillin", "amoxicillin"]},
]

# Reviewed interaction pairs for the demo. Each entry: primary drug fragment, list of
# partner fragments, recorded classification. The classification is displayed as
# recorded; the engine never recommends stopping or changing a medication.
INTERACTION_PAIRS: list[dict[str, object]] = [
    {"id": "IX-1", "drug": "clopidogrel", "partners": ["naproxen", "ibuprofen", "aspirin", "ketorolac"],
     "classification": "moderate", "note": "antiplatelet + NSAID/salicylate: additive bleeding risk"},
    {"id": "IX-2", "drug": "lisinopril", "partners": ["naproxen", "ibuprofen", "ketorolac", "spironolactone", "potassium"],
     "classification": "moderate", "note": "ACE inhibitor + NSAID or potassium-sparing agent: renal function / potassium"},
    {"id": "IX-3", "drug": "simvastatin", "partners": ["amlodipine"],
     "classification": "moderate", "note": "simvastatin with amlodipine: labelled simvastatin dose limit of 20 mg/day"},
]

# Daily-dose thresholds (mg/day) for two or three demo medications. The engine needs
# strength (from the drug name), units per dose (dosage) and a frequency (interval);
# when any is missing it returns "unable to evaluate" rather than guessing.
DOSE_THRESHOLDS_MG_PER_DAY: dict[str, float] = {
    "acetaminophen": 4000,
    "ibuprofen": 3200,
    "metformin": 2550,
}

# OpenEMR drug_interval option_id -> doses per day (None: cannot be converted).
INTERVAL_DOSES_PER_DAY: dict[str, float | None] = {
    "0": None, "1": 2, "2": 3, "3": 4, "4": 8, "5": 6, "6": None, "7": 4, "8": 3, "9": 1,
    "10": None, "11": None, "12": 1, "13": 1, "14": None, "15": 24, "16": 1, "17": None,
    "18": None, "19": 1 / 7, "20": 1 / 30,
}

# CVX codes counted as seasonal influenza vaccine (for the compliance signal).
INFLUENZA_CVX = {"140", "141", "150", "158", "161", "168", "171", "185", "186", "197", "205"}

# SNOMED problem titles that mean "a review is due" in this dataset (compliance signal).
REVIEW_DUE_PATTERNS = ("review due", "screening due", "follow-up due")
