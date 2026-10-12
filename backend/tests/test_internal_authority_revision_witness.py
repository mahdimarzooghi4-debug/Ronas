"""Case-scoped externally owned monotonic witness and ABA tests."""
from dataclasses import FrozenInstanceError,replace
import unittest
from ronas_api.internal_authority_revision_witness import (
    SCIENCE,SPECIALIST,ASSIGNMENT,SyntheticAuthorityWitness,
    validate_witness_vector,compare_authority_vectors,versioned_context_fingerprint,
)
ACTOR="synthetic-agronomy-one"
CASE="DEMO-D-1"
def make(a=0,b=0,c=0):
    return tuple(SyntheticAuthorityWitness(kind,ACTOR,CASE,3,rev)
                 for kind,rev in zip((SCIENCE,SPECIALIST,ASSIGNMENT),(a,b,c)))

class VersionedWitnessTests(unittest.TestCase):
    def test_stable_witnesses_match(self):
        a=make(1,2,3)
        compare_authority_vectors(a,a,subject=ACTOR,case_ref=CASE,case_version=3)
        self.assertEqual(validate_witness_vector(a,subject=ACTOR,case_ref=CASE,
                                                 case_version=3),a)

    def test_aba_reversion_changes_identity_even_if_structural_data_equal(self):
        original=make(1,2,3)
        aba=make(3,4,5)
        with self.assertRaises(ValueError):
            compare_authority_vectors(original,aba,subject=ACTOR,
                                      case_ref=CASE,case_version=3)
        old=versioned_context_fingerprint(context_fingerprint="a"*64,
            vector=original,subject=ACTOR,case_ref=CASE,case_version=3)
        new=versioned_context_fingerprint(context_fingerprint="a"*64,
            vector=aba,subject=ACTOR,case_ref=CASE,case_version=3)
        self.assertNotEqual(old,new)

    def test_each_independent_counter_invalidates_prior_versioned_hash(self):
        base=make(1,1,1)
        old=versioned_context_fingerprint(context_fingerprint="a"*64,
             vector=base,subject=ACTOR,case_ref=CASE,case_version=3)
        for newer in (make(2,1,1),make(1,2,1),make(1,1,2)):
            with self.subTest(newer=newer):
                self.assertNotEqual(old,versioned_context_fingerprint(
                    context_fingerprint="a"*64,vector=newer,
                    subject=ACTOR,case_ref=CASE,case_version=3))

    def test_invalid_shape_scope_boolean_and_kind_fail_closed(self):
        base=make(1,2,3)
        wrong=(base[:-1],tuple(reversed(base)),
               (replace(base[0],case_ref="DEMO-D-2"),*base[1:]),
               (replace(base[0],kind=ASSIGNMENT),*base[1:]),
               [*base])
        for vector in wrong:
            with self.subTest(vector=vector),self.assertRaises(ValueError):
                compare_authority_vectors(base,vector,
                    subject=ACTOR,case_ref=CASE,case_version=3)
        for value in (True,False,-1,"1",None):
            with self.subTest(value=value),self.assertRaises(ValueError):
                SyntheticAuthorityWitness(SCIENCE,ACTOR,CASE,3,value)
        with self.assertRaises(FrozenInstanceError):
            base[0].generation=17
        with self.assertRaises(ValueError):
            versioned_context_fingerprint(context_fingerprint="Z"*64,
                vector=base,subject=ACTOR,case_ref=CASE,case_version=3)
