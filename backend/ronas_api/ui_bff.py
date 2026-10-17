Warning: truncated output (original token count: 69078)
Total output lines: 4918

"""Two authenticated, strictly role-scoped HTML shells for opt-in Keycloak BFF.

The default production entrypoint never mounts these routes. The HTML is
rendered from fixed templates, not client-supplied text or arbitrary files.
No live workflow or personal data exists in this UI foundation.
"""
from collections.abc import Callable
from html import escape
from urllib.parse import quote, parse_qs
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
import sqlite3

from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, JSONResponse, Response

from .auth import InvalidToken, Principal
from .human_review_sqlite import SqliteSyntheticHumanReviewLedger, STATES as TECHNICAL_STATES
from .export_research_evidence import ExportEvidenceReferenceConflict
from .export_research_findings import ExportResearchFindingConflict
from .postgres_export_findings import ExportFindingStorageError
from .export_research_packet import (
    ExportResearchPacketConflict, ExportResearchPacketIntegrityError,
    build_export_research_packet,
)
from .export_source_connector import (
    ExportSourceConnectorRegistry, ExportSourceConnectorUnavailable,
    capture_export_source_reference,
)
from .scoped_drafts import _synthetic_ref
from .scoped_audit import GrantConflict, GrantNotAuthorized
from .export_research_evidence import valid_evidence_refs, valid_snapshot_digest
from .grant_ledger_sqlite import LedgerIntegrityError, SqliteSyntheticGrantLedger
from .household_input_ledger_sqlite import (
    InputRevisionConflict, SqliteSyntheticHouseholdInputLedger,
)
from .household_input_profiles import (
    HouseholdInputSchema, SqliteSyntheticHouseholdProfileLedger,
)
from .export_research_question import (
    ExportResearchQuestionConflict, valid_question_refs,
)
from .oidc_browser import BrowserOIDC
from .financial_source_arithmetic import source_arithmetic
from .operational_readiness import readiness, verify_decision_sources
from .case_journey_guidance import (
    JourneyEvidenceMismatch, owner_next_action, expert_next_action,
    export_next_action,
)
from .business_gate_evidence import (BUSINESS_SOURCE_SHA, dossier_detail,
                                     visible_dossiers, verify_pinned_business_sources,
                                     BusinessSourceSnapshotError, SOURCE_INTEGRITY_STATE)
from .shared_workspaces import USER_ROLES, visible_user_workspaces
from .agronomy_workspace import SyntheticAgronomyWorkspace
from .expert_review_questions_sqlite import (
    ReviewQuestionConflict, SqliteSyntheticExpertQuestionLedger,
)
from .export_supplier_workspace import (
    SyntheticSupplierUnavailable, SyntheticSupplierWorkspace,
)
from .domestic_partner_workspace import (
    FIELDS as DOMESTIC_PARTNER_FIELDS, SyntheticDomesticPartnerUnavailable,
    SyntheticDomesticPartnerWorkspace,
)
from .domestic_stage_observation import (
    CurrentStageContext, StageObservationCommand, StageObservationConflict,
)
from .stage_observation_artifacts import (
    MAX_ARTIFACT_BYTES, StageArtifactStore, StageArtifactStoreError,
    _check_upload_size, _declared_upload_size,
)
from .domestic_preparation_preview import (
    REVIEW_STATES, domestic_preparation_preview,
)
from .gate_evidence_handoff_sqlite import SqliteSyntheticGateEvidenceHandoff
from .gate_evidence_authority_enquiry_sqlite import SqliteSyntheticAuthorityEnquiryLedger
from .domestic_surplus_publication_api import publication_readiness_snapshot
from .domestic_surplus_drafts import (
    SurplusDraftConflict, SurplusDraftIntegrityError, SurplusDraftLedger,
    SurplusDraftStorageError,
    is_surplus_draft_ledger,
)
from .domestic_surplus_producer_consent import (
    ProducerConsentConflict, ProducerConsentIntegrityError,
    ProducerConsentLedger, is_producer_consent_ledger,
)
ADMIN_ROLES = {
    "domestic_ops": "عملیات داخلی",
    "export_ops": "عملیات صادرات",
    "finance": "مالی",
    "governance": "راهبری",
}
STYLE = Path(__file__).resolve().parents[2] / "prototype" / "ui" / "styles.css"

LOGOUT_SCRIPT = """document.addEventListener('DOMContentLoaded', () => {
  const button = document.getElementById('ronas-logout');
  if (!button) return;
  const retryMessage = 'نشست به‌روزرسانی نشد؛ برای ادامه دوباره وارد شوید.';
  const scheduleRenewal = async () => {
    try {
      const status = await fetch('/api/auth/session', {credentials:'same-origin', cache:'no-store'});
      if (!status.ok) return;
      const current = await status.json();
      const delay = Math.max(5000, current.expires_at * 1000 - Date.now() - 60000);
      window.setTimeout(async () => {
        try {
          const renewed = await fetch('/api/auth/refresh', {
            method:'POST', credentials:'same-origin', cache:'no-store',
            headers:{'X-CSRF-Token':current.csrf}
          });
          if (renewed.status === 409) { window.setTimeout(scheduleRenewal, 2000); return; }
          if (!renewed.ok) throw Error('SESSION_REFRESH_REJECTED');
          scheduleRenewal();
        } catch {
          const notice = document.getElementById('logout-message');
          if (notice) notice.textContent = retryMessage;
        }
      }, delay);
    } catch {
      const notice = document.getElementById('logout-message');
      if (notice) notice.textContent = retryMessage;
      window.setTimeout(scheduleRenewal, 20000);
    }
  };
  scheduleRenewal();
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const status = await fetch('/api/auth/session', {credentials:'same-origin', cache:'no-store'});
      if (!status.ok) throw Error('NO_ACTIVE_SESSION');
      const data = await status.json();
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = '/api/auth/logout/keycloak';
      form.hidden = true;
      const csrf = document.createElement('input');
      csrf.type = 'hidden';
      csrf.name = 'csrf';
      csrf.value = data.csrf;
      form.appendChild(csrf);
      document.body.appendChild(form);
      form.requestSubmit();
    } catch {
      button.disabled = false;
      const notice = document.getElementById('logout-message');
      if (notice) notice.textContent = 'خروج تأیید نشد؛ نشست را بسته فرض نکنید.';
    }
  });
});"""

STAGE_UPLOAD_SCRIPT = r"""document.addEventListener('submit', async event => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.hasAttribute('data-stage-upload')) return;
  event.preventDefault();
  const fileInput = form.querySelector('input[type=file]');
  const digestInput = form.querySelector('input[name=artifact_digest]');
  const notice = form.querySelector('[data-upload-status]');
  const button = form.querySelector('button[type=submit]');
  const file = fileInput && fileInput.files && fileInput.files[0];
  const say = text => { if (notice) notice.textContent = text; };
  const safeFailure = async response => {
    let detail = '';
    try { detail = (await response.json()).detail || ''; } catch {}
    if (response.status === 401) return 'نشست شما معتبر نیست؛ دوباره وارد شوید.';
    if (response.status === 403) return 'درخواست از نظر امنیتی تأیید نشد؛ صفحه را تازه کنید.';
    if (response.status === 409) return 'اطلاعات پرونده یا طرح تغییر کرده؛ صفحه را تازه کنید.';
    if (response.status === 413 || detail === 'STAGE_ARTIFACT_TOO_LARGE')
      return 'حجم فایل از سقف ۸ مگابایت بیشتر است.';
    if (response.status === 422) return 'نوع یا محتوای فایل پذیرفته نشد.';
    return 'ثبت انجام نشد؛ وضعیت پرونده را تازه کنید و دوباره تلاش کنید.';
  };
  if (!file || !digestInput) { say('ابتدا یک فایل تصویر یا PDF انتخاب کنید.'); return; }
  if (file.size < 1 || file.size > 8 * 1024 * 1024) { say('اندازه فایل باید حداکثر ۸ مگابایت باشد.'); return; }
  if (!['image/jpeg','image/png','image/webp','application/pdf'].includes(file.type)) {
    digestInput.value = '';
    say('فقط فایل JPEG، PNG، WebP یا PDF پذیرفته می‌شود.');
    return;
  }
  digestInput.value = '';
  if (button) button.disabled = true;
  say('فایل در حال بارگذاری است…');
  try {
    const get = name => form.elements.namedItem(name).value;
    const uploaded = await fetch(form.dataset.uploadUrl, {
      method:'PUT', credentials:'same-origin', cache:'no-store', body:file,
      headers:{'Content-Type':file.type, 'X-CSRF-Token':get('csrf'),
        'X-Ronas-Case-Version':get('case_version'),
        'X-Ronas-Input-Revision':get('input_revision'),
        'X-Ronas-Plan-Digest':get('plan_digest'), 'X-Ronas-Stage-Ref':get('stage_ref'),
        'X-Ronas-Requirements-Digest':get('requirements_digest')}
    });
    if (!uploaded.ok) throw Error(await safeFailure(uploaded));
    const artifact = await uploaded.json();
    if (!/^[0-9a-f]{64}$/.test(artifact.digest) || artifact.byte_length !== file.size
        || artifact.content_type !== file.type || artifact.stored !== true)
      throw Error('پاسخ امن بارگذاری فایل معتبر نیست؛ دوباره تلاش کنید.');
    digestInput.value = artifact.digest;
    const fields = new URLSearchParams();
    for (const [key, value] of new FormData(form).entries())
      if (typeof value === 'string') fields.append(key, value);
    const saved = await fetch(form.action, {
      method:'POST', credentials:'same-origin', cache:'no-store',
      headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:fields
    });
    if (!saved.ok) throw Error(await safeFailure(saved));
    window.location.assign(saved.url);
  } catch (error) {
    say(error instanceof Error && error.message
      ? error.message : 'ثبت انجام نشد؛ وضعیت پرونده را تازه کنید و دوباره تلاش کنید.');
    if (button) button.disabled = false;
  }
});
document.addEventListener('change', event => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || input.type !== 'file') return;
  const form = input.form;
  if (!(form instanceof HTMLFormElement) || !form.hasAttribute('data-stage-upload')) return;
  const digest = form.querySelector('input[name=artifact_digest]');
  const notice = form.querySelector('[data-upload-status]');
  if (digest) digest.value = '';
  if (notice) notice.textContent = '';
});"""

def page(title: str, body: str, *, logged_in: bool, code: int = 200,
         local_test_form: bool = False,
         login_return_path: str = "/",
         stage_upload_script: bool = False) -> HTMLResponse:
    logout = (
        '<button type="button" id="ronas-logout">خروج امن</button>'
        '<p id="logout-message" role="status" aria-live="polite"></p>'
        if logged_in else (
            '<a class="btn" href="/api/auth/start?return_to='
            + quote(login_return_path, safe='') + '">ورود با Keycloak</a>'
        )
    )
    html = ('<!doctype html><html lang="fa" dir="rtl"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>' + escape(title) + '</title>'
            '<link rel="stylesheet" href="/assets/ronas.css">'
            '</head><body><header class="top"><a class="brand" href="/">روناس</a>'
            '<nav aria-label="دو محیط روناس"><a href="/">روناس</a>'
            '<a href="/admin">مدیریت روناس</a></nav></header>'
            '<div class="demo"><strong>نسخه آزمایشی</strong> · همه اطلاعات نمونه هستند؛ '
            'هیچ عملیات مالی، صادرات، ثبت‌نام یا تأیید علمی انجام نمی‌شود.</div>'
            '<main class="wrap" id="main"><h1>' + escape(title) + '</h1>'
            + body + '<section class="section">' + logout + '</section></main>'
            '<script src="/assets/ronas-auth.js" defer></script>'
            + ('<script src="/assets/ronas-stage-observation-upload.js" defer></script>'
               if stage_upload_script else '')
            + '</body></html>')
    response = HTMLResponse(html, status_code=code)
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; base-uri 'none'; form-action "
        + ("'self'" if local_test_form else "'none'")
        + "; frame-ancestors 'none'; object-src 'none'"
    )
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    return response



