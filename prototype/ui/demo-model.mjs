/* Ronas locally simulated drafts. Not a production model, permission service,
   consent receipt, real household record, export data or legal review. */
export const DEMO_STORAGE_KEY = "ronas:synthetic-session:v1";
const VERSION = 1;
export const DOMESTIC_STATES = Object.freeze(["NOT_STARTED", "DEMO_EVIDENCE_REQUIRED", "DEMO_CLARIFICATION_REQUESTED"]);
export const EXPORT_STATES = Object.freeze(["NOT_STARTED", "DEMO_RIGHTS_UNVERIFIED", "DEMO_REVIEW_REQUIRED"]);

export function initialDemoState() {
  return {
    version: VERSION,
    household: { ref: "DEMO-H01", status: "NOT_STARTED" },
    research: { ref: "DEMO-E01", source: "DEMO-SOURCE-01", status: "NOT_STARTED" },
    revision: 0
  };
}
function isExactObject(value, keys) {
  return value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).length === keys.length &&
    keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
}
export function isDemoState(state) {
  return isExactObject(state, ["version", "household", "research", "revision"]) &&
    state.version === VERSION &&
    Number.isSafeInteger(state.revision) && state.revision >= 0 && state.revision < 100000 &&
    isExactObject(state.household, ["ref", "status"]) && state.household.ref === "DEMO-H01" &&
    DOMESTIC_STATES.includes(state.household.status) &&
    isExactObject(state.research, ["ref", "source", "status"]) &&
    state.research.ref === "DEMO-E01" && state.research.source === "DEMO-SOURCE-01" &&
    EXPORT_STATES.includes(state.research.status);
}
export function safeDemoState(candidate) {
  // Fail closed rather than restoring arbitrary browser-stored user data.
  return isDemoState(candidate) ? candidate : initialDemoState();
}
function transition(state, namespace, expectedState, nextState) {
  if (!isDemoState(state)) throw new Error("INVALID_SYNTHETIC_STATE");
  if (state[namespace].status !== expectedState) throw new Error("DEMO_TRANSITION_NOT_AVAILABLE");
  if (state.revision >= 99999) throw new Error("DEMO_REVISION_LIMIT");
  return {
    ...state,
    [namespace]: { ...state[namespace], status: nextState },
    revision: state.revision + 1
  };
}
export function prepareHouseholdDemo(state) {
  // No collected input, no legal consent verification, never Accepted.
  return transition(state, "household", "NOT_STARTED", "DEMO_EVIDENCE_REQUIRED");
}
export function requestHouseholdClarification(state) {
  // An unverified demo action is NOT an authorized staff review.
  return transition(state, "household", "DEMO_EVIDENCE_REQUIRED", "DEMO_CLARIFICATION_REQUESTED");
}
export function prepareExportResearchDemo(state) {
  // A fixed fake source is not a source license or market demand.
  return transition(state, "research", "NOT_STARTED", "DEMO_RIGHTS_UNVERIFIED");
}
export function flagExportForReview(state) {
  // Never VERIFIED or APPROVED; only labels an offline case for review.
  return transition(state, "research", "DEMO_RIGHTS_UNVERIFIED", "DEMO_REVIEW_REQUIRED");
}
export function resetDemoState() {
  return initialDemoState();
}
