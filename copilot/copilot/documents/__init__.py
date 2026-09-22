"""Week 2: reading clinical documents (lab PDFs and intake forms) into strict schemas.

The contract is in schemas.py. An extracted fact is either supported, with a value and a
citation into the document, or unsupported, null with confidence 0. Nothing in between can
validate, which is what keeps a model's guess from ever reading as a fact.
"""