def readonly_domestic_preparation_html(preparation: dict) -> str:
    """One safe DEMO field display, shared by owner and assigned expert."""
    slots = (
        ("محصول", "crop"), ("مساحت", "growing_area"),
        ("آب", "water"), ("خاک", "soil"), ("موقعیت", "location"),
    )
    # Deliberately only accept the pure LOCAL/TEST unknown-input contract;
    # this renderer must never become a raw-input or advisory renderer.
    if (preparation["input_state"] != "NOT_RECORDED_IN_DEMO"
            or any(preparation["cultivation_inputs"][key] is not None
                   for _, key in slots)
            or preparation["plan_state"] != "NOT_AUTHORED"
            or preparation["business_actions_enabled"] is not False):
        raise ValueError("unapproved cultivation preparation display state")
    events = preparation["technical_timeline"]
    if not isinstance(events, list):
        raise ValueError("invalid technical timeline")
    try:
        recorded = tuple(
            event["technical_event"] for event in events
        )
        expected = domestic_preparation_preview(
            case_version=preparation["case_version"],
            review_revision=preparation["review_revision"],
            technical_review_state=preparation["technical_review_state"],
            valid_review_states=REVIEW_STATES,
            observed_review_steps=recorded,
        )
        if preparation != expected:
            raise ValueError("unexpected display snapshot")
    except (TypeError, KeyError, AttributeError) as exc:
        raise ValueError("invalid technical timeline") from exc
    labels = {
        "TECH_REVIEW_REQUESTED":
            "درخواست بررسی فنی ثبت شده؛ این مرحله تأیید علمی نیست.",
        "TECH_HUMAN_RESPONSE_RECORDED":
            "مرجع پاسخ فنی ثبت شده؛ طرح کشت تأیید نشده است.",
    }
    history = (
        '<ol>' + ''.join(
            '<li>مرحله ' + str(event["revision"]) + ': '
            + labels[event["technical_event"]] + '</li>'
            for event in events
        ) + '</ol>'
        if events else '<p>هنوز رویداد بررسی فنی ثبت نشده است.</p>'
    )
    timeline_html = (
        '<section aria-label="سابقه پیگیری فنی"><h3>سابقه پیگیری فنی</h3>'
        + history
        + '<p>تنها مراحل فنی ثبت‌شده نمایش داده می‌شوند؛ '
        'تاریخ، نظر تخصصی یا تصمیم درباره کشت از آن استنتاج نمی‌شود.</p>'
        '</section>'
    )
    items = ''.join('<li>' + label + ': تعیین نشده</li>'
                    for label, _ in slots)
    return (
        '<section><h3>اطلاعات کشت در پیش‌نمایش آزمایشی</h3>'
        '<p>این فیلدها صرفاً جایگاه نمایشی هستند؛ '
        'معیار کفایت اطلاعات برای طرح کشت تعیین نشده است.</p>'
        '<ul>' + items + '</ul>'
        '<p>طرح کشت تولید نشده است. رضایت واقعی احراز نشده؛ '
        'صلاحیت حرفه‌ای و تأیید علمی نیز احراز نشده‌اند.</p></section>'
        + timeline_html
    )


