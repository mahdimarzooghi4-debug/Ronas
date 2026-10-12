"""LOCAL/TEST version witnesses; sources own revisions, not Ronas."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
from .scoped_drafts import _synthetic_ref, _synthetic_subject

VERSION = "ronas.domestic.synthetic-external-authority-witness.v0"
SCIENCE = "SCIENCE_SOURCE_CANDIDATES"
SPECIALIST = "SPECIALIST_EVIDENCE_CANDIDATES"
ASSIGNMENT = "CASE_ASSIGNMENT"
KINDS = (SCIENCE, SPECIALIST, ASSIGNMENT)

@dataclass(frozen=True, slots=True)
class SyntheticAuthorityWitness:
    kind: str
    subject: str
    case_ref: str
    case_version: int
    generation: int

    def __post_init__(self):
        if (self.kind not in KINDS
            or not _synthetic_subject(self.subject)
            or not _synthetic_ref(self.case_ref)
            or type(self.case_version) is not int or self.case_version < 1
            or type(self.generation) is not int or self.generation < 0):
            raise ValueError("invalid case-scoped source revision")

def validate_witness_vector(vector, *, subject, case_ref, case_version):
    if (type(vector) is not tuple or len(vector) != 3
        or not _synthetic_subject(subject) or not _synthetic_ref(case_ref)
        or type(case_version) is not int or case_version < 1):
        raise ValueError("invalid authority revision vector")
    for witness, kind in zip(vector, KINDS):
        if (not isinstance(witness, SyntheticAuthorityWitness)
            or witness.kind != kind
            or (witness.subject,witness.case_ref,witness.case_version)
               != (subject,case_ref,case_version)):
            raise ValueError("cross-source or cross-case authority witness")
    return vector

def compare_authority_vectors(first,second,*,subject,case_ref,case_version):
    validate_witness_vector(first,subject=subject,case_ref=case_ref,case_version=case_version)
    validate_witness_vector(second,subject=subject,case_ref=case_ref,case_version=case_version)
    if first!=second:
        raise ValueError("in-flight authority generation changed, including ABA")

def versioned_context_fingerprint(*,context_fingerprint,vector,subject,case_ref,case_version):
    validate_witness_vector(vector,subject=subject,case_ref=case_ref,case_version=case_version)
    if (type(context_fingerprint) is not str or len(context_fingerprint)!=64
        or any(c not in "0123456789abcdef" for c in context_fingerprint)):
        raise ValueError("invalid base context identity")
    payload={
        "contract":VERSION,"scope":("DOMESTIC",subject,case_ref,case_version),
        "structural":context_fingerprint,
        "provider_revisions":[(w.kind,w.generation) for w in vector],
    }
    return sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),
                             ensure_ascii=True).encode("ascii")).hexdigest()
