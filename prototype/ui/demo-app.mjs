/* Local-only, synthetic simulator. No fetch, API, free-form input or IAM. */
import {
  DEMO_STORAGE_KEY, safeDemoState, initialDemoState,
  prepareHouseholdDemo, requestHouseholdClarification,
  prepareExportResearchDemo, flagExportForReview, resetDemoState
} from "./demo-model.mjs";

let memoryState = initialDemoState();
let storageAvailable = false;
try {
  const testKey = DEMO_STORAGE_KEY + ":test";
  window.sessionStorage.setItem(testKey, "1");
  window.sessionStorage.removeItem(testKey);
  storageAvailable = true;
} catch {
  storageAvailable = false;
}
function readState() {
  if (!storageAvailable) return memoryState;
  try {
    const raw = window.sessionStorage.getItem(DEMO_STORAGE_KEY);
    if (raw === null || raw.length > 2000) return initialDemoState();
    return safeDemoState(JSON.parse(raw));
  } catch {
    return initialDemoState();
  }
}
function writeState(next) {
  const state = safeDemoState(next);
  memoryState = state;
  if (storageAvailable) {
    try {
      window.sessionStorage.setItem(DEMO_STORAGE_KEY, JSON.stringify(state));
    } catch {
      storageAvailable = false;
    }
  }
}
const householdMessages = {
  NOT_STARTED: "هنوز پیش‌نویس نمونه‌ای ایجاد نشده است.",
  DEMO_EVIDENCE_REQUIRED: "پیش‌نویس ساختگی آماده شد؛ برای ثبت واقعی، رضایت و مستندات معتبر لازم است.",
  DEMO_CLARIFICATION_REQUESTED: "در نمونه، نیاز به اصلاح اطلاعات علامت‌گذاری شد؛ هیچ تأیید تخصصی صادر نشده است."
};
const researchMessages = {
  NOT_STARTED: "هنوز پرونده پژوهش نمونه‌ای ایجاد نشده است.",
  DEMO_RIGHTS_UNVERIFIED: "پژوهش نمونه ایجاد شد؛ حق استفاده از منبع و اعتبار داده تأیید نشده‌اند.",
  DEMO_REVIEW_REQUIRED: "پرونده نمونه برای بازبینی انسانی علامت‌گذاری شد؛ نتیجه تجاری تأیید نشده است."
};
const actions = Object.freeze({
  "household-prepare": prepareHouseholdDemo,
  "domestic-clarify": requestHouseholdClarification,
  "export-prepare": prepareExportResearchDemo,
  "export-flag": flagExportForReview,
  "demo-reset": resetDemoState
});
function writeText(selector, value) {
  document.querySelectorAll(selector).forEach(element => {
    element.textContent = value;
  });
}
function render() {
  const state = readState();
  writeText("[data-demo-household-status]", householdMessages[state.household.status]);
  writeText("[data-demo-export-status]", researchMessages[state.research.status]);
  writeText("[data-demo-revision]", "نسخه آزمایشی: " + state.revision);
  document.querySelectorAll("[data-demo-action]").forEach(button => {
    const action = button.getAttribute("data-demo-action");
    if (action === "household-prepare") button.disabled = state.household.status !== "NOT_STARTED";
    if (action === "domestic-clarify") button.disabled = state.household.status !== "DEMO_EVIDENCE_REQUIRED";
    if (action === "export-prepare") button.disabled = state.research.status !== "NOT_STARTED";
    if (action === "export-flag") button.disabled = state.research.status !== "DEMO_RIGHTS_UNVERIFIED";
  });
}
document.querySelectorAll("[data-demo-action]").forEach(button => {
  button.addEventListener("click", () => {
    const action = button.getAttribute("data-demo-action");
    const operation = Object.prototype.hasOwnProperty.call(actions, action) ? actions[action] : null;
    if (!operation) return;
    try {
      writeState(operation(readState()));
      writeText("[data-demo-error]", "");
    } catch {
      writeText("[data-demo-error]", "این تغییر برای وضعیت فعلی نمونه مجاز نیست. داده واقعی یا تأییدی ثبت نشده است.");
    }
    render();
  });
});
window.addEventListener("pageshow", render);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) render();
});
writeText("[data-demo-storage-note]", storageAvailable
  ? "وضعیت صرفاً ساختگی در حافظه موقت همین نشست مرورگر نگهداری می‌شود."
  : "ذخیره مرورگر در دسترس نیست؛ این صفحه فقط وضعیت همین تب را نشان می‌دهد.");
render();