def build_authenticated_ui_router(
    flow: BrowserOIDC,
    technical_review_ledger: SqliteSyntheticHumanReviewLedger | None = None,
    owned_case_ledger: SqliteSyntheticGrantLedger | None = None,
    household_input_ledger: SqliteSyntheticHouseholdInputLedger | None = None,
    household_profile_schema: HouseholdInputSchema | None = None,
    household_profile_access_authority: Callable[[Principal, str, str], bool] | None = None,
    household_stage_context_authority: Callable[[str], CurrentStageContext | None] | None = None,
    gate_handoff_ledger: SqliteSyntheticGateEvidenceHandoff | None = None,
    authority_enquiry_ledger: SqliteSyntheticAuthorityEnquiryLedger | None = None,
    agronomy_workspace: SyntheticAgronomyWorkspace | None = None,
    export_supplier_workspace: SyntheticSupplierWorkspace | None = None,
    domestic_partner_workspace: SyntheticDomesticPartnerWorkspace | None = None,
    household_stage_artifact_store: StageArtifactStore | None = None,
    export_source_connectors: ExportSourceConnectorRegistry | None = None,
    household_surplus_publication_authority=None,
    household_surplus_draft_ledger: SurplusDraftLedger | None = None,
    household_surplus_producer_consent_ledger: ProducerConsentLedger | None = None,
    export_research_finding_ledger=None,
) -> APIRouter:
    if export_source_connectors is not None and (
            not isinstance(export_source_connectors, ExportSourceConnectorRegistry)
            or technical_review_ledger is None):
        raise ValueError("Export connector UI requires the explicit review ledger")
    if (export_research_finding_ledger is not None and
            getattr(getattr(export_research_finding_ledger, "_workspace_reader", None), "__self__", None) is not technical_review_ledger):
        raise ValueError("Export finding storage must authorize through the shared case ledger")
    if household_surplus_publication_authority is not None and (
            not callable(household_surplus_publication_authority)
            or not isinstance(household_input_ledger,
                              SqliteSyntheticHouseholdProfileLedger)
            or household_input_ledger is not technical_review_ledger
            or household_profile_schema != household_input_ledger.profile_schema
            or not callable(household_profile_access_authority)):
        raise ValueError(
            "surplus readiness UI requires the same owner-scoped household profile ledger"
        )
    if household_surplus_draft_ledger is not None and (
            not is_surplus_draft_ledger(household_surplus_draft_ledger)
            or not isinstance(household_input_ledger,
                              SqliteSyntheticHouseholdProfileLedger)
            or household_input_ledger is not technical_review_ledger
            or not callable(household_profile_access_authority)
            or household_surplus_draft_ledger._owner_access_authority
                != household_profile_access_authority):
        raise ValueError(
            "surplus draft UI requires the shared owner-scoped household authority"
        )
    if household_surplus_producer_consent_ledger is not None and (
            household_surplus_draft_ledger is None
            or not is_producer_consent_ledger(
                household_surplus_producer_consent_ledger,
                household_surplus_draft_ledger,
            )):
        raise ValueError(
            "producer consent must share the exact surplus draft ledger"
        )
    # Only the opt-in same-instance ledger injected by create_app may
    # provide the synthetic worklist. Never trust a client-side role list.
    if (technical_review_ledger is not None
            and not isinstance(technical_review_ledger, SqliteSyntheticHumanReviewLedger)):
        raise ValueError("technical review worklist requires explicit ledger")
    if (owned_case_ledger is not None
            and not isinstance(owned_case_ledger, SqliteSyntheticGrantLedger)):
        raise ValueError("owned household list requires explicit grant ledger")
    if (household_input_ledger is not None
            and (not isinstance(household_input_ledger,
                                SqliteSyntheticHouseholdInputLedger)
                 or household_input_ledger is not owned_case_ledger
                 or household_input_ledger is not technical_review_ledger)):
        raise ValueError("household input must use same explicit review ledger")
    if household_profile_schema is not None:
        if (not isinstance(household_input_ledger, SqliteSyntheticHouseholdProfileLedger)
                or household_input_ledger.profile_schema != household_profile_schema
                or not callable(household_profile_access_authority)):
            raise ValueError("household profile UI needs exact ledger/schema/authority")
    elif household_profile_access_authority is not None:
        raise ValueError("household profile authority requires explicit schema")
    if household_stage_context_authority is not None:
        if (household_profile_schema is None
                or not callable(household_stage_context_authority)):
            raise ValueError("stage observation UI needs current context authority")
    if household_stage_artifact_store is not None and (
            household_stage_context_authority is None
            or household_profile_schema is None
            or not callable(household_profile_access_authority)
            or not all(callable(getattr(household_stage_artifact_store, name, None))
                       for name in ("put", "get", "contains"))):
        raise ValueError("stage upload UI requires exact store and profile authorities")
    if (gate_handoff_ledger is not None
            and not isinstance(gate_handoff_ledger,
                               SqliteSyntheticGateEvidenceHandoff)):
        raise ValueError("technical gate handoff requires explicit synthetic ledger")
    if (authority_enquiry_ledger is not None
            and (not isinstance(authority_enquiry_ledger,
                                SqliteSyntheticAuthorityEnquiryLedger)
                 or gate_handoff_ledger is None
                 or authority_enquiry_ledger.handoff is not gate_handoff_ledger)):
        raise ValueError("authority enquiry requires same explicit handoff ledger")
    if (agronomy_workspace is not None
            and (not isinstance(agronomy_workspace, SyntheticAgronomyWorkspace)
                 or technical_review_ledger is None
                 or agronomy_workspace.ledger is not technical_review_ledger)):
        raise ValueError("agronomy needs the same explicit human-review ledger")
    if (export_supplier_workspace is not None
            and not isinstance(export_supplier_workspace, SyntheticSupplierWorkspace)):
        raise ValueError("explicit synthetic supplier workspace required")
    if (domestic_partner_workspace is not None
            and not isinstance(domestic_partner_workspace,
                               SyntheticDomesticPartnerWorkspace)):
        raise ValueError("explicit synthetic Domestic partner workspace required")
    router = APIRouter()
    cookie_name = "__Host-ronas_session"

    async def checked_browser_form(
        request: Request, sid: str | None, *,
        fields: frozenset[str], optional_fields: frozenset[str] = frozenset(),
        max_bytes: int = 1200, max_fields: int = 8,
        max_value_length: int = 150, value_encoding: str = "ascii",
    ) -> tuple[Principal, dict[str, str]]:
        """Verified server session, strict Origin+CSRF and bounded form input.

        This is not the existing Bearer API route. Never accept ambient cookies
        as enough: the signed session is reverified, as are CSRF and Origin.
        """
        if request.headers.get("origin") != flow.config.origin:
            raise HTTPException(403, detail="ORIGIN_REQUIRED")
        if (request.headers.get("content-type", "").split(";")[0].strip()
                != "application/x-www-form-urlencoded"):
            raise HTTPException(415, detail="FORM_CONTENT_TYPE_REQUIRED")
        try:
            session = flow.session(sid)
        except InvalidToken:
            raise HTTPException(401, detail="INVALID_SESSION") from None
        raw = await request.body()
        if len(raw) > max_bytes:
            raise HTTPException(413, detail="LOCAL_TEST_FORM_TOO_LARGE")
        try:
            form = parse_qs(
                raw.decode("ascii"), keep_blank_values=True,
                strict_parsing=True, max_num_fields=max_fields,
                encoding=value_encoding, errors="strict",
            )
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM") from exc
        present = set(form)
        if (not fields.issubset(present)
                or not present.issubset(fields | optional_fields)
                or any(len(items) != 1 or len(items[0]) > max_value_length
                       for items in form.values())):
            raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM")
        data = {key: values[0] for key, values in form.items()}
        data.update({key: "" for key in optional_fields if key not in data})
        if not hmac.compare_digest(session.csrf, data["csrf"]):
            raise HTTPException(403, detail="CSRF_REQUIRED")
        return Principal(session.subject, session.roles), data

    def form_version(data: str, *, zero_allowed: bool = True) -> int:
        if (not data.isascii() or not data.isdecimal()
                or (len(data) > 1 and data.startswith("0"))
                or len(data) > 12):
            raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM")
        value = int(data)
        if (value < (0 if zero_allowed else 1)
                or value > 2147483647):
            raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM")
        return value

    def sample_choice_options(*, prefix: str) -> str:
        return ''.join(
            '<option value="' + prefix + option + '">'
            + ('سناریوی نمونه الف' if option == "ALPHA"
               else 'سناریوی نمونه ب') + '</option>'
            for option in ("ALPHA", "BETA")
        )

    def export_navigation_query(technical_state: str, after_ref: str | None) -> str:
        # Navigation only; never grant or infer Export case access from URL.
        if (technical_state not in ("ALL", *TECHNICAL_STATES)
                or after_ref is not None and not _synthetic_ref(after_ref)):
            raise HTTPException(422, detail="INVALID_EXPORT_RESEARCH_QUEUE")
        return (
            "technical_state=" + quote(technical_state)
            + ("&after_ref=" + quote(after_ref) if after_ref is not None else "")
        )

    def roles(sid: str | None) -> frozenset[str] | None:
        if sid is None:
            return None
        try:
            return flow.session(sid).roles
        except InvalidToken:
            return None

    @router.get("/assets/ronas.css")
    def style() -> PlainTextResponse:
        # Exactly this trusted repository-owned CSS file; no path input.
        if not STYLE.is_file():
            raise HTTPException(503, detail="UI_ASSET_NOT_AVAILABLE")
        return PlainTextResponse(STYLE.read_text(encoding="utf-8"), media_type="text/css")

    @router.get("/assets/ronas-auth.js")
    def client_script() -> PlainTextResponse:
        return PlainTextResponse(LOGOUT_SCRIPT, media_type="text/javascript")

    @router.get("/assets/ronas-stage-observation-upload.js")
    def stage_upload_script() -> PlainTextResponse:
        return PlainTextResponse(STAGE_UPLOAD_SCRIPT, media_type="text/javascript")

    def household_worklist(
        principal: Principal, after_ref: str | None, technical_state: str,
        snapshot_sequence: int | None = None,
    ) -> str:
        if owned_case_ledger is None:
            return ""
        progress_enabled = (
            technical_review_ledger is not None
            and owned_case_ledger is technical_review_ledger
        )
        try:
            if progress_enabled:
                # One exact-owner, single-transaction snapshot: do not
                # assemble status using separate per-record privileged reads.
                result = technical_review_ledger.list_owned_domestic_progress(
                    principal, after_ref=after_ref, limit=20,
                    technical_state=technical_state,
                    snapshot_sequence=snapshot_sequence,
                )
            else:
                if technical_state != "ALL":
                    raise ValueError("technical filtering requires review ledger")
                result = owned_case_ledger.list_owned_domestic_drafts(
                    principal, after_ref=after_ref, limit=20,
                )
        except LedgerIntegrityError:
            raise  # app-level sanitizer produces 503, never partial HTML
        except ValueError as exc:
            raise HTTPException(422, detail="INVALID_OWNED_CASE_QUERY") from exc
        link_base = (
            "/my-drafts/" if progress_enabled else
            "/api/v1/domestic/household-intake/drafts/"
        )
        labels = {
            "UNREQUESTED": "بررسی فنی درخواست نشده",
            "EVIDENCE_REVIEW_REQUESTED": "درخواست بررسی شواهد ثبت شده",
            "HUMAN_RESPONSE_RECORDED":
                "مرجع پاسخ انسانی ثبت شده؛ به معنی تأیید نیست",
        }
        rows = [
            '<li><a href="' + link_base + escape(item["ref"]) + '">'
            + escape(item["ref"]) + '</a> — DRAFT_ONLY'
            + (' · ' + escape(labels[item["technical_review_state"]])
               if progress_enabled else '')
            + ' · <a href="/my-drafts/' + escape(item["ref"], quote=True)
            + '/versions">تاریخچه نسخه‌ها</a></li>'
            for item in result["items"]
        ]
        body = ('<ul>' + ''.join(rows) + '</ul>' if rows else
                '<p>در این فیلتر پرونده آزمایشی متعلق به این حساب وجود ندارد.</p>'
                if progress_enabled and technical_state != "ALL" else
                '<p>پرونده ساختگی متعلق به این حساب وجود ندارد.</p>')
        if progress_enabled:
            state_labels = {
                "ALL": "همه پرونده‌های من",
                **labels,
            }
            navigation = ' · '.join(
                ('<strong>' + escape(label) + '</strong>'
                 if state == technical_state else
                 '<a href="/?household_technical_state=' + quote(state)
                 + '">' + escape(label) + '</a>')
                for state, label in state_labels.items()
            )
            body = (
                '<p>فیلتر صرفاً مرحله فنی ثبت‌شده را نشان می‌دهد؛ '
                'پاسخ انسانی به معنی تأیید طرح کشت نیست.</p>'
                + ('<p>نمای این صفحات تا نقطه ثبت دفتر شماره '
                   + str(result["snapshot_sequence"])
                   + ' ثابت می‌ماند؛ مالکیت در هر درخواست دوباره بررسی می‌شود.</p>'
                   if progress_enabled else '')
                + '<nav aria-label="فیلتر پیگیری پرونده‌های خانوار">'
                + navigation + '</nav>' + body
            )
        if result["next_cursor"]:
            body += ('<a href="/?household_technical_state='
                     + quote(technical_state) + '&household_after_ref='
                     + quote(result["next_cursor"])
                     + ('&household_snapshot_sequence='
                        + str(result["snapshot_sequence"])
                        if progress_enabled else '')
                     + '">پرونده‌های بعدی</a>')
        return ('<section class="section"><h3>پرونده‌های من'
                ' (فقط نمونه آزمایشی)</h3>' + body + '</section>')

    @router.get("/workspace/{role}")
    def user_role_workspace(
        role: str,
        sid: str | None = Cookie(default=None, alias=cookie_name),
        after_ref: str | None = None,
        technical_state: str = "ALL",
    ) -> HTMLResponse:
        try:
            session = flow.session(sid)
        except InvalidToken:
            raise HTTPException(401, detail="INVALID_SESSION") from None
        active = visible_user_workspaces(
            Principal(session.subject, session.roles),
            owned_cases=owned_case_ledger is not None,
            technical_progress=(
                technical_review_ledger is not None
                and owned_case_ledger is technical_review_ledger
            ),
            agronomy_cases=agronomy_workspace is not None,
            export_supplier_preview=export_supplier_workspace is not None,
            domestic_partner_preview=domestic_partner_workspace is not None,
        )
        assigned = next((w for w in active if w["role"] == role), None)
        if assigned is None:
            # Unknown and unassigned partner roles are indistinguishable.
            raise HTTPException(404, detail="WORKSPACE_NOT_FOUND")
        if role == "agronomy_expert" and agronomy_workspace is not None:
            try:
                listing = agronomy_workspace.list_assigned_cases(
                    Principal(session.subject, session.roles),
                    after_ref=after_ref, limit=20,
                    technical_state=technical_state,
                )
            except LedgerIntegrityError as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    422, detail="INVALID_ASSIGNED_CASE_QUERY",
                ) from exc
            labels = {
                "ALL": "همه مراحل ثبت‌شده",
                "UNREQUESTED": "بدون درخواست بررسی فنی",
                "EVIDENCE_REVIEW_REQUESTED": "درخواست بررسی ثبت‌شده",
                "HUMAN_RESPONSE_RECORDED": "مرجع پاسخ فنی ثبت‌شده",
            }
            filters = ' · '.join(
                ('<strong>' + escape(label) + '</strong>'
                 if state == technical_state else
                 '<a href="/workspace/agronomy_expert?technical_state='
                 + quote(state) + '">' + escape(label) + '</a>')
                for state, label in labels.items()
            )
            links = ''.join(
                '<li><a href="/agronomy/assigned-drafts/'
                + quote(item["ref"]) + '">'
                + escape(item["ref"]) + '</a> — '
                + escape(labels[item["technical_review_state"]])
                + ' · طرح کشت تدوین نشده</li>'
                for item in listing["items"]
            )
            local_read = (
                '<h3>پرونده‌های تخصیص‌یافته آزمایشی</h3>'
                '<p>تخصیص پرونده، اثبات صلاحیت حرفه‌ای یا مجوز صدور طرح نیست.'
                ' فیلتر فقط وضعیت فنی ثبت‌شده را نشان می‌دهد، نه تأیید علمی.</p>'
                '<nav aria-label="فیلتر مراحل فنی کارشناس">'
                + filters + '</nav>'
                + ('<ul>' + links + '</ul>' if links else
                   '<p>در این فیلتر پرونده آزمایشی تخصیص‌یافته‌ای یافت نشد.</p>')
                + ('<p><a href="/workspace/agronomy_expert?technical_state='
                   + quote(technical_state) + '&after_ref='
                   + quote(listing["next_cursor"])
                   + '">ادامه پرونده‌ها</a></p>'
                   if listing["next_cursor"] else '')
            )
        elif (role in ("local_buyer", "equipment_seller")
              and domestic_partner_workspace is not None):
            try:
                preview = domestic_partner_workspace.own_preview(
                    role, Principal(session.subject, session.roles)
                )
            except SyntheticDomesticPartnerUnavailable as exc:
                raise HTTPException(
                    503, detail="DOMESTIC_PARTNER_PREVIEW_UNAVAILABLE",
                ) from exc
            link = (
                "/local-buyer/my-preview" if role == "local_buyer"
                else "/equipment-seller/my-preview"
            )
            local_read = (
                '<h3>پیش‌نمای شخصی نقش داخلی (فقط DEMO)</h3>'
                '<p><a href="/domestic-partners/my-preparation">'
                'نمای یکپارچه آماده‌سازی شخصی من</a></p>'
                '<p>این جایگاه آزمایشی به معنی وجود درخواست خرید، موجودی '
                'تجهیزات، مجوز، پیشنهاد یا معامله نیست.</p>'
                + ('<p><a href="' + link
                   + '">مشاهده پیش‌نمای آماده‌سازی شخصی</a></p>'
                   if preview is not None else
                   '<p>نمونه شخصی دارای مجوز جاری موجود نیست.</p>')
            )
        elif role == "export_supplier" and export_supplier_workspace is not None:
            try:
                preview = export_supplier_workspace.own_preview(
                    Principal(session.subject, session.roles)
                )
            except SyntheticSupplierUnavailable as exc:
                raise HTTPException(
                    503, detail="SUPPLIER_PREVIEW_UNAVAILABLE",
                ) from exc
            local_read = (
                '<h3>پیش‌نمای شخصی تأمین‌کننده صادرات (فقط DEMO)</h3>'
                '<p>این نمای شخصی، هویت، ظرفیت، مجوز یا اظهار واقعی نیست.</p>'
                + (
                    '<p><a href="/export-supplier/my-preview">'
                    'مشاهده پیش‌نمای آماده‌سازی تأمین‌کننده</a></p>'
                    if preview is not None else
                    '<p>نمونه آزمایشی دارای مجوز فعلی موجود نیست.</p>'
                )
            )
        else:
            local_read = (
                '<p><a href="/">مشاهده پرونده‌های ساختگی متعلق به من</a></p>'
                if "OWNED_SYNTHETIC_DOMESTIC_DRAFTS" in assigned["local_test_reads"]
                else '<p>در این نقش، خواندن پرونده عملیاتی فعال نیست.</p>'
            )
        body = (
            '<article class="panel"><h2>' + escape(assigned["label"]) + '</h2>'
            '<p>محیط کاربران و همکاران — دسترسی صرفاً به نقش امضاشده.</p>'
            '<p>وضعیت خدمات این نقش: غیرعملیاتی؛ معامله، ثبت‌نام، '
            'تأیید و تصمیم Business غیرفعال هستند.</p>'
            + local_read
            + '<p><a href="/">بازگشت به محیط مشترک</a></p></article>'
        )
        return page("روناس — فضای کار نقش من (آزمایشی)", body, logged_in=True)

    if agronomy_workspace is not None:
        @router.get("/agronomy/assigned-drafts/{ref}")
        def agronomy_case_page(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            data = agronomy_workspace.read_assigned_case(
                ref, Principal(session.subject, session.roles),
            )
            if data is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            expert_journey_html = ""
            if isinstance(agronomy_workspace.ledger,
                          SqliteSyntheticExpertQuestionLedger):
                who = Principal(session.subject, session.roles)
                history = agronomy_workspace.read_assigned_synthetic_review_questions(
                    ref, who,
                )
                if history is None:
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                try:
                    proposal = agronomy_workspace.read_assigned_proposal_structure(
                        ref, who,
                    )
                except LedgerIntegrityError as exc:
                    # Corrupted / stale independent input or source lineage
                    # cannot be presented as an ordinary navigable case.
                    raise HTTPException(
                        503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                    ) from exc
                try:
                    next_step = expert_next_action(history, proposal)
                except JourneyEvidenceMismatch as exc:
                    raise HTTPException(
                        503, detail="SYNTHETIC_JOURNEY_UNAVAILABLE",
                    ) from exc
                guidance = {
                    "SOURCE_OR_INPUT_CHANGED_HISTORY_ONLY":
                        "منبع یا پیشنهاد معتبر جاری موجود نیست؛ فقط تاریخچه قابل مشاهده است",
                    "REQUEST_MISSING_EVIDENCE_DEMO":
                        "پرسش ساختاری آزمایشی درباره داده قابل ثبت است",
                    "WAIT_FOR_HOUSEHOLD_RESPONSE_DEMO":
                        "پرسش ثبت شده؛ دریافت پاسخ مرجعی خانوار در انتظار است",
                    "INSPECT_RESPONSE_RECEIPT_DEMO":
                        "رسید پاسخ خانوار قابل مشاهده است؛ نه محتوای خصوصی آن",
                    "RECEIPT_OBSERVED_NOT_REVIEWED":
                        "رسید مشاهده شد؛ هیچ بررسی علمی یا برنامه‌ای تصویب نشده است",
                }[next_step]
                expert_journey_html = (
                    '<nav class="journey" aria-label="اقدام بعدی کارشناس">'
                    '<h3>مرحله بعدی در همین پرونده</h3><p>'
                    + escape(guidance) + '</p>'
                    '<p><a href="/agronomy/assigned-drafts/'
                    + quote(ref) + '/review-questions#expert-demo-actions">'
                    'مشاهده پرسش‌ها و اقدامات مجاز</a></p>'
                    + ('<p><a href="/agronomy/assigned-drafts/'
                       + quote(ref) + '/stage-observations">'
                       'مشاهده گزارش‌های مرحله‌ای خانوار</a></p>'
                       if household_stage_context_authority is not None
                       and isinstance(agronomy_workspace.ledger,
                                      SqliteSyntheticHouseholdProfileLedger)
                       else '')
                    + '<p>تخصیص پرونده مجوز تخصصی یا تأیید برنامه کشت نیست.</p>'
                    + '</nav>'
                )
            body = (
                '<article class="panel"><h2>پیش‌نمای پرونده خانوار (فقط DEMO): '
                + escape(data["ref"]) + '</h2>'
                '<p>نسخه پرونده: ' + str(data["case_version"])
                + ' · وضعیت: DRAFT_ONLY</p>'
                + readonly_domestic_preparation_html(
                    data["cultivation_preparation"]
                )
                + expert_journey_html
                + '<p>هیچ پیشنهاد محصول یا برنامه آبیاری '
                'تولید نشده است.</p>'
                '<p>تخصیص فنی کارشناس، صلاحیت حرفه‌ای را احراز نمی‌کند؛ '
                'رضایت واقعی خانوار و تأیید علمی/طرح کشت وجود ندارد.</p>'
                '<p><a href="/agronomy/assigned-drafts/'
                + quote(ref) + '/internal-plan-proposal">'
                'ساختار پیشنهاد داخلی برنامه کشت (فقط DEMO)</a></p>'
                '<p><a href="/agronomy/assigned-drafts/'
                + quote(ref) + '/expert-review-preparation">'
                'سه محور آماده‌سازی بررسی مستقل متخصص (فقط DEMO)</a></p>'
                + ('<p><a href="/agronomy/assigned-drafts/'
                   + quote(ref) + '/review-questions">'
                   'پرسش، دریافت پاسخ و مشاهده رسید DEMO</a></p>'
                   if isinstance(agronomy_workspace.ledger,
                                 SqliteSyntheticExpertQuestionLedger) else '')
                + '<p><a href="/workspace/agronomy_expert">'
                'بازگشت به فضای کار کارشناس کشاورزی</a></p>'
                '</article>'
            )
            return page("روناس — فضای کار کارشناس کشاورزی (آزمایشی)",
                        body, logged_in=True)

    if (agronomy_workspace is not None
            and household_stage_context_authority is not None
            and isinstance(agronomy_workspace.ledger,
                           SqliteSyntheticHouseholdProfileLedger)):
        @router.get(
            "/agronomy/assigned-drafts/{ref}/stage-observations",
        )
        def agronomy_stage_observations_page(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            try:
                data = agronomy_workspace.read_assigned_stage_observations(
                    ref, Principal(session.subject, session.roles),
                    context_authority=household_stage_context_authority,
                )
            except StageObservationConflict as exc:
                raise HTTPException(
                    409, detail="STAGE_OBSERVATION_CONTEXT_CHANGED",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="STAGE_OBSERVATIONS_UNAVAILABLE",
                ) from exc
            if data is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            progress_labels = {
                "NOT_REPORTED": "رسیدی گزارش نشده",
                "CURRENT_RECEIPT": "رسید جاری",
                "HISTORICAL_RECEIPT": "رسید تاریخی",
            }
            stage_progress = ''.join(
                '<li>' + escape(item["stage_ref"]) + ' · '
                + progress_labels[item["state"]]
                + (' · نسخه ' + str(item["observation_revision"])
                   if item["observation_revision"] is not None else '')
                + (' · رسید مشاهده شد (بدون داوری)'
                   if item["receipt_inspected"] else '')
                + '</li>'
                for item in data["stage_progress"]
            )
            items = []
            for item in data["observations"]:
                state = "جاری با زمینه فعلی" if item["current"] else "تاریخی"
                if item["is_superseded"]:
                    replacement_revision = item["superseded_by_revision"]
                    state += (
                        ' · اصلاح‌شده با <a href="#observation-'
                        + quote(item["stage_ref"]) + '-'
                        + str(replacement_revision) + '">رسید '
                        + str(replacement_revision) + '</a>'
                    )
                file_link = ""
                if household_stage_artifact_store is not None:
                    file_link = (
                        '<p><a href="/agronomy/assigned-drafts/'
                        + quote(ref) + '/stage-observations/artifacts/'
                        + quote(item["stage_ref"]) + '/'
                        + quote(item["observation_artifact_digest"])
                        + '">دریافت فایل مشاهده</a></p>'
                    )
                if item["receipt_inspected"]:
                    inspection = (
                        '<p>رسید مشاهده شد (بدون داوری تخصصی).</p>'
                    )
                else:
                    inspection = (
                        '<form method="post" action="/agronomy/assigned-drafts/'
                        + quote(ref) + '/stage-observations/inspect">'
                        '<input type="hidden" name="csrf" value="'
                        + escape(session.csrf, quote=True) + '">'
                        '<input type="hidden" name="case_version" value="'
                        + str(data["case_version"]) + '">'
                        '<input type="hidden" name="stage_ref" value="'
                        + escape(item["stage_ref"], quote=True) + '">'
                        '<input type="hidden" name="observation_revision" value="'
                        + str(item["revision"]) + '">'
                        '<input type="hidden" name="receipt_digest" value="'
                        + escape(item["receipt_digest"], quote=True) + '">'
                        '<button type="submit">ثبت مشاهده رسید (بدون بررسی)</button>'
                        '</form>'
                    )
                items.append(
                    '<section id="observation-'
                    + escape(item["stage_ref"], quote=True) + '-'
                    + str(item["revision"]) + '"><h3>'
                    + escape(item["stage_ref"]) + '</h3>'
                    + '<p>نسخه رسید: ' + str(item["revision"])
                    + ' · نسخه پرونده ' + str(item["case_version"])
                    + ' · نسخه اطلاعات خانوار ' + str(item["input_revision"])
                    + ' · ' + state + '</p>'
                    + ('<p>این رسید اصلاح نسخه <a href="#observation-'
                       + quote(item["stage_ref"]) + '-'
                       + str(item["corrects_revision"]) + '">'
                       + str(item["corrects_revision"]) + '</a> است.</p>'
                       if item["corrects_revision"] is not None else '')
                    + '<p>زمان ثبت: ' + escape(item["observed_at"]) + '</p>'
                    + file_link + inspection + '</section>'
                )
            body = (
                '<article class="panel"><h2>مشاهده‌های مرحله‌ای ثبت‌شده'
                ' (فقط رسید خانوار)</h2>'
                '<p>پرونده ' + escape(data["ref"])
                + ' · نسخه پرونده ' + str(data["case_version"]) + '</p>'
                + ('<h3>وضعیت گزارش مرحله‌های طرح جاری</h3><ul>'
                   + stage_progress + '</ul>'
                   if data["current_context"] is not None else
                   '<p>مرجع جاری برای تعیین مرحله‌های موردنیاز موجود نیست.</p>')
                + (''.join(items) if items else '<p>رسیدی ثبت نشده است.</p>')
                + '<p>این رسیدها گزارش خانوار هستند و تکمیل مرحله، '
                'ارزیابی علمی، توصیه یا تأیید برنامه کشت را نشان نمی‌دهند.</p>'
                '<p><a href="/agronomy/assigned-drafts/' + quote(ref)
                + '">بازگشت به پرونده تخصیص‌یافته</a></p></article>'
            )
            return page(
                "روناس — رسیدهای مرحله‌ای خانوار",
                body, logged_in=True, local_test_form=True,
            )

        @router.post(
            "/agronomy/assigned-drafts/{ref}/stage-observations/inspect",
        )
        async def inspect_stage_receipt_from_browser(
            ref: str, request: Request,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> RedirectResponse:
            principal, form = await checked_browser_form(
                request, sid, fields=frozenset({
                    "csrf", "case_version", "stage_ref",
                    "observation_revision", "receipt_digest",
                }),
            )
            try:
                result = agronomy_workspace.inspect_assigned_stage_receipt(
                    ref, principal,
                    action_id="DEMO-UI-SI-" + secrets.token_hex(10).upper(),
                    expected_case_version=form_version(
                        form["case_version"], zero_allowed=False,
                    ),
                    stage_ref=form["stage_ref"],
                    expected_observation_revision=form_version(
                        form["observation_revision"], zero_allowed=False,
                    ),
                    expected_observation_receipt_digest=form["receipt_digest"],
                )
            except ReviewQuestionConflict as exc:
                raise HTTPException(
                    409, detail="STAGE_RECEIPT_CONTEXT_CHANGED",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="STAGE_OBSERVATIONS_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(422, detail="INVALID_STAGE_RECEIPT_INSPECTION") from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return RedirectResponse(
                "/agronomy/assigned-drafts/" + quote(ref)
                + "/stage-observations", status_code=303,
            )

    if (agronomy_workspace is not None
            and household_stage_artifact_store is not None
            and isinstance(agronomy_workspace.ledger,
                           SqliteSyntheticHouseholdProfileLedger)):
        @router.get(
            "/agronomy/assigned-drafts/{ref}/stage-observations/"
            "artifacts/{stage_ref}/{digest}",
        )
        def agronomy_stage_observation_artifact(
            ref: str, stage_ref: str, digest: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> Response:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            try:
                stored = agronomy_workspace.read_assigned_stage_artifact(
                    ref, stage_ref, digest,
                    Principal(session.subject, session.roles),
                    store=household_stage_artifact_store,
                )
            except StageArtifactStoreError as exc:
                raise HTTPException(
                    503, detail="STAGE_ARTIFACT_STORE_UNAVAILABLE",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="STAGE_OBSERVATIONS_UNAVAILABLE",
                ) from exc
            if stored is None:
                raise HTTPException(404, detail="STAGE_ARTIFACT_NOT_FOUND")
            artifact, content = stored
            return Response(
                content=content, media_type=artifact.content_type,
                headers={
                    "Content-Disposition": 'attachment; filename="stage-observation"',
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )

    if agronomy_workspace is not None:
        @router.get("/agronomy/assigned-drafts/{ref}/internal-plan-proposal")
        def agronomy_internal_proposal_page(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            try:
                data = agronomy_workspace.read_assigned_proposal_structure(
                    ref, Principal(session.subject, session.roles),
                )
            except LedgerIntegrityError as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if data is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            if (data["engine"] != "DOMESTIC"
                    or data["plan_state"] != "NOT_AUTHORED"
                    or data["plan_accepted"] is not False
                    or data["advice_enabled"] is not False
                    or data["real_data"] is not False):
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                )
            status = data["proposal_status"]
            if status == "NO_INTERNAL_PROPOSAL_FIXTURE":
                explanation = (
                    '<p>هنوز هیچ پیشنهاد ساختاری AI داخلی روناس '
                    'برای این پرونده آزمایشی وجود ندارد.</p>'
                )
            elif status == "STRUCTURE_ONLY_UNREVIEWED":
                stages = ''.join(
                    '<li>' + escape(stage_ref) + '</li>'
                    for stage_ref in data["proposed_stage_refs"]
                )
                explanation = (
                    '<p>نمونه ساختاری آزمایشی برای مطالعه پیوند نسخه‌ها موجود است. '
                    'اجرای واقعی مدل، محتوای علمی و اعتبارسنجی آن تأیید نشده‌اند.</p>'
                    '<h3>شناسه‌های مراحل پیشنهادی غیرعملیاتی</h3>'
                    '<ul>' + stages + '</ul>'
                )
            else:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                )
            body = (
                '<article class="panel"><h2>بررسی ساختار پیشنهاد داخلی کشت '
                '(فقط DEMO)</h2>'
                '<p>پرونده ' + escape(data["case_ref"])
                + ' · نسخه ' + str(data["case_version"]) + '</p>'
                + explanation
                + '<p>این پاسخ یک برنامه کشت یا تأیید متخصص نیست؛ '
                'داده‌های خانوار، رضایت، منابع علمی، مدل اجرایی و '
                'صلاحیت واقعی متخصص هنوز احراز نشده‌اند.</p>'
                '<p>هیچ برنامه‌ای پذیرفته نشده و گزارش مرحله‌ای '
                'یا توصیه کشت از آن فعال نمی‌شود.</p>'
                '<p><a href="/agronomy/assigned-drafts/' + quote(ref)
                + '">بازگشت به پرونده تخصیص‌…39078 tokens truncated…")
        async def technical_review_submit(
            engine: str, ref: str, operation: str, request: Request,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> RedirectResponse:
            engine_key = engine.upper()
            if engine_key not in ("DOMESTIC", "EXPORT") or operation not in (
                    "request", "human-response"):
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            required = {"csrf", "action_id", "case_version", "review_revision",
                        "request_ref", "evidence_ref"}
            if operation == "human-response":
                required.add("decision_ref")
            principal, form = await checked_browser_form(
                request, sid, fields=frozenset(required), max_bytes=1200,
                max_fields=8, max_value_length=120,
            )
            try:
                if operation == "request":
                    expected_revision = form_version(form["review_revision"])
                    if expected_revision % 2:
                        raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM")
                    technical_review_ledger.request_evidence_review(
                        engine=engine_key, ref=ref, actor=principal,
                        expected_case_version=form_version(
                            form["case_version"], zero_allowed=False,
                        ), expected_review_revision=expected_revision,
                        action_id=form["action_id"], request_ref=form["request_ref"],
                        evidence_ref=form["evidence_ref"],
                    )
                else:
                    expected_revision = form_version(form["review_revision"])
                    if expected_revision % 2 != 1:
                        raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM")
                    technical_review_ledger.record_human_response(
                        engine=engine_key, ref=ref, actor=principal,
                        expected_case_version=form_version(
                            form["case_version"], zero_allowed=False,
                        ), expected_review_revision=expected_revision,
                        action_id=form["action_id"], request_ref=form["request_ref"],
                        evidence_ref=form["evidence_ref"],
                        decision_ref=form["decision_ref"],
                    )
            except GrantNotAuthorized as exc:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND") from exc
            except GrantConflict as exc:
                raise HTTPException(409, detail="TECHNICAL_REVIEW_CHANGED") from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM") from exc
            return RedirectResponse(
                "/admin/technical-review/" + engine.lower() + "/" + quote(ref),
                status_code=303,
            )

    if technical_review_ledger is not None:
        @router.get("/admin/export/research")
        def export_research_cases_page(
            sid: str | None = Cookie(default=None, alias=cookie_name),
            technical_state: str = "ALL",
            after_ref: str | None = None,
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            try:
                research = technical_review_ledger.list_export_research_cases(
                    Principal(session.subject, session.roles),
                    technical_state=technical_state, after_ref=after_ref,
                    limit=20,
                )
            except LedgerIntegrityError:
                raise  # integrity failures must stay 503, never validation 422
            except ValueError as exc:
                raise HTTPException(
                    422, detail="INVALID_EXPORT_RESEARCH_QUEUE",
                ) from exc
            # A role alone cannot expose any cases. An unrelated admin
            # role must not gain a portal into Export by guessing the URL.
            if "export_ops" not in session.roles:
                raise HTTPException(404, detail="RESEARCH_QUEUE_NOT_FOUND")
            labels = {
                "ALL": "همه پرونده‌های تخصیص‌یافته",
                "UNREQUESTED": "بدون درخواست بررسی",
                "EVIDENCE_REVIEW_REQUESTED": "درخواست بررسی ثبت‌شده",
                "HUMAN_RESPONSE_RECORDED": "مرجع پاسخ فنی ثبت‌شده",
            }
            filters = ' · '.join(
                ('<strong>' + escape(label) + '</strong>'
                 if state == technical_state else
                 '<a href="/admin/export/research?technical_state='
                 + quote(state) + '">' + escape(label) + '</a>')
                for state, label in labels.items()
            )
            rows = ''.join(
                '<li><a href="/admin/export/research/drafts/'
                + quote(item["ref"]) + '?'
                + export_navigation_query(technical_state, after_ref) + '">'
                + escape(item["ref"]) + '</a>'
                ' — نسخه ' + str(item["case_version"])
                + ' — ' + escape(labels[item["technical_review_state"]])
                + ' — پرسش بازار و حقوق منبع هنوز احراز نشده‌اند.</li>'
                for item in research["items"]
            )
            more = (
                '<p><a href="/admin/export/research?technical_state='
                + quote(technical_state) + '&after_ref='
                + quote(research["next_cursor"])
                + '">پرونده‌های بعدی</a></p>'
                if research["next_cursor"] is not None else ''
            )
            content = (
                '<article class="panel"><h2>پرونده‌های پژوهش صادرات '
                '(فقط DEMO)</h2>'
                '<p>فقط پرونده‌های دارای تخصیص فعلی نمایش داده می‌شوند. '
                'این فیلتر وضعیت بررسی فنی است؛ وضعیت گزارش معتبر بازار نیست.</p>'
                '<nav aria-label="فیلتر وضعیت فنی پژوهش">'
                + filters + '</nav>'
                + ('<ol>' + rows + '</ol>' if rows else
                   '<p>پرونده تخصیص‌یافته‌ای در این وضعیت وجود ندارد.</p>')
                + more
                + '<p>محصول، کشور مقصد، قیمت، خریدار و قرارداد '
                'از این فهرست استنتاج نمی‌شوند.</p>'
                '<p><a href="/admin">بازگشت به مدیریت روناس</a></p>'
                '</article>'
            )
            return page("روناس — صف پژوهش صادرات آزمایشی",
                        content, logged_in=True)

    if technical_review_ledger is not None:
        @router.get("/admin/export/research/drafts/{ref}/packet.json")
        def export_research_packet_download(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> JSONResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            principal = Principal(session.subject, session.roles)
            try:
                before = technical_review_ledger.read_export_research_workspace(
                    ref, principal,
                )
                if before is None:
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                if export_research_finding_ledger is not None:
                    findings_before = export_research_finding_ledger.read_history(
                        ref, principal,
                    )
                    findings_after = export_research_finding_ledger.read_history(
                        ref, principal,
                    )
                else:
                    findings_before = before.get("local_test_findings")
                    findings_after = findings_before
                after = technical_review_ledger.read_export_research_workspace(
                    ref, principal,
                )
                if findings_before is None or findings_after is None or after is None:
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                packet = build_export_research_packet(
                    before, findings_before, findings_after, after,
                )
            except HTTPException:
                raise
            except ExportResearchPacketConflict as exc:
                raise HTTPException(409, detail="EXPORT_RESEARCH_CONTEXT_CHANGED") from exc
            except ExportResearchPacketIntegrityError as exc:
                raise HTTPException(503, detail="TECHNICAL_REVIEW_UNAVAILABLE") from exc
            except (LedgerIntegrityError, sqlite3.Error, ExportFindingStorageError) as exc:
                raise HTTPException(503, detail="TECHNICAL_REVIEW_UNAVAILABLE") from exc
            return JSONResponse(
                packet,
                headers={
                    "Cache-Control": "no-store",
                    "Content-Disposition": 'attachment; filename="ronas-export-demo-packet.json"',
                },
            )

    if technical_review_ledger is not None:
        @router.get("/admin/export/research/drafts/{ref}/versions")
        def export_research_versions_page(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
            technical_state: str = "ALL",
            after_ref: str | None = None,
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            navigation = export_navigation_query(technical_state, after_ref)
            data = technical_review_ledger.read_export_research_version_history(
                ref, Principal(session.subject, session.roles),
            )
            if data is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            versions = ''.join(
                '<li>نسخه ' + str(item["version"])
                + (' — نسخه فعلی DEMO' if item["is_current"]
                   else ' — نسخه پیشین DEMO')
                + '</li>' for item in data["versions"]
            )
            body = (
                '<article class="panel"><h2>تاریخچه نسخه‌های پژوهش صادرات: '
                + escape(data["ref"]) + '</h2>'
                '<p>فقط شماره نسخه‌های از پیش ثبت‌شده و تأیید یکپارچگی‌شده '
                'نمونه آزمایشی نمایش داده می‌شوند. تاریخ و محتوای تغییرات '
                'از شماره نسخه‌ها استنتاج نمی‌شود.</p>'
                '<p>همه نسخه‌ها DRAFT_ONLY؛ هیچ مجوز استفاده از منبع، '
                'گزارش تأییدشده، خریدار یا قرارداد وجود ندارد.</p>'
                '<ol>' + versions + '</ol>'
                '<p><a href="/admin/export/research/drafts/'
                + quote(data["ref"]) + '?' + navigation
                + '">بازگشت به جزئیات پرونده</a></p>'
                '<p><a href="/admin/export/research?'
                + navigation + '">بازگشت به فهرست فیلترشده</a></p>'
                '</article>'
            )
            return page("روناس — تاریخچه پژوهش صادرات (DEMO)",
                        body, logged_in=True)

    if technical_review_ledger is not None:
        @router.get("/admin/export/research/drafts/{ref}")
        def export_research_detail(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
            technical_state: str = "ALL",
            after_ref: str | None = None,
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            navigation = export_navigation_query(technical_state, after_ref)
            data = technical_review_ledger.read_export_research_workspace(
                ref, Principal(session.subject, session.roles),
            )
            if data is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            if export_research_finding_ledger is not None:
                try:
                    findings = export_research_finding_ledger.read_history(
                        ref, Principal(session.subject, session.roles),
                    )
                except ExportFindingStorageError as exc:
                    raise HTTPException(503, detail="TECHNICAL_REVIEW_UNAVAILABLE") from exc
                if findings is None:
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                data["local_test_findings"] = findings
            question = data["local_test_draft_question"]
            try:
                export_step = export_next_action(data)
            except JourneyEvidenceMismatch as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_JOURNEY_UNAVAILABLE",
                ) from exc
            next_action = (
                "پرسش محصول–مقصد صرفاً آزمایشی هنوز تعریف نشده است"
                if export_step == "DEFINE_INITIAL_RESEARCH_QUESTION_DEMO"
                else "پرسش نسخه‌دار موجود است؛ حقوق منبع و گزارش هنوز معتبر نیستند"
            )
            export_journey_html = (
                '<nav class="journey" aria-label="اقدام بعدی پژوهش صادرات">'
                '<h3>اقدام بعدی پرونده پژوهش</h3><p>'
                + escape(next_action) + '</p>'
                '<p><a href="#export-demo-question-form">'
                'رفتن به تعریف یا اصلاح پرسش نمونه</a></p>'
                '<p>ثبت پرسش، مجوز منبع، قرارداد یا گزارش صادرات نیست.</p>'
                '</nav>'
            )
            demo_question = (
                '<h3>پرسش آزمایشی ثبت‌شده در همین پرونده</h3>'
                '<p>نسخه پرسش ' + str(question["question_revision"])
                + ' — مرجع محصول ' + escape(question["product_ref"])
                + ' · مرجع مقصد ' + escape(question["destination_ref"])
                + '</p><p>صرفاً DEMO و تأییدنشده؛ منبع، محصول، مقصد، '
                'حق استفاده یا یافته معتبر بازار احراز نشده‌اند.</p>'
                if question is not None else
                '<p>هنوز هیچ پرسش DEMO نسخه‌داری ثبت نشده است.</p>'
            )
            previous_demo_questions = data["local_test_question_history"]
            history_section = (
                '<section aria-label="تاریخچه پرسش‌های DEMO">'
                '<h3>تاریخچه اصلاح پرسش‌های DEMO</h3>'
                '<ol>' + ''.join(
                    '<li>نسخه پرسش ' + str(item["question_revision"])
                    + (' (نسخه جاری)' if item["is_current"] else ' (تاریخی)')
                    + ' · مرجع محصول ' + escape(item["product_ref"])
                    + ' · مرجع مقصد ' + escape(item["destination_ref"])
                    + ' · حقوق و یافته‌ها تأییدنشده</li>'
                    for item in previous_demo_questions
                ) + '</ol></section>'
                if previous_demo_questions else
                '<p>سابقه‌ای از اصلاح پرسش‌های DEMO ثبت نشده است.</p>'
            )
            version = (
                question["question_revision"] if question is not None else 0
            )
            demo_form = (
                '<section id="export-demo-question-form" aria-label="ویرایش پرسش آزمایشی صادرات">'
                '<h3>تعریف یا اصلاح پرسش DEMO</h3>'
                '<p>صرفاً شناسه‌های نمونه؛ هیچ محصول، کشور یا مأخذ واقعی '
                'در این صفحه ثبت یا تأیید نمی‌شود.</p>'
                '<form method="post" action="/admin/export/research/drafts/'
                + quote(ref) + '/local-test-question">'
                '<input type="hidden" name="csrf" value="'
                + escape(session.csrf, quote=True) + '">'
                '<input type="hidden" name="action_id" value="DEMO-UI-E-'
                + secrets.token_hex(10).upper() + '">'
                '<input type="hidden" name="case_version" value="'
                + str(data["case_version"]) + '">'
                '<input type="hidden" name="question_revision" value="'
                + str(version) + '">'
                '<label for="export-demo-product">مرجع محصول DEMO</label>'
                '<select id="export-demo-product" name="product_ref">'
                + sample_choice_options(prefix="DEMO-PRODUCT-")
                + '</select>'
                '<label for="export-demo-destination">مرجع مقصد DEMO</label>'
                '<select id="export-demo-destination" name="destination_ref">'
                + sample_choice_options(prefix="DEMO-DEST-")
                + '</select><button type="submit">ثبت پرسش آزمایشی</button>'
                '</form></section>'
            )
            stage_labels = {
                "UNREQUESTED": "درخواست بررسی فنی هنوز ثبت نشده است",
                "EVIDENCE_REVIEW_REQUESTED": "مرجع درخواست بررسی فنی ثبت شده است",
                "HUMAN_RESPONSE_RECORDED":
                    "مرجع پاسخ مستقل ثبت شده؛ نتیجه پژوهش تأیید نشده است",
            }
            stage_events = {
                "TECH_REVIEW_REQUESTED": "درخواست بررسی فنی ثبت‌شده",
                "TECH_HUMAN_RESPONSE_RECORDED":
                    "مرجع پاسخ انسانی ثبت‌شده (نه تأیید گزارش)",
            }
            steps = ''.join(
                '<li>مرحله فنی ' + str(item["revision"]) + ': '
                + escape(stage_events[item["stage"]]) + '</li>'
                for item in data["technical_review_steps"]
            )
            if not steps:
                steps = '<li>هیچ بررسی فنی برای این نمونه ثبت نشده است.</li>'
            versions = '، '.join(str(v) for v in data["known_versions"])
            body = (
                '<article class="panel"><h2>پرونده پژوهش صادرات (آزمایشی): '
                + escape(data["ref"]) + '</h2>'
                '<p>وضعیت پرونده: DRAFT_ONLY · نسخه فعلی '
                + str(data["case_version"]) + '</p>'
                '<p>نسخه‌های مستند در نمونه: ' + escape(versions) + '</p>'
                '<p><a href="/admin/export/research/drafts/'
                + quote(data["ref"]) + '/versions?' + navigation
                + '">تاریخچه نسخه‌های این پرونده</a></p>'
                '<p><a href="/admin/export/research/drafts/'
                + quote(data["ref"]) + '/packet.json">دریافت بسته پژوهش DEMO به‌صورت JSON</a></p>'
                '<p>بسته فقط شناسه‌ها، fingerprint و یادداشت DEMO دارد؛ مجوز منبع یا گزارش معتبر ایجاد نمی‌کند.</p>'
                '<h3>تعریف مسئله پژوهش</h3>'
                '<p>محصول: تعیین نشده · مقصد: تعیین نشده '
                '· HS: تعیین نشده</p>'
                '<p>محصول و مقصد واقعی همچنان تعیین و اعتبارسنجی نشده‌اند.</p>'
                + export_journey_html
                + demo_question
                + history_section
                + demo_form
                + '<section aria-label="ارجاع‌های منبع نسخه‌دار"><h3>ارجاع‌های فنی منبع</h3>'
                '<p>فقط شناسه و fingerprint دریافتی از اتصال نمونه ثبت می‌شود؛ '
                'محتوای منبع ذخیره یا مجوز آن تأیید نمی‌شود.</p>'
                '<ol>' + ''.join(
                    '<li>پرسش نسخه ' + str(item["question_revision"])
                    + '، ارجاع نسخه ' + str(item["evidence_revision"])
                    + ' (' + ("پرسش جاری" if item["question_binding"] == "CURRENT"
                              else "تاریخی") + ') · '
                    + escape(item["connector_ref"]) + ' · '
                    + escape(item["evidence_ref"]) + ' · SHA-256 '
                    + escape(item["source_snapshot_digest"])
                    + ' · حقوق و یافته‌ها تأییدنشده</li>'
                    for item in data["local_test_evidence_references"]
                ) + '</ol></section>'
                + (
                    '<section id="export-evidence-reference-form">'
                    '<h3>ثبت fingerprint اتصال منبع (DEMO)</h3>'
                    '<p>ابتدا پرسش محصول–مقصد نسخه‌دار ثبت کنید. مقادیر فقط '
                    'شناسه‌های نمونه‌اند و این فرم گزارش پژوهش نمی‌سازد.</p>'
                    + (
                        '<form method="post" action="/admin/export/research/drafts/'
                        + quote(ref) + '/evidence-reference/capture">'
                        '<input type="hidden" name="csrf" value="'
                        + escape(session.csrf, quote=True) + '">'
                        '<input type="hidden" name="action_id" value="DEMO-UI-CAPTURE-'
                        + secrets.token_hex(10).upper() + '">'
                        '<input type="hidden" name="case_version" value="'
                        + str(data["case_version"]) + '">'
                        '<input type="hidden" name="question_revision" value="'
                        + str(question["question_revision"]) + '">'
                        '<input type="hidden" name="evidence_revision" value="'
                        + str(sum(1 for item in data["local_test_evidence_references"]
                                  if item["question_revision"] == question["question_revision"])) + '">'
                        '<label for="export-source-connector">اتصال منبع پیکربندی‌شده</label>'
                        '<select id="export-source-connector" name="connector_ref">'
                        + ''.join(
                            '<option value="' + escape(connector_ref, quote=True) + '">'
                            + escape(connector_ref) + '</option>'
                            for connector_ref in export_source_connectors.refs()
                        )
                        + '</select><button type="submit">گرفتن snapshot و ثبت fingerprint</button>'
                        '</form><p>محتوای snapshot ذخیره نمی‌شود؛ این ثبت، مجوز یا یافته بازار نیست.</p>'
                        if export_source_connectors is not None and export_source_connectors.refs()
                        else ''
                    )
                    + '<form method="post" action="/admin/export/research/drafts/'
                    + quote(ref) + '/evidence-reference">'
                    '<input type="hidden" name="csrf" value="'
                    + escape(session.csrf, quote=True) + '">'
                    '<input type="hidden" name="action_id" value="DEMO-UI-ER-'
                    + secrets.token_hex(10).upper() + '">'
                    '<input type="hidden" name="case_version" value="'
                    + str(data["case_version"]) + '">'
                    '<input type="hidden" name="question_revision" value="'
                    + str(question["question_revision"] if question else 0) + '">'
                    '<input type="hidden" name="evidence_revision" value="'
                    + str(sum(1 for item in data["local_test_evidence_references"]
                              if question and item["question_revision"] == question["question_revision"])) + '">'
                    '<label for="export-evidence-ref">شناسه شواهد DEMO</label>'
                    '<select id="export-evidence-ref" name="evidence_ref">'
                    + sample_choice_options(prefix="DEMO-EVIDENCE-")
                    + '</select><label for="export-connector-ref">شناسه اتصال DEMO</label>'
                    '<select id="export-connector-ref" name="connector_ref">'
                    + sample_choice_options(prefix="DEMO-CONNECTOR-")
                    + '</select><label for="export-snapshot-digest">SHA-256 snapshot</label>'
                    '<input id="export-snapshot-digest" name="source_snapshot_digest" '
                    'pattern="[0-9a-f]{64}" minlength="64" maxlength="64" required>'
                    '<button type="submit">ثبت ارجاع آزمایشی</button></form></section>'
                    if question is not None else
                    '<p>ثبت ارجاع منبع باز است تا پرسش نسخه‌دار تعریف شود.</p>'
                )
                + '<section id="export-research-findings"><h3>یافته‌های پژوهشی پیش‌نویس</h3>'
                '<p>یادداشت‌ها باید با پیشوند DEMO باشند و به ارجاع شواهد پرسش جاری متصل شوند. '
                'این یادداشت‌ها واقعیت بازار یا گزارش تأییدشده نیستند.</p>'
                '<ol>' + ''.join(
                    '<li>پرسش نسخه ' + str(item["question_revision"])
                    + ' · یافته نسخه ' + str(item["revision"])
                    + ' · ارجاع ' + escape(item["evidence_ref"])
                    + ' · پرسش: ' + escape(item["question_binding"])
                    + ' · شواهد: ' + escape(item["evidence_binding"])
                    + '<p>اتصال منبع: ' + escape(item["connector_ref"])
                    + ' · fingerprint snapshot: '
                    + escape(item["source_snapshot_digest"]) + '</p>'
                    + '<p>' + escape(item["note"]) + '</p></li>'
                    for item in data.get("local_test_findings", [])
                ) + '</ol>'
                + (
                    '<form method="post" action="/admin/export/research/drafts/'
                    + quote(ref) + '/findings">'
                    '<input type="hidden" name="csrf" value="'
                    + escape(session.csrf, quote=True) + '">'
                    '<input type="hidden" name="action_id" value="DEMO-UI-FINDING-'
                    + secrets.token_hex(10).upper() + '">'
                    '<input type="hidden" name="case_version" value="'
                    + str(data["case_version"]) + '">'
                    '<input type="hidden" name="question_revision" value="'
                    + str(question["question_revision"]) + '">'
                    '<input type="hidden" name="finding_revision" value="'
                    + str(sum(1 for item in data.get("local_test_findings", [])
                              if item["question_revision"] == question["question_revision"])) + '">'
                    '<label for="export-finding-evidence">ارجاع شواهد پرسش جاری</label>'
                    '<select id="export-finding-evidence" name="evidence_binding">'
                    + ''.join(
                        '<option value="' + str(item["evidence_revision"]) + ':'
                        + escape(item["evidence_ref"], quote=True) + '">'
                        + escape(item["evidence_ref"]) + ' · نسخه '
                        + str(item["evidence_revision"]) + '</option>'
                        for item in data["local_test_evidence_references"]
                        if item["question_binding"] == "CURRENT"
                    )
                    + '</select><label for="export-finding-note">یادداشت DEMO</label>'
                    '<textarea id="export-finding-note" name="note" minlength="8" '
                    'maxlength="2000" required></textarea>'
                    '<button type="submit">ثبت نسخه پیش‌نویس</button></form>'
                    if question is not None and any(
                        item["question_binding"] == "CURRENT"
                        for item in data["local_test_evidence_references"]
                    ) else '<p>برای ثبت یادداشت، پرسش جاری و حداقل یک ارجاع شواهد لازم است.</p>'
                ) + '</section>'
                + '<p>مرجع منبع صرفاً آزمایشی: '
                + escape(data["source_ref"]) + '</p>'
                '<p>حقوق استفاده و بازنشر این منبع احراز نشده است.</p>'
                '<h3>وضعیت بررسی</h3><p>'
                + escape(stage_labels[data["technical_review_state"]])
                + '</p><ul>' + steps + '</ul>'
                '<p>یافته معتبر بازار، گزارش تأییدشده، خریدار احرازشده، '
                'قیمت یا قرارداد وجود ندارد؛ این صفحه توصیه تجاری نیست.</p>'
                '<p><a href="/admin/export/research?'
                + navigation + '">بازگشت به فهرست پژوهش صادرات</a></p>'
                '</article>'
            )
            return page("روناس — فضای پژوهش صادرات آزمایشی",
                        body, logged_in=True, local_test_form=True)

        @router.post("/admin/export/research/drafts/{ref}/local-test-question")
        async def export_demo_question_browser(
            ref: str, request: Request,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> RedirectResponse:
            principal, form = await checked_browser_form(
                request, sid,
                fields=frozenset({
                    "csrf", "action_id", "case_version", "question_revision",
                    "product_ref", "destination_ref",
                }),
            )
            if not valid_question_refs(
                form["product_ref"], form["destination_ref"],
            ) or form["product_ref"] not in (
                "DEMO-PRODUCT-ALPHA", "DEMO-PRODUCT-BETA",
            ) or form["destination_ref"] not in (
                "DEMO-DEST-ALPHA", "DEMO-DEST-BETA",
            ):
                raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM")
            try:
                result = technical_review_ledger.record_export_research_question(
                    ref, principal,
                    expected_case_version=form_version(
                        form["case_version"], zero_allowed=False,
                    ),
                    expected_question_revision=form_version(
                        form["question_revision"],
                    ),
                    action_id=form["action_id"],
                    product_ref=form["product_ref"],
                    destination_ref=form["destination_ref"],
                )
            except ExportResearchQuestionConflict as exc:
                raise HTTPException(
                    409, detail="EXPORT_LOCAL_QUESTION_CHANGED",
                ) from exc
            except LedgerIntegrityError as exc:
                raise HTTPException(
                    503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    422, detail="INVALID_LOCAL_TEST_FORM",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return RedirectResponse(
                "/admin/export/research/drafts/" + quote(ref),
                status_code=303,
            )

        @router.post("/admin/export/research/drafts/{ref}/evidence-reference")
        async def export_demo_evidence_reference_browser(
            ref: str, request: Request,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> RedirectResponse:
            principal, form = await checked_browser_form(
                request, sid,
                fields=frozenset({
                    "csrf", "action_id", "case_version", "question_revision",
                    "evidence_revision", "evidence_ref", "connector_ref",
                    "source_snapshot_digest",
                }),
            )
            if (not valid_evidence_refs(
                    form["evidence_ref"], form["connector_ref"],
                ) or form["evidence_ref"] not in (
                    "DEMO-EVIDENCE-ALPHA", "DEMO-EVIDENCE-BETA",
                ) or form["connector_ref"] not in (
                    "DEMO-CONNECTOR-ALPHA", "DEMO-CONNECTOR-BETA",
                ) or not valid_snapshot_digest(form["source_snapshot_digest"])):
                raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM")
            try:
                result = technical_review_ledger.record_export_evidence_reference(
                    ref, principal,
                    expected_case_version=form_version(
                        form["case_version"], zero_allowed=False,
                    ),
                    expected_question_revision=form_version(
                        form["question_revision"], zero_allowed=False,
                    ),
                    expected_evidence_revision=form_version(
                        form["evidence_revision"],
                    ),
                    action_id=form["action_id"],
                    evidence_ref=form["evidence_ref"],
                    connector_ref=form["connector_ref"],
                    source_snapshot_digest=form["source_snapshot_digest"],
                )
            except ExportEvidenceReferenceConflict as exc:
                raise HTTPException(
                    409, detail="EXPORT_EVIDENCE_REFERENCE_CHANGED",
                ) from exc
            except LedgerIntegrityError as exc:
                raise HTTPException(
                    503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(
                    422, detail="INVALID_LOCAL_TEST_FORM",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return RedirectResponse(
                "/admin/export/research/drafts/" + quote(ref),
                status_code=303,
            )

        @router.post("/admin/export/research/drafts/{ref}/findings")
        async def export_demo_finding_browser(
            ref: str, request: Request,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> RedirectResponse:
            principal, form = await checked_browser_form(
                request, sid, fields=frozenset({
                    "csrf", "action_id", "case_version", "question_revision",
                    "finding_revision", "evidence_binding", "note",
                }), max_bytes=4096, max_fields=8, max_value_length=2100,
            )
            try:
                evidence_revision_text, evidence_ref = form["evidence_binding"].split(":", 1)
                evidence_revision = form_version(evidence_revision_text, zero_allowed=False)
            except (ValueError, TypeError) as exc:
                raise HTTPException(422, detail="INVALID_EXPORT_RESEARCH_FINDING") from exc
            try:
                finding_ledger = export_research_finding_ledger or technical_review_ledger
                result = finding_ledger.record_export_research_finding(
                    ref, principal,
                    expected_case_version=form_version(
                        form["case_version"], zero_allowed=False,
                    ),
                    expected_question_revision=form_version(
                        form["question_revision"], zero_allowed=False,
                    ),
                    expected_finding_revision=form_version(
                        form["finding_revision"],
                    ),
                    evidence_revision=evidence_revision,
                    action_id=form["action_id"],
                    evidence_ref=evidence_ref, note=form["note"],
                )
            except ExportResearchFindingConflict as exc:
                raise HTTPException(
                    409, detail="EXPORT_RESEARCH_FINDING_CHANGED",
                ) from exc
            except (LedgerIntegrityError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
                ) from exc
            except ExportFindingStorageError as exc:
                raise HTTPException(503, detail="TECHNICAL_REVIEW_UNAVAILABLE") from exc
            except ValueError as exc:
                raise HTTPException(
                    422, detail="INVALID_EXPORT_RESEARCH_FINDING",
                ) from exc
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return RedirectResponse(
                "/admin/export/research/drafts/" + quote(ref), status_code=303,
            )

        if export_source_connectors is not None:
            @router.post("/admin/export/research/drafts/{ref}/evidence-reference/capture")
            async def export_demo_evidence_reference_capture_browser(
                ref: str, request: Request,
                sid: str | None = Cookie(default=None, alias=cookie_name),
            ) -> RedirectResponse:
                principal, form = await checked_browser_form(
                    request, sid,
                    fields=frozenset({
                        "csrf", "action_id", "case_version", "question_revision",
                        "evidence_revision", "connector_ref",
                    }),
                )
                try:
                    result = capture_export_source_reference(
                        technical_review_ledger, export_source_connectors, ref,
                        principal,
                        expected_case_version=form_version(
                            form["case_version"], zero_allowed=False,
                        ),
                        expected_question_revision=form_version(
                            form["question_revision"], zero_allowed=False,
                        ),
                        expected_evidence_revision=form_version(
                            form["evidence_revision"],
                        ),
                        action_id=form["action_id"],
                        connector_ref=form["connector_ref"],
                    )
                except ExportEvidenceReferenceConflict as exc:
                    raise HTTPException(
                        409, detail="EXPORT_EVIDENCE_REFERENCE_CHANGED",
                    ) from exc
                except ExportSourceConnectorUnavailable as exc:
                    raise HTTPException(
                        503, detail="EXPORT_SOURCE_CONNECTOR_UNAVAILABLE",
                    ) from exc
                except (LedgerIntegrityError, sqlite3.Error) as exc:
                    raise HTTPException(
                        503, detail="TECHNICAL_REVIEW_UNAVAILABLE",
                    ) from exc
                except ValueError as exc:
                    raise HTTPException(
                        422, detail="INVALID_EXPORT_SOURCE_CONNECTOR",
                    ) from exc
                if result is None:
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                return RedirectResponse(
                    "/admin/export/research/drafts/" + quote(ref),
                    status_code=303,
                )

    if authority_enquiry_ledger is not None:
        @router.get("/admin/gate-evidence/{domain}/readiness")
        def technical_readiness_matrix(
            domain: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            permitted = next((
                dossier for dossier in visible_dossiers(
                    Principal(session.subject, session.roles)
                )
                if dossier.domain == domain and dossier.role in session.roles
            ), None)
            if permitted is None:
                # Governance may read public gate metadata, but must not
                # implicitly gain a domain operator's technical worklist.
                raise HTTPException(404, detail="READINESS_MATRIX_NOT_FOUND")
            matrix = authority_enquiry_ledger.read_readiness_matrix(
                Principal(session.subject, session.roles), domain,
            )
            rows = []
            for item in matrix["items"]:
                stage = item["technical_handoff"]["technical_state"]
                checks = '؛ '.join(
                    check["check_kind"] + ": " + check["technical_state"]
                    for check in item["authority_checks"]
                )
                rows.append(
                    '<li><strong>' + escape(item["evidence_id"]) +
                    '</strong> — ارجاع: ' + escape(stage) +
                    ' — استعلام‌ها: ' + escape(checks) +
                    ' — پذیرش: مسدود</li>'
                )
            body = (
                '<article class="panel"><h2>ماتریس فنی شواهد ' +
                escape(domain) + '</h2>'
                '<p>تمام وضعیت‌ها در یک تراکنش واحد، پس از بررسی یکپارچگی تاریخچه خوانده شده‌اند.</p>'
                '<p>این اطلاعات نسخه‌بسته و غیرعملیاتی هستند؛ '
                'اصالت منشأ، حق استفاده، صلاحیت بازبین و تصویب Business '
                'همچنان تأیید نشده‌اند.</p>'
                '<ul>' + ''.join(rows) + '</ul>'
                '<p><a href="/admin/gate-evidence/' +
                escape(domain, quote=True) +
                '">بازگشت به اسناد شواهد این حوزه</a></p></article>'
            )
            return page("روناس — ماتریس فنی شواهد آزمایشی",
                        body, logged_in=True)

    @router.get("/admin/gate-evidence/{domain}")
    def gate_evidence_detail(
        domain: str,
        sid: str | None = Cookie(default=None, alias=cookie_name),
    ) -> HTMLResponse:
        try:
            session = flow.session(sid)
        except InvalidToken:
            raise HTTPException(401, detail="INVALID_SESSION") from None
        allowed = next((
            d for d in visible_dossiers(
                Principal(session.subject, session.roles)
            ) if d.domain == domain
        ), None)
        if allowed is None:
            raise HTTPException(404, detail="GATE_DOSSIER_NOT_FOUND")
        verify_pinned_business_sources()
        current = dossier_detail(allowed)
        handoff_states: dict[str, str] = {}
        enquiry_states: dict[str, str] = {}
        preflight_notice = ""
        if (gate_handoff_ledger is not None
                and allowed.role in session.roles):
            preflight = gate_handoff_ledger.preflight_worklist(
                Principal(session.subject, session.roles), domain,
            )
            handoff_states = {
                item["evidence_id"]: item["technical_state"]
                for item in preflight["items"]
            }
            preflight_notice = (
                '<p>کنترل پذیرش شواهد: مسدود؛ اصالت منشأ، حق استفاده '
                'و صلاحیت بازبین تأیید نشده است. حتی تطبیق هش DEMO '
                'برای تأیید Business کافی نیست.</p>'
            )
        if (authority_enquiry_ledger is not None
                and allowed.role in session.roles):
            enquiry = authority_enquiry_ledger.read_check_status(
                Principal(session.subject, session.roles), domain,
            )
            grouped = {}
            for item in enquiry["items"]:
                if item["technical_state"] != "NO_REQUEST":
                    grouped.setdefault(item["evidence_id"], []).append(
                        item["check_kind"] + ": " + item["technical_state"]
                    )
            enquiry_states = {ref: "؛ ".join(parts) for ref, parts in grouped.items()}
            preflight_notice += (
                '<p>ارجاع‌های بررسی مرجع معتبر فقط فنی هستند؛ '
                'تأیید واقعی منشأ، حقوق یا صلاحیت بازبین هنوز وجود ندارد.</p>'
                '<p><a href="/admin/gate-evidence/' +
                escape(domain, quote=True) +
                '/readiness">نمای یکپارچه پیگیری فنی این حوزه</a></p>'
            )
        # All URLs are derived exclusively from pinned repository constants,
        # not from a query or arbitrary user-provided source path.
        official_source = (
            "https://github.com/mahdimarzooghi4-debug/Ronas/blob/"
            + BUSINESS_SOURCE_SHA + "/" + current["source_path"]
        )
        issue = (
            "https://github.com/mahdimarzooghi4-debug/Ronas/issues/"
            + str(current["gate_issue"])
        )
        evidence_rows = ''.join(
            '<li><strong>' + escape(e["id"]) + '</strong> — '
            + escape(e["label"]) + ': '
            + escape(e["source_status"])
            + (' · پیگیری ارجاع فنی: '
               + escape(handoff_states[e["id"]])
               if e["id"] in handoff_states else '')
            + (' · پیگیری استعلام فنی: ' + escape(enquiry_states[e["id"]])
               if e["id"] in enquiry_states else '')
            + '</li>'
            for e in current["evidence_items"]
        )
        body = (
            '<article class="panel"><h2>پرونده شواهد ' +
            escape(current["domain"]) + '</h2>'
            '<p>این نمای نسخه‌بسته، تصمیم زنده گیت یا مدرک تأییدشده نیست.</p>'
            '<p>وضعیت در نسخه منبع: OPEN — مسئول بررسی هنوز تعیین نشده.</p>'
            '<p>فایل‌های همین نسخه محلی با شناسه Git مورد انتظار مطابقت دارند؛ '
            'این تأیید، وضعیت زنده گیت یا نسخه جاری PR نیست.</p>'
            '<p>شناسه نسخه منبع: <code>' + escape(BUSINESS_SOURCE_SHA)
            + '</code></p>'
            '<ul>' + evidence_rows + '</ul>'
            '<p><a href="' + escape(official_source, quote=True) +
            '">سند مبدأ نسخه‌بسته</a> — '
            '<a href="' + escape(issue, quote=True) +
            '">گیت Business در GitHub</a></p>'
            + preflight_notice +
            '<p>یادداشت بررسی فنی، تأیید اعتبار سند یا تصویب Business نیست.</p>'
            '<p>هیچ تأیید، ثبت مدرک، بودجه، معامله یا تصمیمی در این نما انجام نمی‌شود.</p>'
            '<p><a href="/admin">بازگشت به مدیریت روناس</a></p>'
            '</article>'
        )
        return page("مدیریت روناس — وضعیت نسخه‌بسته شواهد گیت",
                    body, logged_in=True)

    @router.get("/admin/operational-readiness/{domain}")
    def operational_readiness_page(
        domain: str,
        sid: str | None = Cookie(default=None, alias=cookie_name),
    ) -> HTMLResponse:
        try:
            session = flow.session(sid)
        except InvalidToken:
            raise HTTPException(401, detail="INVALID_SESSION") from None
        if not any(
            d.domain == domain for d in visible_dossiers(
                Principal(session.subject, session.roles)
            )
        ):
            raise HTTPException(404, detail="READINESS_NOT_FOUND")
        summary = readiness(domain)
        needs = ''.join(
            '<li>' + escape(item["label"]) +
            ' — مدرک معتبر هنوز احراز نشده است.</li>'
            for item in summary["pending_evidence"]
        )
        sources = ''.join(
            '<li><strong>' + escape(item["name"]) + '</strong>'
            ' — حق استفاده و آموزش AI احراز نشده؛ موانع: '
            + escape("، ".join(item["review_flags"])) +
            ' · <a href="' + escape(item["official_terms_urls"][0], quote=True)
            + '">شرایط رسمی منبع</a></li>'
            for item in summary["sources_not_licensed"]
        )
        source_box = (
            '<h3>منابع غربال‌شده، نه دارای مجوز استفاده</h3><ul>'
            + sources + '</ul>'
            if sources else ''
        )
        finance = (
            '<h3>ممیزی عددی منبع، نه بودجه</h3><p>اختلاف سرمایه نقل‌شده: '
            + str(summary["source_arithmetic_not_budget"][
                "arithmetic_unexplained_difference"
            ]) + ' میلیون تومان؛ تفسیر حسابداری هنوز تصویب نشده است.</p>'
            if domain == "FINANCE" else ''
        )
        issue = ("https://github.com/mahdimarzooghi4-debug/Ronas/issues/"
                 + str(summary["gate_issue"]))
        body = (
            '<article class="panel"><h2>میزکار تصمیم عملیاتی — '
            + escape(domain) + '</h2>'
            '<p>وضعیت در نسخه پیش‌نویس: OPEN. این صفحه وضعیت '
            'زنده GitHub یا تصویب مسئول را نشان نمی‌دهد.</p>'
            '<h3>شواهد لازم برای تصمیم واقعی</h3><ul>'
            + needs + '</ul>'
            '<p>حوزه‌های پیشنهادی، نه مجوز اجرا: '
            + escape("، ".join(summary["candidate_scopes_not_approved"])
                     or "هنوز انتخاب نشده") + '</p>'
            + source_box + finance +
            '<p>دریافت داده واقعی، برنامه کشت، پژوهش تجاری تأییدشده، '
            'آموزش مدل، پرداخت و قرارداد عملیاتی در این صفحه فعال نیست.</p>'
            '<p><a href="' + escape(issue, quote=True) +
            '">پیگیری مدارک و تصمیم گیت در GitHub</a></p>'
            '<p><a href="/admin">بازگشت به مدیریت روناس</a></p></article>'
        )
        return page("روناس — شواهد لازم برای تصمیم عملیاتی",
                    body, logged_in=True)

    @router.get("/admin/finance/source-arithmetic")
    def finance_source_review_page(
        sid: str | None = Cookie(default=None, alias=cookie_name),
    ) -> HTMLResponse:
        try:
            session = flow.session(sid)
        except InvalidToken:
            raise HTTPException(401, detail="INVALID_SESSION") from None
        if "finance" not in session.roles:
            raise HTTPException(404, detail="SOURCE_REVIEW_NOT_FOUND")
        verify_pinned_business_sources()
        report = source_arithmetic()
        body = (
            '<article class="panel"><h2>بررسی عددی منبع FIN-002 '
            '(صرفاً سند تاریخی)</h2>'
            '<p>همه مقادیر برحسب میلیون تومان و نقلِ طرح‌نامه‌اند؛ '
            'بودجه، هزینه واقعی، وجه نقد یا سرمایه مورد تأیید نیستند.</p>'
            '<ul><li>سرمایه اولیه نقل‌شده: '
            + str(report["reported_initial_capital"]) + '</li>'
            '<li>تجهیزات: ' + str(report["reported_equipment"]) + '</li>'
            '<li>پیش از بهره‌برداری: '
            + str(report["reported_pre_operating"]) + '</li>'
            '<li>جمع دو مؤلفه: '
            + str(report["arithmetic_component_sum"]) + '</li>'
            '<li>اختلاف با رقم اولیه: '
            + str(report["arithmetic_unexplained_difference"]) + '</li>'
            '<li>هزینه عملیاتی سال نخست در منبع: '
            + str(report["reported_year_one_operating_cost"]) + '</li></ul>'
            '<p>برابری اختلاف و هزینه سال نخست یک مشاهده عددی است؛ '
            'نوع سرمایه/هزینه، خطا یا دوباره‌شماری را اثبات نمی‌کند.</p>'
            '<p>FIN-001 تا FIN-007 و گیت مالی #4 باز هستند. '
            'هیچ نرخ، بودجه اصلاحی، پرداخت یا تسویه فعال نیست.</p>'
            '<p>هش نسخه فایل مالی: <code>'
            + escape(report["source_blob_sha"]) + '</code></p>'
            '<p><a href="/admin/gate-evidence/FINANCE">'
            'شواهد تصمیم مالی</a> · <a href="/admin">'
            'بازگشت به مدیریت روناس</a></p></article>'
        )
        return page("روناس — تطبیق ارقام منبع مالی", body, logged_in=True)

    @router.get("/admin")
    def admin_ui(
        sid: str | None = Cookie(default=None, alias=cookie_name),
        domestic_after_ref: str | None = None,
        export_after_ref: str | None = None,
    ) -> HTMLResponse:
        try:
            session = flow.session(sid)
        except InvalidToken:
            session = None
        grants = session.roles if session is not None else None
        if grants is None:
            return page("مدیریت روناس — ورود الزامی", '<p>ورود امن لازم است.</p>',
                        logged_in=False, code=401, login_return_path="/admin")
        active = [(name, label) for name, label in ADMIN_ROLES.items() if name in grants]
        if not active:
            return page("دسترسی مدیریت مجاز نیست",
                        '<p>مجوز ورود به هیچ‌یک از چهار حوزه مدیریت وجود ندارد.</p>',
                        logged_in=True, code=403)
        cards = []
        try:
            verify_pinned_business_sources()
            gate_source_usable = True
        except BusinessSourceSnapshotError:
            # Keep unrelated local admin read models available, while
            # withholding all obsolete gate links and showing a warning.
            gate_source_usable = False
        for role, label in active:
            note = {
                "domestic_ops": "نمونه پرونده خانوار DEMO-H01؛ رضایت و تأیید کارشناس وجود ندارد.",
                "export_ops": "نمونه پژوهش DEMO-SOURCE-01؛ حقوق منبع و خریدار احراز نشده است.",
                "finance": "پرداخت، تسویه و انتقال وجه غیرفعال هستند.",
                "governance": "راهبری به معنی مجوز خودکار مالی، کشاورزی یا صادرات نیست.",
            }[role]
            worklist = ""
            if technical_review_ledger is not None and session is not None:
                if role == "domestic_ops":
                    worklist = technical_worklist(
                        "DOMESTIC", Principal(session.subject, session.roles),
                        domestic_after_ref,
                    )
                elif role == "export_ops":
                    worklist = (
                        '<p><a href="/admin/export/research">'
                        'مرور و فیلتر پرونده‌های پژوهش صادرات</a></p>'
                        + technical_worklist(
                            "EXPORT", Principal(session.subject, session.roles),
                            export_after_ref,
                        )
                    )
            domain = {
                "domestic_ops": "DOMESTIC",
                "export_ops": "EXPORT",
                "finance": "FINANCE",
            }.get(role)
            # Governance can inspect all public Business gate metadata, but
            # this does not grant access to case/evidence private records.
            domains = [domain] if domain else (
                ["DOMESTIC", "EXPORT", "FINANCE"]
                if role == "governance" else []
            )
            gate_links = (''.join(
                '<p><a href="/admin/gate-evidence/' + key
                + '">شواهد باز Business — ' + key + '</a>'
                ' (صرفاً نسخه‌بسته و غیرعملیاتی)</p>'
                for key in domains
            ) if gate_source_usable else
                '<p>نسخه محلی اسناد شواهد معتبر نیست؛ '
                'پیوندهای گیت موقتاً غیرفعال‌اند.</p>')
            if gate_source_usable:
                try:
                    verify_decision_sources()
                except BusinessSourceSnapshotError:
                    gate_links += (
                        '<p>اسناد تصمیم عملیاتی با نسخه تأییدنشده تغییر '
                        'کرده‌اند؛ پیوندها غیرفعال هستند.</p>'
                    )
                else:
                    gate_links += ''.join(
                        '<p><a href="/admin/operational-readiness/'
                        + key + '">شواهد لازم برای تصمیم عملیاتی — '
                        + key + '</a></p>'
                        for key in domains
                    )
            if role == "finance" and gate_source_usable:
                gate_links += (
                    '<p><a href="/admin/finance/source-arithmetic">'
                    'ممیزی عددی نسخه‌بسته FIN-002 (بدون تصویب بودجه)'
                    '</a></p>'
                )
            cards.append('<article class="panel"><h2>' + escape(label) + '</h2><p>'
                         + escape(note) + '</p>' + worklist + gate_links
                         + '</article>')
        return page("مدیریت روناس — پنل واحد با دسترسی مجزا",
                    '<div class="columns">' + ''.join(cards) + '</div>', logged_in=True)

    return router
