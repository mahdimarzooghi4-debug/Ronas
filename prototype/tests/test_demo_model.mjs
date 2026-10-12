import test from "node:test";
import assert from "node:assert/strict";
import {
  DOMESTIC_STATES, EXPORT_STATES, initialDemoState, isDemoState, safeDemoState,
  prepareHouseholdDemo, requestHouseholdClarification, prepareExportResearchDemo,
  flagExportForReview, resetDemoState
} from "../ui/demo-model.mjs";

test("initial model contains only fake markers and no authorized actions", () => {
  const state = initialDemoState();
  assert.equal(state.household.ref, "DEMO-H01");
  assert.equal(state.research.source, "DEMO-SOURCE-01");
  assert.equal(state.version, 1);
  assert.equal(state.revision, 0);
  assert.equal(state.household.status, "NOT_STARTED");
  assert.equal(state.research.status, "NOT_STARTED");
  assert.ok(isDemoState(state));
});
test("household sample is always evidence-required, never accepted", () => {
  const state = prepareHouseholdDemo(initialDemoState());
  assert.equal(state.household.status, "DEMO_EVIDENCE_REQUIRED");
  assert.equal(state.research.status, "NOT_STARTED");
  assert.equal(state.revision, 1);
  assert.equal(initialDemoState().household.status, "NOT_STARTED");
  assert.ok(!("consentGranted" in state.household));
  assert.ok(!("expertApproved" in state.household));
});
test("review scenario only requests clarification and preserves export", () => {
  const state = prepareHouseholdDemo(initialDemoState());
  const review = requestHouseholdClarification(state);
  assert.equal(review.household.status, "DEMO_CLARIFICATION_REQUESTED");
  assert.equal(review.research.status, state.research.status);
  assert.equal(review.household.ref, state.household.ref);
  assert.equal(review.revision, 2);
});
test("household cannot transition without first preparing or twice", () => {
  assert.throws(() => requestHouseholdClarification(initialDemoState()), /DEMO_TRANSITION_NOT_AVAILABLE/);
  const state = prepareHouseholdDemo(initialDemoState());
  assert.throws(() => prepareHouseholdDemo(state), /DEMO_TRANSITION_NOT_AVAILABLE/);
});
test("research source never becomes verified or a buyer", () => {
  const state = prepareExportResearchDemo(initialDemoState());
  assert.equal(state.research.status, "DEMO_RIGHTS_UNVERIFIED");
  const review = flagExportForReview(state);
  assert.equal(review.research.status, "DEMO_REVIEW_REQUIRED");
  assert.equal(review.research.source, "DEMO-SOURCE-01");
  assert.ok(!("buyer" in review.research));
  assert.ok(!("license" in review.research));
  assert.ok(!("order" in review.research));
});
test("export has strictly guarded transitions", () => {
  assert.throws(() => flagExportForReview(initialDemoState()), /DEMO_TRANSITION_NOT_AVAILABLE/);
  const state = prepareExportResearchDemo(initialDemoState());
  assert.throws(() => prepareExportResearchDemo(state), /DEMO_TRANSITION_NOT_AVAILABLE/);
});
test("two flows are independent and preserve immutability", () => {
  const start = initialDemoState();
  const d = prepareHouseholdDemo(start);
  const e = prepareExportResearchDemo(d);
  assert.equal(start.household.status, "NOT_STARTED");
  assert.equal(d.research.status, "NOT_STARTED");
  assert.equal(e.household.status, "DEMO_EVIDENCE_REQUIRED");
  assert.equal(e.research.status, "DEMO_RIGHTS_UNVERIFIED");
  assert.notEqual(e, start);
  assert.equal(e.household, d.household); // untouched domain retains identity
});
test("strict browser session boundary rejects extra fields, real data and invalid statuses", () => {
  const base = initialDemoState();
  const invalid = [
    null, "", [], {}, { ...base, profile: { name: "Someone" } },
    { ...base, version: 2 },
    { ...base, revision: -1 },
    { ...base, household: { ...base.household, ref: "REAL-PERSON" } },
    { ...base, household: { ...base.household, consent: "Yes" } },
    { ...base, household: { ...base.household, status: "APPROVED" } },
    { ...base, research: { ...base.research, status: "BUYER_CONFIRMED" } },
    { ...base, research: { ...base.research, source: "http://market" } }
  ];
  for (const candidate of invalid) {
    assert.equal(isDemoState(candidate), false);
    assert.deepEqual(safeDemoState(candidate), base);
  }
});
test("reject malformed state and forbidden approval attempts", () => {
  assert.throws(() => prepareHouseholdDemo({}), /INVALID_SYNTHETIC_STATE/);
  assert.throws(() => flagExportForReview({}), /INVALID_SYNTHETIC_STATE/);
  assert.equal(DOMESTIC_STATES.includes("ACCEPTED"), false);
  assert.equal(EXPORT_STATES.includes("VERIFIED"), false);
  assert.equal(EXPORT_STATES.includes("CONTRACTED"), false);
});
test("reset discards synthetic session state only", () => {
  const altered = prepareHouseholdDemo(prepareExportResearchDemo(initialDemoState()));
  assert.deepEqual(resetDemoState(), initialDemoState());
  assert.notDeepEqual(altered, resetDemoState());
});
