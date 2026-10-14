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
from .export_source_connector import (
    ExportSourceConnectorRegistry, ExportSourceConnectorUnavailable,
    capture_export_source_reference,
)
from .scoped_drafts import _synthetic_ref
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
)
from .domestic_preparation_preview import (
    REVIEW_STATES, domestic_preparation_preview,
)
from .gate_evidence_handoff_sqlite import SqliteSyntheticGateEvidenceHandoff
from .gate_evidence_authority_enquiry_sqlite import SqliteSyntheticAuthorityEnquiryLedger
from .domestic_surplus_publication_api import publication_readiness_snapshot
from .domestic_surplus_drafts import (
    SurplusDraftConflict, SqliteSyntheticSurplusDraftLedger,
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
  if (!file || !digestInput) { say('ابتدا یک فایل تصویر یا PDF انتخاب کنید.'); return; }
  if (file.size < 1 || file.size > 8 * 1024 * 1024) { say('اندازه فایل باید حداکثر ۸ مگابایت باشد.'); return; }
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
    if (!uploaded.ok) throw Error('UPLOAD_REJECTED');
    const artifact = await uploaded.json();
    if (!/^[0-9a-f]{64}$/.test(artifact.digest) || artifact.byte_length !== file.size
        || artifact.content_type !== file.type || artifact.stored !== true) throw Error('UPLOAD_INVALID');
    digestInput.value = artifact.digest;
    const fields = new URLSearchParams();
    for (const [key, value] of new FormData(form).entries())
      if (typeof value === 'string') fields.append(key, value);
    const saved = await fetch(form.action, {
      method:'POST', credentials:'same-origin', cache:'no-store',
      headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:fields
    });
    if (!saved.ok) throw Error('RECEIPT_REJECTED');
    window.location.assign(saved.url);
  } catch {
    say('ثبت فایل یا رسید انجام نشد؛ وضعیت را تازه کنید و دوباره تلاش کنید.');
    if (button) button.disabled = false;
  }
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
    household_surplus_draft_ledger: SqliteSyntheticSurplusDraftLedger | None = None,
) -> APIRouter:
    if export_source_connectors is not None and (
            not isinstance(export_source_connectors, ExportSourceConnectorRegistry)
            or technical_review_ledger is None):
        raise ValueError("Export connector UI requires the explicit review ledger")
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
            not isinstance(household_surplus_draft_ledger,
                            SqliteSyntheticSurplusDraftLedger)
            or not isinstance(household_input_ledger,
                              SqliteSyntheticHouseholdProfileLedger)
            or household_input_ledger is not technical_review_ledger
            or not callable(household_profile_access_authority)
            or household_surplus_draft_ledger._owner_access_authority
                != household_profile_access_authority):
        raise ValueError(
            "surplus draft UI requires the shared owner-scoped household authority"
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
                '<nav aria-label="فیلتر پیگیری پرونده‌های خانوار">'
                + navigation + '</nav>' + body
            )
        if result["next_cursor"]:
            body += ('<a href="/?household_technical_state='
                     + quote(technical_state) + '&household_after_ref='
                     + quote(result["next_cursor"]) + '">پرونده‌های بعدی</a>')
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
                    '<section><h3>' + escape(item["stage_ref"]) + '</h3>'
                    '<p>نسخه رسید: ' + str(item["revision"])
                    + ' · ' + escape(state) + '</p>'
                    '<p>زمان ثبت: ' + escape(item["observed_at"]) + '</p>'
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
                + '">بازگشت به پرونده تخصیص‌یافته</a></p></article>'
            )
            return page("روناس — بررسی ساختار پیشنهاد کشت (DEMO)",
                        body, logged_in=True)

    if agronomy_workspace is not None:
        @router.get("/agronomy/assigned-drafts/{ref}/expert-review-preparation")
        def agronomy_expert_review_preparation_page(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            try:
                dossier = agronomy_workspace.read_assigned_expert_review_preparation(
                    ref, Principal(session.subject, session.roles),
                )
            except LedgerIntegrityError as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if dossier is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            if (dossier["engine"] != "DOMESTIC"
                    or dossier["case_status"] != "DRAFT_ONLY"
                    or dossier["combined_review_status"] != "NOT_AUTHORIZED_FOR_DECISION"
                    or dossier["plan_accepted"] is not False
                    or dossier["real_data"] is not False
                    or dossier["new_advice_enabled"] is not False):
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                )
            descriptions = {
                "HOUSEHOLD_INPUT_ADEQUACY": (
                    "۱. کفایت اطلاعات خانوار",
                    "نسخه ساختاری به معنی کفایت داده یا رضایت خانوار نیست."),
                "SCIENTIFIC_BASIS_AND_USE_RIGHTS": (
                    "۲. منشأ علمی و حقوق استفاده",
                    "منبع نسخه‌دار به معنی حق استفاده یا اعتبار علمی نیست."),
                "INDIVIDUAL_CULTIVATION_PROPOSAL": (
                    "۳. بررسی خود برنامه پیشنهادی",
                    "ساختار پیشنهادی AI تأیید برنامه توسط متخصص نیست."),
            }
            items = []
            for part in dossier["tracks"]:
                label, note = descriptions[part["track"]]
                items.append(
                    '<section><h3>' + escape(label) + '</h3>'
                    '<p>وضعیت ساختاری: ' + escape(part["observed_structure"])
                    + '</p><p>' + escape(note) + '</p>'
                    '<p>نتیجه بررسی مستقل: ثبت نشده.</p></section>'
                )
            body = (
                '<article class="panel"><h2>آماده‌سازی سه محور بررسی متخصص '
                '(فقط DEMO)</h2>'
                '<p>پرونده: ' + escape(dossier["case_ref"])
                + ' · نسخه ' + str(dossier["case_version"]) + '</p>'
                + ''.join(items)
                + '<p>این سه محور مستقل‌اند. هیچ تصمیم کارشناسی واقعی، '
                'رضایت معتبر خانوار، احراز صلاحیت، مجوز علمی یا '
                'تأیید برنامه ثبت نشده است.</p>'
                '<p>تأیید، رد، اصلاح برنامه، ثبت گزارش کشت '
                'و توصیه جدید در این صفحه غیرفعال‌اند.</p>'
                + ('<p><a href="/agronomy/assigned-drafts/'
                   + quote(ref) + '/review-questions">'
                   'تاریخچه پرسش‌های آزمایشی سه محور</a></p>'
                   if isinstance(agronomy_workspace.ledger,
                                 SqliteSyntheticExpertQuestionLedger)
                   else '')
                + '<p><a href="/agronomy/assigned-drafts/' + quote(ref)
                + '">بازگشت به پرونده تخصیص‌یافته</a></p></article>'
            )
            return page(
                "روناس — آماده‌سازی بررسی مستقل برنامه کشت (DEMO)",
                body, logged_in=True,
            )

    if (agronomy_workspace is not None
            and isinstance(agronomy_workspace.ledger,
                           SqliteSyntheticExpertQuestionLedger)):
        @router.get("/agronomy/assigned-drafts/{ref}/review-questions")
        def agronomy_question_history_page(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            try:
                notes = agronomy_workspace.read_assigned_synthetic_review_questions(
                    ref, Principal(session.subject, session.roles),
                )
            except LedgerIntegrityError as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            if notes is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            if (notes["engine"] != "DOMESTIC"
                    or notes["qualification_verified"] is not False
                    or notes["questions_are_review_decisions"] is not False
                    or notes["plan_accepted"] is not False
                    or notes["real_data"] is not False):
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                )
            # Historical questions must remain visible after an input or
            # scientific source changes. Failure to obtain a CURRENT pinned
            # synthetic proposal only disables new form commands.
            current_proposal = None
            try:
                current_proposal = (
                    agronomy_workspace.read_assigned_proposal_structure(
                        ref, Principal(session.subject, session.roles),
                    )
                )
            except LedgerIntegrityError:
                pass
            current_stage_observations = []
            if (household_stage_context_authority is not None
                    and isinstance(
                        agronomy_workspace.ledger,
                        SqliteSyntheticHouseholdProfileLedger,
                    )):
                try:
                    stage_data = agronomy_workspace.read_assigned_stage_observations(
                        ref, Principal(session.subject, session.roles),
                        context_authority=household_stage_context_authority,
                    )
                    if stage_data is not None:
                        current_stage_observations = [
                            item for item in stage_data["observations"]
                            if item["current"]
                        ]
                except (StageObservationConflict, LedgerIntegrityError, sqlite3.Error):
                    current_stage_observations = []
            expert_forms = ""
            if (current_proposal is not None
                    and current_proposal["proposal_status"]
                    == "STRUCTURE_ONLY_UNREVIEWED"
                    and type(current_proposal.get("input_revision")) is int):
                track_options = (
                    ("HOUSEHOLD_INPUT_ADEQUACY", "پرسش درباره کفایت داده"),
                    ("SCIENTIFIC_BASIS_AND_USE_RIGHTS", "پرسش درباره منشأ علمی"),
                    ("INDIVIDUAL_CULTIVATION_PROPOSAL", "پرسش درباره پیشنهاد کشت"),
                )
                for track, label in track_options:
                    revision = max((
                        q["question_revision"] for q in notes["questions"]
                        if q["track"] == track
                    ), default=0)
                    expert_forms += (
                        '<form method="post" action="/agronomy/assigned-drafts/'
                        + quote(ref) + '/review-questions/demo-question">'
                        '<input type="hidden" name="csrf" value="'
                        + escape(session.csrf, quote=True) + '">'
                        '<input type="hidden" name="action_id" value="DEMO-UI-Q-'
                        + secrets.token_hex(10).upper() + '">\n'

                        '<input type="hidden" name="case_version" value="'
                        + str(notes["case_version"]) + '">'
                        '<input type="hidden" name="input_revision" value="'
                        + str(current_proposal["input_revision"]) + '">'
                        '<input type="hidden" name="question_revision" value="'
                        + str(revision) + '">'
                        '<input type="hidden" name="track" value="'
                        + track + '">'
                        '<input type="hidden" name="stage_ref" value="">'
                        '<input type="hidden" name="stage_observation_revision" value="">'
                        '<input type="hidden" name="stage_observation_receipt_digest" value="">'
                        '<p><button type="submit">' + escape(label)
                        + ' (فقط DEMO)</button></p></form>'
                    )
                if household_stage_context_authority is not None:
                    revision = max((
                        q["question_revision"] for q in notes["questions"]
                        if q["track"] == "HOUSEHOLD_INPUT_ADEQUACY"
                    ), default=0)
                    for item in current_stage_observations:
                        expert_forms += (
                            '<form method="post" action="/agronomy/assigned-drafts/'
                            + quote(ref) + '/review-questions/demo-question">'
                            '<input type="hidden" name="csrf" value="'
                            + escape(session.csrf, quote=True) + '">'
                            '<input type="hidden" name="action_id" value="DEMO-UI-Q-'
                            + secrets.token_hex(10).upper() + '">\n'

                            '<input type="hidden" name="case_version" value="'
                            + str(notes["case_version"]) + '">'
                            '<input type="hidden" name="input_revision" value="'
                            + str(current_proposal["input_revision"]) + '">'
                            '<input type="hidden" name="question_revision" value="'
                            + str(revision) + '">'
                            '<input type="hidden" name="track" value="HOUSEHOLD_INPUT_ADEQUACY">'
                            '<input type="hidden" name="stage_ref" value="'
                            + escape(item["stage_ref"], quote=True) + '">'
                            '<input type="hidden" name="stage_observation_revision" value="'
                            + str(item["revision"]) + '">'
                            '<input type="hidden" name="stage_observation_receipt_digest" value="'
                            + escape(item["receipt_digest"], quote=True) + '">'
                            '<p><button type="submit">پرسش درباره رسید جاری '
                            + escape(item["stage_ref"]) + ' · نسخه '
                            + str(item["revision"]) + ' (فقط DEMO)</button></p></form>'
                        )
            inspections = ""
            if current_proposal is not None and type(
                current_proposal.get("input_revision")
            ) is int:
                input_revision = current_proposal["input_revision"]
                current_questions = [
                    q for q in notes["questions"]
                    if q["track"] == "HOUSEHOLD_INPUT_ADEQUACY"
                ]
                if current_questions:
                    recent = max(
                        current_questions, key=lambda q: q["question_revision"],
                    )
                    if (recent["bound_input_revision"] == input_revision
                            and recent["synthetic_household_response_received"]
                            and not recent["synthetic_receipt_inspected_not_reviewed"]):
                        inspections = (
                            '<form method="post" action="/agronomy/assigned-drafts/'
                            + quote(ref) + '/review-questions/demo-inspection">'
                            '<input type="hidden" name="csrf" value="'
                            + escape(session.csrf, quote=True) + '">'
                            '<input type="hidden" name="action_id" value="DEMO-UI-I-'
                            + secrets.token_hex(10).upper() + '">\n'

                            '<input type="hidden" name="case_version" value="'
                            + str(notes["case_version"]) + '">'
                            '<input type="hidden" name="input_revision" value="'
                            + str(input_revision) + '">'
                            '<input type="hidden" name="question_revision" value="'
                            + str(recent["question_revision"]) + '">'
                            '<button type="submit">ثبت مشاهده رسید پاسخ DEMO '
                            '(نه بررسی علمی)</button></form>'
                        )
            form_section = (
                '<section id="expert-demo-actions" aria-label="گردش آزمایشی پرسش متخصص">'
                '<h3>ثبت پرسش ساختاری آزمایشی</h3>'
                '<p>فقط شناسه‌های ثابت نمونه ثبت می‌شوند؛ '
                'هیچ پرسش واقعی، سند تخصصی یا نتیجه ارزیابی دریافت نمی‌شود.</p>'
                + (expert_forms if expert_forms else
                   '<p>نسخه معتبرِ ساختاری برای پرسش جدید موجود نیست.</p>')
                + inspections + '</section>'
            )
            descriptions = {
                "HOUSEHOLD_INPUT_ADEQUACY": "کفایت داده خانوار",
                "SCIENTIFIC_BASIS_AND_USE_RIGHTS": "منشأ علمی و حقوق استفاده",
                "INDIVIDUAL_CULTIVATION_PROPOSAL": "پیشنهاد اختصاصی کشت",
            }
            rows = ''.join(
                '<li>' + escape(descriptions[q["track"]])
                + ' · پرسش آزمایشی ' + str(q["question_revision"])
                + ' · نسخه ورودی ' + str(q["bound_input_revision"])
                + ' · ارجاع دلیل ' + escape(q["draft_reason_ref"])
                + ' · ارجاع شاهد ' + escape(q["draft_evidence_ref"])
                + (' · متصل به رسید مرحله ' + escape(q["stage_ref"])
                   + ' · نسخه ' + str(q["stage_observation_revision"])
                   if q.get("stage_ref") else '')
                + (' · پاسخ ساختاری خانوار دریافت شده (بررسی نشده)'
                   if q["synthetic_household_response_received"]
                   else ' · پاسخی ثبت نشده')
                + (' · رسید پاسخ مشاهده شد (بدون داوری تخصصی)'
                   if q["synthetic_receipt_inspected_not_reviewed"]
                   else '')
                + ' — صرفاً سابقه، بدون تأیید</li>'
                for q in notes["questions"]
            )
            body = (
                '<article class="panel"><h2>تاریخچه پرسش‌های بررسی '
                'متخصص (فقط DEMO)</h2>'
                '<p>پرونده ' + escape(notes["case_ref"])
                + ' · نسخه ' + str(notes["case_version"]) + '</p>'
                + ('<ul>' + rows + '</ul>' if rows else
                   '<p>هنوز پرسشی در نمونه آزمایشی ثبت نشده است.</p>')
                + '<p>پرسش‌ها بازخورد یا رأی علمی نیستند؛ '
                'تغییر نسخه ورودی یا منبع، اجازه استفاده از '
                'نسخه قدیمی برای تصمیم جدید را نمی‌دهد.</p>'
                '<p>فرم ثبت داده واقعی، تأیید برنامه، اصلاح تخصصی '
                'و مجوز انتشار در این صفحه وجود ندارد.</p>'
                + form_section
                + '<p><a href="/agronomy/assigned-drafts/'
                + quote(ref) + '/expert-review-preparation">'
                'بازگشت به سه محور بررسی</a></p></article>'
            )
            return page("روناس — تاریخچه پرسش‌های آزمایشی کارشناس",
                        body, logged_in=True, local_test_form=True)

        @router.post("/agronomy/assigned-drafts/{ref}/review-questions/demo-question")
        async def expert_demo_question(
            ref: str, request: Request,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> RedirectResponse:
            principal, form = await checked_browser_form(
                request, sid, fields=frozenset({
                    "csrf", "action_id", "case_version", "input_revision",
                    "question_revision", "track",
                }), optional_fields=frozenset({
                    "stage_ref", "stage_observation_revision",
                    "stage_observation_receipt_digest",
                }),
            )
            track = form["track"]
            if track not in (
                "HOUSEHOLD_INPUT_ADEQUACY",
                "SCIENTIFIC_BASIS_AND_USE_RIGHTS",
                "INDIVIDUAL_CULTIVATION_PROPOSAL",
            ):
                raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM")
            stage_fields = (
                form["stage_ref"], form["stage_observation_revision"],
                form["stage_observation_receipt_digest"],
            )
            if any(stage_fields) and not all(stage_fields):
                raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM")
            try:
                created = agronomy_workspace.record_assigned_synthetic_review_question(
                    ref, principal,
                    action_id=form["action_id"],
                    track=track,
                    expected_case_version=form_version(
                        form["case_version"], zero_allowed=False,
                    ),
                    expected_input_revision=form_version(
                        form["input_revision"], zero_allowed=False,
                    ),
                    expected_question_revision=form_version(
                        form["question_revision"],
                    ),
                    reason_ref="DEMO-UI-MISSING-REF",
                    evidence_ref="DEMO-UI-PENDING-REF",
                    stage_context_authority=household_stage_context_authority,
                    stage_ref=form["stage_ref"] or None,
                    expected_stage_observation_revision=(
                        form_version(form["stage_observation_revision"], zero_allowed=False)
                        if form["stage_observation_revision"] else None
                    ),
                    expected_stage_observation_receipt_digest=(
                        form["stage_observation_receipt_digest"] or None
                    ),
                )
            except ReviewQuestionConflict as exc:
                raise HTTPException(
                    409, detail="SYNTHETIC_QUESTION_VERSION_CONFLICT",
                ) from exc
            except LedgerIntegrityError as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM") from exc
            if created is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return RedirectResponse(
                "/agronomy/assigned-drafts/" + quote(ref) + "/review-questions",
                status_code=303,
            )

        @router.post(
            "/agronomy/assigned-drafts/{ref}/review-questions/demo-inspection"
        )
        async def expert_demo_receipt_inspection(
            ref: str, request: Request,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> RedirectResponse:
            principal, form = await checked_browser_form(
                request, sid, fields=frozenset({
                    "csrf", "action_id", "case_version", "input_revision",
                    "question_revision",
                }),
            )
            try:
                checked = agronomy_workspace.inspect_assigned_synthetic_response_receipt(
                    ref, principal,
                    action_id=form["action_id"],
                    expected_case_version=form_version(
                        form["case_version"], zero_allowed=False,
                    ),
                    expected_input_revision=form_version(
                        form["input_revision"], zero_allowed=False,
                    ),
                    expected_question_revision=form_version(
                        form["question_revision"], zero_allowed=False,
                    ),
                )
            except ReviewQuestionConflict as exc:
                raise HTTPException(
                    409, detail="SYNTHETIC_RECEIPT_CONTEXT_CHANGED",
                ) from exc
            except LedgerIntegrityError as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_AGRONOMY_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM") from exc
            if checked is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return RedirectResponse(
                "/agronomy/assigned-drafts/" + quote(ref) + "/review-questions",
                status_code=303,
            )

    if domestic_partner_workspace is not None:
        @router.get("/domestic-partners/my-preparation")
        def domestic_partner_preparation_page(
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            if not ({"local_buyer", "equipment_seller"} & session.roles):
                raise HTTPException(404, detail="PREVIEW_NOT_FOUND")
            try:
                overview = domestic_partner_workspace.own_preparation_overview(
                    Principal(session.subject, session.roles),
                )
            except SyntheticDomesticPartnerUnavailable as exc:
                raise HTTPException(
                    503, detail="DOMESTIC_PARTNER_PREVIEW_UNAVAILABLE",
                ) from exc
            labels = {
                "local_buyer": (
                    "خریدار محلی", "/local-buyer/my-preview",
                    ("هویت", "محصول درخواستی", "مقدار درخواستی",
                     "محل تحویل", "بودجه"),
                ),
                "equipment_seller": (
                    "فروشنده تجهیزات", "/equipment-seller/my-preview",
                    ("هویت", "فهرست تجهیزات", "موجودی",
                     "محدوده خدمات", "تناسب فنی تجهیزات"),
                ),
            }
            blocks = []
            for item in overview["items"]:
                role = item["role"]
                label, url, slots = labels[role]
                if (item["business_readiness"] != "NOT_EVALUATED"
                        or item["commercial_actions_enabled"] is not False
                        or item["data_submission_enabled"] is not False
                        or item["unknown_display_slots"] !=
                           list(DOMESTIC_PARTNER_FIELDS[role])):
                    raise HTTPException(
                        503, detail="DOMESTIC_PARTNER_PREVIEW_UNAVAILABLE",
                    )
                rows = ''.join(
                    '<li>' + escape(name) + ': هنوز داده‌ای ثبت نشده</li>'
                    for name in slots
                )
                blocks.append(
                    '<section class="section"><h3>' + escape(label) + '</h3>'
                    '<p>نمونه اختصاصی: ' + escape(item["profile_ref"])
                    + ' — نسخه ' + str(item["profile_version"]) + '</p>'
                    '<p>وضعیت بررسی آمادگی تجاری: انجام نشده (DEMO)</p>'
                    '<ul>' + rows + '</ul>'
                    '<p><a href="' + url
                    + '">مشاهده جزئیات همین نقش</a></p></section>'
                )
            content = (
                '<article class="panel"><h2>آماده‌سازی شخصی من (فقط DEMO)</h2>'
                '<p>فقط نمونه‌هایی نمایش داده می‌شوند که این حساب با نقش '
                'امضاشده و مجوز جاری اختصاصی به آن‌ها دسترسی دارد.</p>'
                '<p>این جایگاه‌ها صرفاً نمایشی و داده‌های آن‌ها نامشخص‌اند؛ '
                'معیار اجباری ثبت‌نام یا صلاحیت نیستند.</p>'
                + (''.join(blocks) if blocks else
                   '<p>هیچ پیش‌نمای مجاز آزمایشی موجود نیست.</p>')
                + '<p>ارتباط با خانوار، تطبیق خریدار و فروشنده، '
                'پیشنهاد، سفارش، قیمت، پرداخت و فعالیت تجاری فعال نیست.</p>'
                '<p><a href="/">بازگشت به محیط مشترک</a></p>'
                '</article>'
            )
            return page("روناس — نمای آماده‌سازی شخصی (DEMO)",
                        content, logged_in=True)

        def partner_page(
            role: str, sid: str | None,
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            try:
                view = domestic_partner_workspace.own_preview(
                    role, Principal(session.subject, session.roles),
                )
            except SyntheticDomesticPartnerUnavailable as exc:
                raise HTTPException(
                    503, detail="DOMESTIC_PARTNER_PREVIEW_UNAVAILABLE",
                ) from exc
            if view is None:
                raise HTTPException(404, detail="PREVIEW_NOT_FOUND")
            if (view["profile_state"] != "NOT_SUBMITTED_DEMO"
                    or view["commercial_actions_enabled"] is not False
                    or view["data_submission_enabled"] is not False
                    or tuple(view["preparation_fields"]) != DOMESTIC_PARTNER_FIELDS[role]
                    or any(value is not None
                           for value in view["preparation_fields"].values())):
                raise HTTPException(503, detail="DOMESTIC_PARTNER_PREVIEW_UNAVAILABLE")
            labels = {
                "local_buyer": (
                    "خریدار محلی",
                    ("هویت", "محصول درخواستی", "مقدار درخواستی",
                     "محل تحویل", "بودجه"),
                ),
                "equipment_seller": (
                    "فروشنده تجهیزات",
                    ("هویت", "فهرست تجهیزات", "موجودی",
                     "محدوده خدمات", "تناسب فنی تجهیزات"),
                ),
            }
            label, slots = labels[role]
            items = ''.join(
                '<li>' + name + ': ثبت نشده</li>' for name in slots
            )
            body = (
                '<article class="panel"><h2>پیش‌نمای شخصی '
                + label + ' (فقط DEMO)</h2>'
                '<p>شناسه نمونه: ' + escape(view["profile_ref"])
                + ' — نسخه ' + str(view["profile_version"]) + '</p>'
                '<p>وضعیت: NOT_SUBMITTED_DEMO؛ هیچ اطلاعاتی ارسال نشده است.</p>'
                '<h3>جایگاه‌های آماده‌سازی</h3><ul>' + items + '</ul>'
                '<p>این جایگاه‌ها معیار پذیرش یا اظهار واقعی نیستند. '
                'هویت، رضایت، موجودی یا تقاضا احراز نشده‌اند.</p>'
                '<p>خریدوفروش، پیشنهاد، سفارش، قیمت، پرداخت و '
                'تأیید تناسب فنی فعال نیستند.</p>'
                '<p><a href="/workspace/' + role
                + '">بازگشت به فضای کار نقش من</a></p>'
                '</article>'
            )
            return page("روناس — پیش‌نمای داخلی " + label + " (DEMO)",
                        body, logged_in=True)

        @router.get("/local-buyer/my-preview")
        def buyer_page(
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            return partner_page("local_buyer", sid)

        @router.get("/equipment-seller/my-preview")
        def equipment_page(
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            return partner_page("equipment_seller", sid)

    if export_supplier_workspace is not None:
        @router.get("/export-supplier/my-preview")
        def supplier_personal_preview(
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            try:
                view = export_supplier_workspace.own_preview(
                    Principal(session.subject, session.roles)
                )
            except SyntheticSupplierUnavailable as exc:
                raise HTTPException(
                    503, detail="SUPPLIER_PREVIEW_UNAVAILABLE",
                ) from exc
            if view is None:
                raise HTTPException(404, detail="PREVIEW_NOT_FOUND")
            fields = (
                "هویت حرفه‌ای", "محصولات", "ظرفیت تأمین",
                "زمان دسترسی", "تأسیسات", "مجوزهای صادراتی",
            )
            slots = ''.join(
                '<li>' + escape(label) + ': ثبت نشده</li>'
                for label in fields
            )
            body = (
                '<article class="panel"><h2>پیش‌نمای شخصی تأمین‌کننده '
                '(فقط آزمایشی)</h2>'
                '<p>شناسه نمونه: ' + escape(view["profile_ref"])
                + ' — نسخه ' + str(view["profile_version"]) + '</p>'
                '<p>وضعیت: NOT_SUBMITTED_DEMO؛ اطلاعاتی ارسال نشده است.</p>'
                '<h3>جایگاه‌های آماده‌سازی اظهار تأمین‌کننده</h3>'
                '<ul>' + slots + '</ul>'
                '<p>هیچ هویت حرفه‌ای، ظرفیت واقعی، مجوز، حق استفاده '
                'از منبع یا صلاحیت تجاری تأیید نشده است.</p>'
                '<p>خریدار، قیمت، سفارش، معامله، پرداخت و قرارداد فعال نیستند.'
                ' این صفحه فقط نمایش است و اطلاعات دریافت نمی‌کند.</p>'
                '<p><a href="/workspace/export_supplier">'
                'بازگشت به فضای تأمین‌کننده</a></p>'
                '</article>'
            )
            return page("روناس — پیش‌نمای تأمین‌کننده صادرات (DEMO)",
                        body, logged_in=True)

    @router.get("/")
    def public_ui(
        sid: str | None = Cookie(default=None, alias=cookie_name),
        household_after_ref: str | None = None,
        household_technical_state: str = "ALL",
    ) -> HTMLResponse:
        try:
            session = flow.session(sid)
        except InvalidToken:
            session = None
        grants = session.roles if session is not None else None
        if grants is None:
            return page("روناس — محیط کاربران و همکاران",
                        '<p>برای مشاهده بخش مربوط به نقش خود، با Keycloak وارد شوید. '
                        'این نسخه فقط داده ساختگی نمایش می‌دهد.</p>', logged_in=False)
        active = [(name, label) for name, label in USER_ROLES.items() if name in grants]
        cards = ''
        for name, label in active:
            if name == "household" and owned_case_ledger is not None:
                household = household_worklist(
                    Principal(session.subject, session.roles),
                    household_after_ref, household_technical_state,
                )
            else:
                household = (
                    '<p>پرونده ساختگی DEMO-H01؛ رضایت واقعی و تأیید متخصص وجود ندارد.</p>'
                    if name == "household" else ''
                )
            cards += ('<article class="panel"><h2>' + escape(label) + '</h2>'
                      '<p>وضعیت خدمت: نیازمند شواهد و مجوز عملیاتی.</p>'
                      '<p><a href="/workspace/' + quote(name)
                      + '">مشاهده فضای کار این نقش</a></p>'
                      + household + '</article>')
        if not cards:
            cards = '<p>هیچ نمای کاربری بیرونی برای دسترسی‌های فعلی شما تخصیص نیافته است.</p>'
        return page("روناس — محیط کاربران و همکاران", cards, logged_in=True)

    if owned_case_ledger is not None:
        @router.get("/my-drafts/{ref}/versions")
        def household_versions_page(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            principal = Principal(session.subject, session.roles)
            result = owned_case_ledger.read_owned_domestic_version_history(
                ref, principal,
            )
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            versions = ''.join(
                '<li>نسخه ' + str(entry["version"]) +
                (' — نسخه موجود (ساختگی)' if entry["is_current"]
                 else ' — نسخه پیشین (ساختگی)')
                + '</li>' for entry in result["versions"]
            )
            body = (
                '<article class="panel"><h2>تاریخچه نسخه‌های پرونده '
                + escape(result["ref"]) + '</h2>'
                '<p>این فهرست فقط نسخه‌های از پیش ثبت‌شده نمونه DEMO است؛ '
                'فرایند اصلاح واقعی، تاریخ تغییرات یا تأیید متخصص '
                'از این داده‌ها استنتاج نمی‌شود.</p>'
                '<p>وضعیت همه نسخه‌ها: DRAFT_ONLY؛ '
                'رضایت، طرح کشت و تأیید متخصص واقعی وجود ندارد.</p>'
                '<ol>' + versions + '</ol>'
                '<p><a href="/">بازگشت به پرونده‌های من</a></p>'
                '</article>'
            )
            return page("روناس — تاریخچه پرونده ساختگی من",
                        body, logged_in=True)

    if household_input_ledger is not None:
        @router.get("/my-drafts/{ref}/progress-notes")
        def household_progress_notes_page(
            ref: str, sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            result = household_input_ledger.read_owned_progress_notes(
                ref, Principal(session.subject, session.roles),
            )
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            notes = ''.join(
                '<li><time>' + escape(item["reported_at"]) + '</time> — '
                + escape(item["note"]) + '</li>' for item in result["notes"]
            )
            form = (
                '<form method="post" action="/my-drafts/' + quote(ref)
                + '/progress-notes">'
                '<input type="hidden" name="csrf" value="'
                + escape(session.csrf, quote=True) + '">'
                '<input type="hidden" name="action_id" value="DEMO-PROGRESS-'
                + secrets.token_hex(10).upper() + '">'
                '<input type="hidden" name="case_version" value="'
                + str(result["case_version"]) + '">'
                '<input type="hidden" name="revision" value="'
                + str(result["current_revision"]) + '">'
                '<label for="reported-at">زمان گزارش‌شده با منطقه زمانی</label>'
                '<input id="reported-at" name="reported_at" maxlength="40" '
                'placeholder="2026-10-12T10:30:00+03:30" required>'
                '<label for="progress-note">یادداشت ساختگی</label>'
                '<textarea id="progress-note" name="note" maxlength="150" '
                'required>DEMO: </textarea>'
                '<button type="submit">ثبت یادداشت DEMO</button></form>'
            )
            body = (
                '<article class="panel"><h2>یادداشت‌های پیشرفت پرونده (DEMO)</h2>'
                '<p>فقط متن ساختگی با پیشوند DEMO: و زمان واردشده توسط شما ثبت می‌شود. '
                'مرحله علمی از پیش تعریف‌شده یا ارزیابی محصول وجود ندارد.</p>'
                + ('<ol>' + notes + '</ol>' if notes else
                   '<p>یادداشتی ثبت نشده است.</p>')
                + '<p>این یادداشت‌ها داده واقعی، نظارت متخصص، ارزیابی علمی یا '
                'تأیید برنامه کشت محسوب نمی‌شوند و فقط برای مالک قابل مشاهده‌اند.</p>'
                + form
                + '<p><a href="/my-drafts/' + quote(ref)
                + '">بازگشت به پرونده من</a></p></article>'
            )
            return page("روناس — یادداشت پیشرفت ساختگی",
                        body, logged_in=True, local_test_form=True)

        @router.post("/my-drafts/{ref}/progress-notes")
        async def household_progress_note_submit(
            ref: str, request: Request,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> RedirectResponse:
            principal, form = await checked_browser_form(
                request, sid, fields=frozenset({
                    "csrf", "action_id", "case_version", "revision", "reported_at", "note",
                }),
            )
            try:
                saved = household_input_ledger.append_owned_progress_note(
                    ref, principal,
                    action_id=form["action_id"],
                    expected_case_version=form_version(
                        form["case_version"], zero_allowed=False,
                    ),
                    expected_revision=form_version(form["revision"]),
                    reported_at=form["reported_at"], note=form["note"],
                )
            except InputRevisionConflict as exc:
                raise HTTPException(409, detail="SYNTHETIC_PROGRESS_VERSION_CONFLICT") from exc
            except LedgerIntegrityError as exc:
                raise HTTPException(503, detail="SYNTHETIC_PROGRESS_HISTORY_UNAVAILABLE") from exc
            except ValueError as exc:
                raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM") from exc
            if saved is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return RedirectResponse(
                "/my-drafts/" + quote(ref) + "/progress-notes", status_code=303,
            )

        @router.get("/my-drafts/{ref}/input-revisions")
        def household_input_history_page(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            result = household_input_ledger.read_owned_input_revisions(
                ref, Principal(session.subject, session.roles),
            )
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            demo_form = (
                '<section id="domestic-demo-correction" aria-label="ثبت اصلاح صرفاً نمایشی">'
                '<h3>ثبت اصلاح نسخه DEMO</h3>'
                '<p>فقط یک سناریوی از پیش تعریف‌شده ثبت می‌شود. '
                'هیچ اطلاعات کشت، هویت یا رضایت واقعی دریافت نمی‌شود.</p>'
                '<form method="post" action="/my-drafts/'
                + quote(ref) + '/input-revisions/demo-correction">'
                '<input type="hidden" name="csrf" value="'
                + escape(session.csrf, quote=True) + '">'
                '<input type="hidden" name="action_id" value="DEMO-UI-D-'
                + secrets.token_hex(10).upper() + '">'
                '<input type="hidden" name="case_version" value="'
                + str(result["case_version"]) + '">'
                '<input type="hidden" name="input_revision" value="'
                + str(result["current_input_revision"] or 0) + '">'
                '<label for="domestic-demo-choice">سناریوی اصلاح نمونه</label>'
                '<select id="domestic-demo-choice" name="scenario">'
                + sample_choice_options(prefix="DEMO-MANIFEST-")
                + '</select><button type="submit">ثبت نسخه DEMO</button>'
                '</form></section>'
            )
            entries = ''.join(
                '<li>بازنگری آزمایشی ' + str(number) + '</li>'
                for number in result["input_revisions"]
            )
            body = (
                '<article class="panel"><h2>تاریخچه نمونه اصلاح اطلاعات خانوار '
                '(فقط DEMO)</h2>'
                '<p>پرونده: ' + escape(result["ref"]) + ' · نسخه '
                + str(result["case_version"]) + '</p>'
                + ('<ol>' + entries + '</ol>' if entries else
                   '<p>هنوز اثرانگشت نسخه‌ای در این نمونه ثبت نشده است.</p>')
                + '<p>صرفاً شناسه نسخه و اثرانگشت ساختگی ثبت می‌شود؛ '
                'هیچ محصول، آب، خاک، اطلاعات شخصی یا دستور کشت دریافت نمی‌شود.</p>'
                '<p>این سابقه رضایت آگاهانه، کفایت داده، '
                'تأیید متخصص یا برنامه کشت معتبر نیست.</p>'
                '<p>ثبت اصلاح واقعی و ارائه فرم رضایت '
                'در این پیش‌نمای آزمایشی فعال نیست.</p>'
                + demo_form
                + ('<p><a href="/my-drafts/' + quote(ref)
                   + '/question-responses">'
                   'پاسخ‌های آزمایشی من به پرسش کفایت اطلاعات</a></p>'
                   if isinstance(household_input_ledger,
                                 SqliteSyntheticExpertQuestionLedger) else '')
                + '<p><a href="/my-drafts/' + quote(ref)
                + '">بازگشت به پرونده من</a></p></article>'
            )
            return page("روناس — تاریخچه اصلاح آزمایشی اطلاعات خانوار",
                        body, logged_in=True, local_test_form=True)


        if (household_profile_schema is not None
                and household_profile_access_authority is not None
                and isinstance(household_input_ledger,
                               SqliteSyntheticHouseholdProfileLedger)):
            @router.get("/my-drafts/{ref}/cultivation-inputs")
            def household_cultivation_inputs_page(
                ref: str,
                sid: str | None = Cookie(default=None, alias=cookie_name),
            ) -> HTMLResponse:
                try:
                    session = flow.session(sid)
                except InvalidToken:
                    raise HTTPException(401, detail="INVALID_SESSION") from None
                principal = Principal(session.subject, session.roles)
                try:
                    permitted = household_profile_access_authority(
                        principal, ref, household_profile_schema.schema_ref,
                    )
                except Exception as exc:
                    raise HTTPException(
                        503, detail="HOUSEHOLD_PROFILE_AUTHORITY_UNAVAILABLE",
                    ) from exc
                if permitted is not True:
                    raise HTTPException(403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED")
                try:
                    result = household_input_ledger.read_owned_profile(ref, principal)
                except (LedgerIntegrityError, sqlite3.Error) as exc:
                    raise HTTPException(503, detail="HOUSEHOLD_PROFILE_UNAVAILABLE") from exc
                if result is None:
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                controls = []
                for field in household_profile_schema.fields:
                    value = result["current_values"].get(field.key, "")
                    label = escape(field.label)
                    key = escape(field.key, quote=True)
                    safe_value = escape(value, quote=True)
                    required = " required" if field.required else ""
                    if field.kind == "choice":
                        options = ['<option value="">انتخاب کنید</option>']
                        options.extend(
                            '<option value="' + escape(choice, quote=True) + '"'
                            + (" selected" if choice == value else "") + ">"
                            + escape(choice) + "</option>"
                            for choice in field.choices
                        )
                        control = '<select id="' + key + '" name="' + key + '"' + required + '>' + ''.join(options) + '</select>'
                    elif field.kind == "text":
                        control = '<textarea id="' + key + '" name="' + key + '" maxlength="' + str(field.max_length) + '"' + required + '>' + escape(value) + '</textarea>'
                    else:
                        control = '<input id="' + key + '" name="' + key + '" type="' + field.kind + '" maxlength="' + str(field.max_length) + '" value="' + safe_value + '"' + required + '>'
                    controls.append('<label for="' + key + '">' + label + '</label>' + control)
                history = ''.join(
                    '<li><a href="/my-drafts/' + quote(ref)
                    + '/cultivation-inputs/revisions/'
                    + str(item["revision"]) + '">مشاهده نسخه '
                    + str(item["revision"]) + '</a></li>'
                    for item in result["revisions"]
                )
                fields = frozenset(
                    {"csrf", "case_version", "profile_revision"}
                    | {field.key for field in household_profile_schema.fields}
                )
                body = (
                    '<article class="panel"><h2>اطلاعات ساختاریافته پرونده کشت</h2>'
                    '<p>پرونده ' + escape(ref) + ' · نسخه پرونده '
                    + str(result["case_version"]) + '</p>'
                    '<p>این فرم فقط برای پرونده آزمایشی محلی فعال است. '
                    'اطلاعات ساختگی وارد کنید؛ تأیید علمی یا برنامه کشت تولید نمی‌شود.</p>'
                    + ('<p role="status">نسخه فرم تغییر کرده است؛ '
                       'مقادیر نسخه قبلی برای این فرم نمایش داده نمی‌شوند.</p>'
                       if result["schema_changed"] else '')
                    + '<form method="post" action="/my-drafts/' + quote(ref)
                    + '/cultivation-inputs"><input type="hidden" name="csrf" value="'
                    + escape(session.csrf, quote=True) + '">'
                    '<input type="hidden" name="action_id" value="DEMO-PROFILE-'
                    + secrets.token_hex(10).upper() + '">'
                    '<input type="hidden" name="case_version" value="'
                    + str(result["case_version"]) + '">'
                    '<input type="hidden" name="profile_revision" value="'
                    + str(result["current_revision"]) + '">'
                    + ''.join(controls)
                    + '<button type="submit">ذخیره نسخه جدید</button></form>'
                    + ('<p><a href="/my-drafts/' + quote(ref)
                        + '/surplus-offers">فهرست و شروع پیش‌نویس مازاد</a></p>'
                        if household_surplus_draft_ledger is not None else '')
                    + ('<form method="get" action="/my-drafts/' + quote(ref)
                        + '/surplus-publication-readiness">'
                        '<label for="surplus-offer-ref">شناسه پیشنهاد مازاد (DEMO)</label>'
                        '<input id="surplus-offer-ref" name="offer_ref" required '
                        'pattern="DEMO-[A-Za-z0-9._:-]{1,96}" maxlength="101">'
                        '<button type="submit">بررسی آمادگی فنی</button></form>'
                        if household_surplus_publication_authority is not None else '')
                     + '<h3>تاریخچه اصلاح</h3>'
                    + ('<ol>' + history + '</ol>' if history else
                       '<p>هنوز نسخه‌ای ثبت نشده است.</p>')
                    + '<p>مقادیر فقط برای صاحب پرونده قابل مشاهده‌اند. '
                    'ثبت آن‌ها به معنی رضایت، تأیید متخصص یا پذیرش طرح نیست.</p>'
                    '<p><a href="/my-drafts/' + quote(ref) + '">بازگشت به پرونده</a></p>'
                    '</article>'
                )
                if household_stage_context_authority is not None:
                    body += (
                        '<p><a href="/my-drafts/' + quote(ref)
                        + '/stage-observations">ثبت و مشاهده رسیدهای مرحله‌ای</a></p>'
                    )
                return page("روناس — اطلاعات پرونده کشت",
                            body, logged_in=True, local_test_form=True)

            @router.get(
                "/my-drafts/{ref}/cultivation-inputs/revisions/{revision}",
                response_class=HTMLResponse,
            )
            def household_cultivation_inputs_revision_page(
                ref: str, revision: int,
                sid: str | None = Cookie(default=None, alias=cookie_name),
            ) -> HTMLResponse:
                try:
                    session = flow.session(sid)
                except InvalidToken:
                    raise HTTPException(401, detail="INVALID_SESSION") from None
                principal = Principal(session.subject, session.roles)
                try:
                    permitted = household_profile_access_authority(
                        principal, ref, household_profile_schema.schema_ref,
                    )
                except Exception as exc:
                    raise HTTPException(
                        503, detail="HOUSEHOLD_PROFILE_AUTHORITY_UNAVAILABLE",
                    ) from exc
                if permitted is not True:
                    raise HTTPException(403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED")
                try:
                    result = household_input_ledger.read_owned_profile_revision(
                        ref, principal, revision,
                    )
                except (LedgerIntegrityError, sqlite3.Error) as exc:
                    raise HTTPException(503, detail="HOUSEHOLD_PROFILE_UNAVAILABLE") from exc
                except ValueError as exc:
                    raise HTTPException(422, detail="INVALID_HOUSEHOLD_PROFILE_REVISION") from exc
                if result is None:
                    raise HTTPException(404, detail="PROFILE_REVISION_NOT_FOUND")
                if result["schema_changed"]:
                    values_html = (
                        '<p role="status">ساختار فرم پس از ثبت این نسخه تغییر کرده است؛ '
                        'برای جلوگیری از نمایش نادرست، مقادیر قدیمی پنهان شده‌اند.</p>'
                    )
                else:
                    rows = ''.join(
                        '<dt>' + escape(field.label) + '</dt><dd>'
                        + escape(result["values"].get(field.key, '')) + '</dd>'
                        for field in household_profile_schema.fields
                    )
                    values_html = '<dl>' + rows + '</dl>'
                body = (
                    '<article class="panel"><h2>نسخه تاریخی اطلاعات پرونده</h2>'
                    '<p>پرونده ' + escape(ref) + ' · نسخه '
                    + str(result["revision"]) + '</p>'
                    + values_html
                    + '<p>این سابقه فقط برای صاحب پرونده است و به معنی تأیید علمی، '
                    'پذیرش طرح یا رضایت برای مصرف دیگری نیست.</p>'
                    '<p><a href="/my-drafts/' + quote(ref)
                    + '/cultivation-inputs">بازگشت به اطلاعات پرونده</a></p>'
                    '</article>'
                )
                return page("روناس — نسخه تاریخی اطلاعات",
                            body, logged_in=True, local_test_form=True)

            if household_stage_context_authority is not None:
                if household_stage_artifact_store is not None:
                    @router.put("/my-drafts/{ref}/stage-observations/artifacts")
                    async def household_stage_artifact_upload(
                        ref: str, request: Request,
                        sid: str | None = Cookie(default=None, alias=cookie_name),
                    ) -> JSONResponse:
                        if request.headers.get("origin") != flow.config.origin:
                            raise HTTPException(403, detail="ORIGIN_REQUIRED")
                        try:
                            session = flow.session(sid)
                        except InvalidToken:
                            raise HTTPException(401, detail="INVALID_SESSION") from None
                        csrf = request.headers.get("x-csrf-token", "")
                        if not hmac.compare_digest(session.csrf, csrf):
                            raise HTTPException(403, detail="CSRF_REQUIRED")
                        principal = Principal(session.subject, session.roles)
                        try:
                            permitted = household_profile_access_authority(
                                principal, ref, household_profile_schema.schema_ref,
                            )
                        except Exception as exc:
                            raise HTTPException(
                                503, detail="HOUSEHOLD_PROFILE_AUTHORITY_UNAVAILABLE",
                            ) from exc
                        if permitted is not True:
                            raise HTTPException(403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED")
                        case_version = form_version(
                            request.headers.get("x-ronas-case-version", ""),
                            zero_allowed=False,
                        )
                        input_revision = form_version(
                            request.headers.get("x-ronas-input-revision", ""),
                            zero_allowed=False,
                        )
                        try:
                            context = household_stage_context_authority(ref)
                        except Exception as exc:
                            raise HTTPException(503, detail="STAGE_CONTEXT_UNAVAILABLE") from exc
                        stage_ref = request.headers.get("x-ronas-stage-ref", "")
                        requirements = request.headers.get(
                            "x-ronas-requirements-digest", "",
                        )
                        if (not isinstance(context, CurrentStageContext)
                                or context.case_ref != ref
                                or context.case_version != case_version
                                or context.input_revision != input_revision
                                or context.plan_digest != request.headers.get(
                                    "x-ronas-plan-digest", "",
                                )
                                or not any(
                                    item.stage_ref == stage_ref
                                    and item.observation_requirements_digest == requirements
                                    for item in context.requirements
                                )):
                            raise HTTPException(
                                409, detail="STAGE_OBSERVATION_CONTEXT_CHANGED",
                            )
                        declared = request.headers.get("content-length")
                        if declared:
                            try:
                                if int(declared) > MAX_ARTIFACT_BYTES:
                                    raise HTTPException(413, detail="STAGE_ARTIFACT_TOO_LARGE")
                            except ValueError as exc:
                                raise HTTPException(400, detail="INVALID_CONTENT_LENGTH") from exc
                        chunks, size = [], 0
                        async for chunk in request.stream():
                            size += len(chunk)
                            if size > MAX_ARTIFACT_BYTES:
                                raise HTTPException(413, detail="STAGE_ARTIFACT_TOO_LARGE")
                            chunks.append(chunk)
                        try:
                            artifact = household_stage_artifact_store.put(
                                principal.subject, ref + ":" + stage_ref,
                                request.headers.get("content-type", ""),
                                b"".join(chunks),
                            )
                        except ValueError as exc:
                            raise HTTPException(422, detail="INVALID_STAGE_ARTIFACT") from exc
                        except StageArtifactStoreError as exc:
                            raise HTTPException(
                                503, detail="STAGE_ARTIFACT_STORE_UNAVAILABLE",
                            ) from exc
                        return JSONResponse(status_code=201, content={
                            "digest": artifact.digest,
                            "content_type": artifact.content_type,
                            "byte_length": artifact.byte_length,
                            "stored": True,
                        })

                @router.get(
                    "/my-drafts/{ref}/stage-observations",
                    response_class=HTMLResponse,
                )
                def household_stage_observations_page(
                    ref: str,
                    sid: str | None = Cookie(default=None, alias=cookie_name),
                ) -> HTMLResponse:
                    try:
                        session = flow.session(sid)
                    except InvalidToken:
                        raise HTTPException(401, detail="INVALID_SESSION") from None
                    principal = Principal(session.subject, session.roles)
                    try:
                        permitted = household_profile_access_authority(
                            principal, ref, household_profile_schema.schema_ref,
                        )
                    except Exception as exc:
                        raise HTTPException(
                            503, detail="HOUSEHOLD_PROFILE_AUTHORITY_UNAVAILABLE",
                        ) from exc
                    if permitted is not True:
                        raise HTTPException(403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED")
                    try:
                        result = household_input_ledger.read_owned_stage_observations(
                            ref, principal,
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
                    if result is None:
                        raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                    current = result["current_context"]
                    progress_labels = {
                        "NOT_REPORTED": "هنوز رسیدی ثبت نشده",
                        "CURRENT_RECEIPT": "رسید جاری ثبت شده",
                        "HISTORICAL_RECEIPT": "فقط رسید تاریخی موجود است",
                    }
                    stage_progress_html = ''.join(
                        '<li>' + escape(item["stage_ref"]) + ' · '
                        + progress_labels[item["state"]]
                        + (' · نسخه ' + str(item["observation_revision"])
                           if item["observation_revision"] is not None else '')
                        + (' · رسید مشاهده شد (بدون داوری)'
                           if item["receipt_inspected"] else '')
                        + '</li>'
                        for item in result["stage_progress"]
                    )
                    forms = []
                    if current:
                        for index, stage in enumerate(current["stages"], start=1):
                            stage_ref = escape(stage["stage_ref"], quote=True)
                            requirements = escape(
                                stage["observation_requirements_digest"], quote=True,
                            )
                            if household_stage_artifact_store is not None:
                                form_attrs = (
                                    ' data-stage-upload data-upload-url="/my-drafts/'
                                    + quote(ref) + '/stage-observations/artifacts"'
                                )
                                artifact_control = (
                                    '<label for="artifact-' + str(index)
                                    + '">فایل مشاهده (تصویر یا PDF، حداکثر ۸ مگابایت)</label>'
                                    '<input id="artifact-' + str(index)
                                    + '" name="observation_file" type="file" '
                                    'accept="image/jpeg,image/png,image/webp,application/pdf" required>'
                                    '<input name="artifact_digest" type="hidden" value="">'
                                    '<p data-upload-status role="status" aria-live="polite"></p>'
                                )
                            else:
                                form_attrs = ''
                                artifact_control = (
                                    '<label for="artifact-' + str(index)
                                    + '">اثر انگشت مرجع مشاهده (SHA-256)</label>'
                                    '<input id="artifact-' + str(index)
                                    + '" name="artifact_digest" type="text" '
                                    'inputmode="latin" minlength="64" maxlength="64" '
                                    'pattern="[0-9a-f]{64}" required>'
                                )
                            form = (
                                '<form method="post" action="/my-drafts/'
                                + quote(ref) + '/stage-observations"' + form_attrs + '>'
                                + '<input type="hidden" name="csrf" value="'
                                + escape(session.csrf, quote=True) + '">'
                                '<input type="hidden" name="action_id" value="DEMO-STAGE-OBS-'
                                + secrets.token_hex(10).upper() + '">'
                                '<input type="hidden" name="case_version" value="'
                                + str(current["case_version"]) + '">'
                                '<input type="hidden" name="input_revision" value="'
                                + str(current["input_revision"]) + '">'
                                '<input type="hidden" name="input_snapshot_digest" value="'
                                + escape(current["input_snapshot_digest"], quote=True) + '">'
                                '<input type="hidden" name="plan_digest" value="'
                                + escape(current["plan_digest"], quote=True) + '">'
                                '<input type="hidden" name="stage_ref" value="'
                                + stage_ref + '">'
                                '<input type="hidden" name="requirements_digest" value="'
                                + requirements + '">'
                                '<input type="hidden" name="observation_revision" value="'
                                + str(result["current_revision"]) + '">'
                                '<h3>مرحله ' + str(index) + '</h3>'
                                '<p>شناسه مرحله: ' + stage_ref + '</p>'
                                + artifact_control
                                + '<button type="submit">ثبت رسید مشاهده</button>'
                                '</form>'
                            )
                            forms.append(form)
                    history = ''.join(
                        '<li>مرحله ' + escape(item["stage_ref"])
                        + ' · ' + ('رسید جاری' if item["current"]
                                   else 'رسید قدیمی') + ' · نسخه '
                        + str(item["revision"])
                        + (' · رسید مشاهده شد (بدون داوری)'
                           if item["receipt_inspected"] else '')
                        + (' · <a href="/api/v1/domestic/household-intake/my-drafts/'
                           + quote(ref) + '/stage-observations/artifacts/'
                           + quote(item["stage_ref"]) + '/'
                           + escape(item["observation_artifact_digest"], quote=True)
                           + '">دریافت فایل</a>'
                           if household_stage_artifact_store is not None else
                           ' · مرجع ' + escape(item["observation_artifact_digest"]))
                        + '</li>'
                        for item in result["observations"]
                    )
                    body = (
                        '<article class="panel"><h2>ثبت مشاهده مرحله‌ای</h2>'
                        '<p>فقط مرجع رمزنگاری‌شدهٔ مشاهده ثبت می‌شود. '
                        'ثبت رسید به معنی تکمیل مرحله، ارزیابی علمی یا تأیید متخصص نیست.</p>'
                        + ('<p role="status">مرجع جاری طرح در دسترس نیست؛ '
                           'ثبت مشاهده تا دریافت نسخه جاری غیرفعال است.</p>'
                           if not current else
                           '<p>طرح و الزامات مشاهده از مرجع جاری دریافت شده‌اند؛ '
                           'هیچ معیار کشاورزی در این فرم ساخته نمی‌شود.</p>'
                           + '<h3>وضعیت گزارش هر مرحله</h3><ul>'
                           + stage_progress_html + '</ul>')
                        + ''.join(forms)
                        + ('<ol>' + history + '</ol>' if history else
                           '<p>رسیدی ثبت نشده است.</p>')
                        + '<p>با اصلاح پرونده یا تغییر طرح، رسیدهای قبلی حفظ می‌شوند '
                        'و به‌عنوان رسید جاری نمایش داده نخواهند شد.</p>'
                        + '<p><a href="/my-drafts/' + quote(ref)
                        + '/cultivation-inputs">بازگشت به اطلاعات پرونده</a></p>'
                        '</article>'
                    )
                    return page("روناس — مشاهده مرحله‌ای پرونده",
                                body, logged_in=True, local_test_form=True,
                                stage_upload_script=household_stage_artifact_store is not None)

                @router.post("/my-drafts/{ref}/stage-observations")
                async def household_stage_observation_submit(
                    ref: str, request: Request,
                    sid: str | None = Cookie(default=None, alias=cookie_name),
                ) -> RedirectResponse:
                    principal, form = await checked_browser_form(
                        request, sid,
                        fields=frozenset({
                            "csrf", "action_id", "case_version", "input_revision",
                            "input_snapshot_digest", "plan_digest", "stage_ref",
                            "requirements_digest", "observation_revision",
                            "artifact_digest",
                        }),
                        max_bytes=4096, max_fields=10, max_value_length=128,
                    )
                    try:
                        permitted = household_profile_access_authority(
                            principal, ref, household_profile_schema.schema_ref,
                        )
                    except Exception as exc:
                        raise HTTPException(
                            503, detail="HOUSEHOLD_PROFILE_AUTHORITY_UNAVAILABLE",
                        ) from exc
                    if permitted is not True:
                        raise HTTPException(403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED")
                    try:
                        command = StageObservationCommand(
                            action_id=form["action_id"],
                            expected_case_version=form_version(
                                form["case_version"], zero_allowed=False,
                            ),
                            expected_input_revision=form_version(
                                form["input_revision"], zero_allowed=False,
                            ),
                            expected_input_snapshot_digest=form[
                                "input_snapshot_digest"
                            ],
                            expected_plan_digest=form["plan_digest"],
                            stage_ref=form["stage_ref"],
                            expected_observation_requirements_digest=
                                form["requirements_digest"],
                            observed_at=datetime.now(timezone.utc).isoformat(
                                timespec="seconds",
                            ),
                            observation_artifact_digest=form["artifact_digest"],
                        )
                        if (household_stage_artifact_store is not None
                                and not household_stage_artifact_store.contains(
                                    principal.subject, ref + ":" + command.stage_ref,
                                    command.observation_artifact_digest,
                                )):
                            return JSONResponse(
                                status_code=422,
                                content={"detail": "STAGE_ARTIFACT_NOT_UPLOADED"},
                            )
                        saved = household_input_ledger.append_owned_stage_observation(
                            ref, principal, command,
                            expected_observation_revision=form_version(
                                form["observation_revision"],
                            ),
                            context_authority=household_stage_context_authority,
                        )
                    except StageObservationConflict as exc:
                        raise HTTPException(
                            409, detail="STAGE_OBSERVATION_CONTEXT_CHANGED",
                        ) from exc
                    except StageArtifactStoreError as exc:
                        raise HTTPException(
                            503, detail="STAGE_ARTIFACT_STORE_UNAVAILABLE",
                        ) from exc
                    except (LedgerIntegrityError, sqlite3.Error) as exc:
                        raise HTTPException(
                            503, detail="STAGE_OBSERVATIONS_UNAVAILABLE",
                        ) from exc
                    except ValueError as exc:
                        raise HTTPException(422, detail="INVALID_STAGE_OBSERVATION") from exc
                    if saved is None:
                        raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                    return RedirectResponse(
                        "/my-drafts/" + quote(ref) + "/stage-observations",
                        status_code=303,
                    )

            @router.post("/my-drafts/{ref}/cultivation-inputs")
            async def household_cultivation_inputs_submit(
                ref: str, request: Request,
                sid: str | None = Cookie(default=None, alias=cookie_name),
            ) -> RedirectResponse:
                profile_fields = frozenset(
                    {"csrf", "action_id", "case_version", "profile_revision"}
                    | {field.key for field in household_profile_schema.fields}
                )
                principal, form = await checked_browser_form(
                    request, sid, fields=profile_fields,
                    max_bytes=8192, max_fields=10,
                    max_value_length=300,
                )
                try:
                    permitted = household_profile_access_authority(
                        principal, ref, household_profile_schema.schema_ref,
                    )
                except Exception as exc:
                    raise HTTPException(
                        503, detail="HOUSEHOLD_PROFILE_AUTHORITY_UNAVAILABLE",
                    ) from exc
                if permitted is not True:
                    raise HTTPException(403, detail="HOUSEHOLD_PROFILE_ACCESS_DENIED")
                values = {
                    field.key: form[field.key]
                    for field in household_profile_schema.fields
                }
                try:
                    saved = household_input_ledger.append_owned_profile(
                        ref, principal,
                        action_id=form["action_id"],
                        expected_case_version=form_version(
                            form["case_version"], zero_allowed=False,
                        ),
                        expected_revision=form_version(form["profile_revision"]),
                        values=values,
                    )
                except InputRevisionConflict as exc:
                    raise HTTPException(
                        409, detail="HOUSEHOLD_PROFILE_VERSION_CONFLICT",
                    ) from exc
                except (LedgerIntegrityError, sqlite3.Error) as exc:
                    raise HTTPException(
                        503, detail="HOUSEHOLD_PROFILE_UNAVAILABLE",
                    ) from exc
                except ValueError as exc:
                    raise HTTPException(422, detail="INVALID_HOUSEHOLD_PROFILE") from exc
                if saved is None:
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                return RedirectResponse(
                    "/my-drafts/" + quote(ref) + "/cultivation-inputs",
                    status_code=303,
                )

        @router.post("/my-drafts/{ref}/input-revisions/demo-correction")
        async def household_demo_correction(
            ref: str, request: Request,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> RedirectResponse:
            principal, form = await checked_browser_form(
                request, sid,
                fields=frozenset({
                    "csrf", "action_id", "case_version", "input_revision", "scenario",
                }),
            )
            scenario = form["scenario"]
            if scenario not in ("DEMO-MANIFEST-ALPHA", "DEMO-MANIFEST-BETA"):
                raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM")
            case_version = form_version(form["case_version"], zero_allowed=False)
            observed = form_version(form["input_revision"])
            # Private opaque sample digest: no physical cultivation/user data.
            digest = hashlib.sha256(
                ("ronas.local-test.manifest.v1:" + ref + ":"
                 + str(observed) + ":" + scenario).encode("ascii")
            ).hexdigest() if _synthetic_ref(ref) else ""
            try:
                updated = household_input_ledger.append_owned_input_manifest(
                    ref, principal,
                    action_id=form["action_id"],
                    expected_case_version=case_version,
                    expected_input_revision=observed,
                    synthetic_manifest_digest=digest,
                )
            except InputRevisionConflict as exc:
                raise HTTPException(
                    409, detail="SYNTHETIC_INPUT_VERSION_CONFLICT",
                ) from exc
            except LedgerIntegrityError as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_INPUT_HISTORY_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM") from exc
            if updated is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return RedirectResponse(
                "/my-drafts/" + quote(ref) + "/input-revisions",
                status_code=303,
            )


    if household_surplus_draft_ledger is not None:
        @router.get("/my-drafts/{ref}/surplus-offers/new")
        def household_start_surplus_draft(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> RedirectResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            identity = Principal(session.subject, session.roles)
            if "household" not in identity.roles or not _synthetic_ref(ref):
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            try:
                permitted = household_profile_access_authority(
                    identity, ref, household_surplus_draft_ledger.schema.schema_ref,
                )
            except Exception as exc:
                raise HTTPException(
                    503, detail="SURPLUS_DRAFT_AUTHORITY_UNAVAILABLE",
                ) from exc
            if permitted is not True:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            try:
                existing_refs = {
                    record.offer_ref
                    for record in household_surplus_draft_ledger.list_owned(identity, ref)
                }
            except LookupError:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND") from None
            except (RuntimeError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SURPLUS_DRAFT_UNAVAILABLE",
                ) from exc
            offer_ref = ""
            for _ in range(8):
                candidate = "DEMO-OFFER-" + secrets.token_hex(16).upper()
                if candidate not in existing_refs:
                    offer_ref = candidate
                    break
            if not offer_ref:
                raise HTTPException(503, detail="SURPLUS_DRAFT_ID_UNAVAILABLE")
            return RedirectResponse(
                "/my-drafts/" + quote(ref) + "/surplus-offers?offer_ref="
                + quote(offer_ref), status_code=303,
            )

        @router.get(
            "/my-drafts/{ref}/surplus-offers/{offer_ref}/revisions"
        )
        def household_surplus_revision_history(
            ref: str,
            offer_ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            identity = Principal(session.subject, session.roles)
            if ("household" not in identity.roles or not _synthetic_ref(ref)
                    or not _synthetic_ref(offer_ref)):
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            try:
                revisions = household_surplus_draft_ledger.history_owned(
                    identity, ref, offer_ref,
                )
            except LookupError:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND") from None
            except (RuntimeError, sqlite3.Error) as exc:
                raise HTTPException(
                    503, detail="SURPLUS_DRAFT_UNAVAILABLE",
                ) from exc
            entries = []
            active_digest = household_surplus_draft_ledger.schema.digest
            for index, record in enumerate(revisions):
                schema_matches = record.schema_digest == active_digest
                previous = revisions[index - 1] if index else None
                diff_matches = (
                    schema_matches
                    and (previous is None or previous.schema_digest == active_digest)
                )
                if schema_matches:
                    values = "<dl>" + "".join(
                        "<dt>" + escape(key) + "</dt><dd>"
                        + escape(value) + "</dd>"
                        for key, value in sorted(record.values.items())
                    ) + "</dl>"
                    state = "نسخهٔ طرح‌وارهٔ جاری"
                    if diff_matches:
                        before = {} if previous is None else previous.values
                        changes = [
                            (key, before.get(key), record.values.get(key))
                            for key in sorted(set(before) | set(record.values))
                            if before.get(key) != record.values.get(key)
                        ]
                        if changes:
                            diff = "<ul>" + "".join(
                                "<li><strong>" + escape(key) + "</strong>: "
                                + ("بدون مقدار" if old is None else escape(old))
                                + " ← "
                                + ("حذف‌شده" if new is None else escape(new))
                                + "</li>"
                                for key, old, new in changes
                            ) + "</ul>"
                        else:
                            diff = "<p>در این نسخه تغییری نسبت به نسخهٔ قبل ثبت نشده است.</p>"
                        diff_block = (
                            '<section aria-label="تفاوت با نسخهٔ قبل"><h4>'
                            'تفاوت با نسخهٔ قبل</h4>' + diff + '</section>'
                        )
                    else:
                        diff_block = (
                            '<p>طرح‌وارهٔ نسخهٔ قبل متفاوت است؛ تفاوت مقادیر '
                            'نمایش داده نمی‌شود.</p>'
                        )
                else:
                    values = "<p>طرح‌واره تغییر کرده؛ مقادیر این نسخه نمایش داده نمی‌شود.</p>"
                    state = "نیازمند بازبینی در طرح‌وارهٔ جاری"
                    diff_block = (
                        '<p>طرح‌واره تغییر کرده؛ تفاوت مقادیر قابل مقایسه نیست.</p>'
                    )
                entries.append(
                    '<section><h3>نسخه ' + str(record.revision)
                    + ' · طرح‌واره ' + str(record.schema_version) + '</h3>'
                    + '<p>' + state + '</p>' + values + diff_block + '</section>'
                )
            body = (
                '<article class="panel"><h2>تاریخچهٔ پیش‌نویس مازاد</h2>'
                '<p>نسخه‌ها فقط‌خواندنی‌اند و تغییر یا حذف نمی‌شوند.</p>'
                + ''.join(entries)
                + '<p><a href="/my-drafts/' + quote(ref)
                + '/surplus-offers?offer_ref=' + quote(offer_ref)
                + '">بازگشت به ویرایش</a></p>'
                + '<p><a href="/my-drafts/' + quote(ref)
                + '/surplus-offers">بازگشت به فهرست</a></p></article>'
            )
            return page("روناس — تاریخچهٔ پیش‌نویس مازاد", body,
                        logged_in=True)

        @router.get("/my-drafts/{ref}/surplus-offers")
        def household_surplus_draft_page(
            ref: str,
            offer_ref: str | None = None,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            identity = Principal(session.subject, session.roles)
            if ("household" not in identity.roles
                    or not _synthetic_ref(ref)
                    or (offer_ref is not None and not _synthetic_ref(offer_ref))):
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            try:
                permitted = household_profile_access_authority(
                    identity, ref, household_surplus_draft_ledger.schema.schema_ref,
                )
            except Exception as exc:
                raise HTTPException(
                    503, detail="SURPLUS_DRAFT_AUTHORITY_UNAVAILABLE",
                ) from exc
            if permitted is not True:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            if offer_ref is None:
                try:
                    records = household_surplus_draft_ledger.list_owned(identity, ref)
                except LookupError:
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND") from None
                except (RuntimeError, sqlite3.Error) as exc:
                    raise HTTPException(503, detail="SURPLUS_DRAFT_UNAVAILABLE") from exc
                items = []
                for record in records:
                    state = (
                        "طرح‌واره تغییر کرده؛ بازبینی لازم است"
                        if record.schema_digest != household_surplus_draft_ledger.schema.digest
                        else "نسخه " + str(record.revision) + " · خصوصی و منتشرنشده"
                    )
                    href = ("/my-drafts/" + quote(ref)
                            + "/surplus-offers?offer_ref=" + quote(record.offer_ref))
                    history_href = (
                        "/my-drafts/" + quote(ref) + "/surplus-offers/"
                        + quote(record.offer_ref) + "/revisions"
                    )
                    items.append(
                        '<li><a href="' + escape(href, quote=True) + '">'
                        + escape(record.offer_ref) + '</a><span>'
                        + escape(state) + '</span><a href="'
                        + escape(history_href, quote=True)
                        + '">تاریخچه نسخه‌ها</a></li>'
                    )
                body = (
                    '<article class="panel"><h2>پیش‌نویس‌های مازاد من</h2>'
                    '<p>فهرست فقط شناسه و وضعیت نسخه را نشان می‌دهد و مقدار فرم‌ها را افشا نمی‌کند.</p>'
                    + ('<ul>' + ''.join(items) + '</ul>' if items else
                       '<p>هنوز پیش‌نویسی ثبت نشده است.</p>')
                    + '<p><a class="button" href="/my-drafts/' + quote(ref)
                    + '/surplus-offers/new">شروع پیش‌نویس مازاد جدید</a></p>'
                    '<p><a href="/my-drafts/' + quote(ref)
                    + '/cultivation-inputs">بازگشت به پرونده</a></p></article>'
                )
                return page("روناس — پیش‌نویس‌های مازاد", body,
                            logged_in=True, local_test_form=True)
            if not _synthetic_ref(offer_ref):
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            current = None
            try:
                current = household_surplus_draft_ledger.read_owned(
                    identity, ref, offer_ref,
                )
            except LookupError:
                pass
            except RuntimeError as exc:
                raise HTTPException(
                    503, detail="SURPLUS_DRAFT_AUTHORITY_UNAVAILABLE",
                ) from exc
            except sqlite3.Error as exc:
                raise HTTPException(503, detail="SURPLUS_DRAFT_UNAVAILABLE") from exc
            schema_matches = (
                current is not None
                and current.schema_digest == household_surplus_draft_ledger.schema.digest
            )
            values = current.values if schema_matches else {}
            controls = []
            for field in household_surplus_draft_ledger.schema.fields:
                key = escape(field.key, quote=True)
                label = escape(field.label)
                value = values.get(field.key, "")
                safe_value = escape(value, quote=True)
                required = " required" if field.required else ""
                if field.kind == "choice":
                    options = ['<option value="">انتخاب کنید</option>']
                    options.extend(
                        '<option value="' + escape(choice, quote=True) + '"'
                        + (" selected" if choice == value else "") + ">"
                        + escape(choice) + "</option>"
                        for choice in field.choices
                    )
                    control = '<select id="' + key + '" name="' + key + '"' + required + '>' + ''.join(options) + '</select>'
                elif field.kind == "text":
                    control = '<textarea id="' + key + '" name="' + key + '" maxlength="' + str(field.max_length) + '"' + required + '>' + escape(value) + '</textarea>'
                else:
                    control = '<input id="' + key + '" name="' + key + '" type="' + field.kind + '" maxlength="' + str(field.max_length) + '" value="' + safe_value + '"' + required + '>'
                controls.append('<label for="' + key + '">' + label + '</label>' + control)
            expected_revision = 0 if current is None else current.revision
            state = (
                "پیش‌نویس جدید و خصوصی" if current is None else
                "نسخه " + str(current.revision) + " · خصوصی و منتشرنشده"
                if schema_matches else
                "نسخه " + str(current.revision)
                + " · طرح‌واره تغییر کرده؛ مقادیر نسخه قبلی نمایش داده نمی‌شود"
            )
            body = (
                '<article class="panel"><h2>پیش‌نویس مازاد خانوار</h2>'
                '<p>' + state + '</p>'
                '<p>فقط فیلدهای تعریف‌شده در طرح‌وارهٔ جاری دریافت می‌شوند؛ '
                'این پیش‌نویس برای خریداران قابل مشاهده نیست.</p>'
                '<form method="post" action="/my-drafts/' + quote(ref)
                + '/surplus-offers"><input type="hidden" name="csrf" value="'
                + escape(session.csrf, quote=True) + '">'
                '<input type="hidden" name="offer_ref" value="'
                + escape(offer_ref, quote=True) + '">'
                '<input type="hidden" name="action_id" value="DEMO-OFFER-UI-'
                + secrets.token_hex(10).upper() + '">'
                '<input type="hidden" name="expected_revision" value="'
                + str(expected_revision) + '">'
                + ''.join(controls)
                + '<button type="submit">ذخیره نسخه خصوصی</button></form>'
                '<p>ثبت پیش‌نویس به‌معنی تأیید کیفیت، عرضه، قیمت یا معامله نیست.</p>'
                '<p><a href="/my-drafts/' + quote(ref)
                + '/cultivation-inputs">بازگشت به پرونده</a></p>'
                + ('<p><a href="/my-drafts/' + quote(ref)
                   + '/surplus-offers/' + quote(offer_ref)
                   + '/revisions">مشاهده تاریخچه نسخه‌ها</a></p>'
                   if current is not None else
                   '<p><a href="/my-drafts/' + quote(ref)
                   + '/surplus-offers">انصراف و دور انداختن فرم ذخیره‌نشده</a></p>')
                + '</article>'
            )
            return page("روناس — پیش‌نویس مازاد خانوار", body,
                        logged_in=True, local_test_form=True)

        @router.post("/my-drafts/{ref}/surplus-offers")
        async def household_surplus_draft_submit(
            ref: str, request: Request,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> RedirectResponse:
            fields = frozenset(
                {"csrf", "offer_ref", "action_id", "expected_revision"}
                | {field.key for field in household_surplus_draft_ledger.schema.fields}
            )
            principal, form = await checked_browser_form(
                request, sid, fields=fields, max_bytes=8192, max_fields=10,
                max_value_length=300, value_encoding="utf-8",
            )
            if not _synthetic_ref(ref) or not _synthetic_ref(form["offer_ref"]):
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            try:
                household_surplus_draft_ledger.save(
                    principal, ref, form["offer_ref"],
                    action_id=form["action_id"],
                    expected_revision=form_version(form["expected_revision"]),
                    values={
                        field.key: form[field.key]
                        for field in household_surplus_draft_ledger.schema.fields
                    },
                )
            except SurplusDraftConflict as exc:
                raise HTTPException(
                    409, detail="SURPLUS_DRAFT_VERSION_CONFLICT",
                ) from exc
            except LookupError as exc:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND") from exc
            except RuntimeError as exc:
                raise HTTPException(
                    503, detail="SURPLUS_DRAFT_AUTHORITY_UNAVAILABLE",
                ) from exc
            except sqlite3.Error as exc:
                raise HTTPException(503, detail="SURPLUS_DRAFT_UNAVAILABLE") from exc
            except ValueError as exc:
                raise HTTPException(422, detail="INVALID_SURPLUS_DRAFT") from exc
            return RedirectResponse(
                "/my-drafts/" + quote(ref) + "/surplus-offers",
                status_code=303,
            )

    if household_surplus_publication_authority is not None:
        @router.get("/my-drafts/{ref}/surplus-publication-readiness")
        def household_surplus_readiness_page(
            ref: str,
            offer_ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            identity = Principal(session.subject, session.roles)
            try:
                result = publication_readiness_snapshot(
                    household_surplus_publication_authority,
                    identity, ref, offer_ref, household_surplus_draft_ledger,
                )
            except HTTPException as exc:
                if exc.status_code == 404:
                    return page(
                        "روناس — آمادگی پیشنهاد مازاد",
                        '<p>پیشنهاد در دسترس نیست.</p>'
                        '<p><a href="/my-drafts/' + quote(ref) + '/surplus-offers">بازگشت به فهرست پیشنهادها</a></p>',
                        logged_in=True, code=404,
                    )
                return page(
                    "روناس — آمادگی پیشنهاد مازاد",
                    '<p role="status">وضعیت آمادگی اکنون قابل دریافت نیست؛ بعداً دوباره تلاش کنید.</p>'
                    '<p><a href="/my-drafts/' + quote(ref) + '/surplus-offers">بازگشت به فهرست پیشنهادها</a></p>',
                    logged_in=True, code=503,
                )
            blocker_labels = {
                "CURRENT_OFFER_UNAVAILABLE": "نسخه جاری پیشنهاد در دسترس نیست",
                "OFFER_SCHEMA_CHANGED": "ساختار پیشنهاد تغییر کرده و بازبینی لازم است",
                "OFFER_VERSION_CHANGED": "نسخه پیشنهاد تغییر کرده است",
                "PRODUCER_APPROVAL_REQUIRED": "تأیید تولیدکننده ثبت نشده است",
                "PRODUCER_APPROVAL_STALE": "تأیید تولیدکننده با نسخه جاری هم‌خوان نیست",
                "QUALITY_SAFETY_VERIFICATION_REQUIRED": "بررسی مستقل کیفیت و ایمنی ثبت نشده است",
                "QUALITY_SAFETY_VERIFICATION_STALE": "بررسی کیفیت و ایمنی با نسخه جاری هم‌خوان نیست",
                "SELLER_ELIGIBILITY_UNVERIFIED": "وضعیت صلاحیت فروشنده احراز نشده است",
                "HOUSEHOLD_PERMISSION_INACTIVE": "مجوز خانوار فعال نیست",
                "MARKETPLACE_GATE_CLOSED": "درگاه فنی بازارگاه باز نیست",
            }
            blockers = result.get("blockers")
            if (not isinstance(blockers, list)
                    or any(code not in blocker_labels for code in blockers)
                    or result.get("published") is not False
                    or result.get("real_data") is not False):
                return page(
                    "روناس — آمادگی پیشنهاد مازاد",
                    '<p role="status">وضعیت آمادگی قابل نمایش نیست.</p>',
                    logged_in=True, code=503,
                )
            state = (
                "الزامات فنیِ تعریف‌شده برای این نسخه برقرار است"
                if result.get("can_publish") is True
                and result.get("state") == "PUBLICATION_AUTHORIZED"
                else "پیشنهاد هنوز در وضعیت پیش‌نویس غیرعمومی است"
            )
            items = ''.join(
                '<li>' + blocker_labels[code] + '</li>' for code in blockers
            ) or '<li>مانعی در کنترل‌های فنی ثبت نشده است</li>'
            body = (
                '<article class="panel"><h2>آمادگی فنی پیشنهاد مازاد</h2>'
                '<p>' + state + '</p>'
                '<p>این نتیجه فقط بررسی فنیِ نسخه جاری است؛ به‌معنای انتشار، '
                'نمایش به خریدار، مجوز فروش، تأیید علمی کیفیت یا اقدام مالی نیست.</p>'
                '<p>وضعیت انتشار: منتشر نشده</p>'
                '<h3>موارد نیازمند توجه</h3><ul>' + items + '</ul>'
                '<p><a href="/my-drafts/' + quote(ref)
                + '/surplus-offers">بازگشت به فهرست پیشنهادها</a></p></article>'
            )
            return page("روناس — آمادگی پیشنهاد مازاد", body, logged_in=True)

    if isinstance(household_input_ledger, SqliteSyntheticExpertQuestionLedger):
        @router.get("/my-drafts/{ref}/question-responses")
        def household_question_response_history(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            try:
                notes = household_input_ledger.read_owned_question_responses(
                    ref, Principal(session.subject, session.roles),
                )
            except LedgerIntegrityError as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_QUESTION_RESPONSE_UNAVAILABLE",
                ) from exc
            if notes is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            if (notes["engine"] != "DOMESTIC"
                    or notes["purpose_consent_verified"] is not False
                    or notes["expert_review_recorded"] is not False
                    or notes["plan_accepted"] is not False
                    or notes["real_data"] is not False):
                raise HTTPException(
                    503, detail="SYNTHETIC_QUESTION_RESPONSE_UNAVAILABLE",
                )
            # Only the latest question on the CURRENT owner's input
            # revision may be answered. Historical lines remain visible.
            current_items = [
                q for q in notes["questions"]
                if q["is_current_input_version"]
            ]
            active_question = (
                max(current_items, key=lambda item: item["question_revision"])
                if current_items else None
            )
            reply_form = ""
            if (active_question is not None
                    and active_question["response_state"] == "MISSING_RESPONSE"
                    and active_question["bound_input_revision"] > 0):
                reply_form = (
                    '<section id="owner-demo-reply" aria-label="پاسخ ساختاری آزمایشی خانوار">'
                    '<h3>ثبت مرجع پاسخ DEMO</h3>'
                    '<p>پاسخ واقعی یا اطلاعات شخصی دریافت نمی‌شود. '
                    'این عمل تأیید متخصص نیست.</p>'
                    '<form method="post" action="/my-drafts/'
                    + quote(ref) + '/question-responses/demo-reply">'
                    '<input type="hidden" name="csrf" value="'
                    + escape(session.csrf, quote=True) + '">'
                    '<input type="hidden" name="action_id" value="DEMO-UI-R-'
                    + secrets.token_hex(10).upper() + '">'
                    '<input type="hidden" name="case_version" value="'
                    + str(notes["case_version"]) + '">'
                    '<input type="hidden" name="input_revision" value="'
                    + str(active_question["bound_input_revision"]) + '">'
                    '<input type="hidden" name="question_revision" value="'
                    + str(active_question["question_revision"]) + '">'
                    '<label for="owner-demo-answer">پاسخ مرجعی نمونه</label>'
                    '<select id="owner-demo-answer" name="scenario">'
                    + sample_choice_options(prefix="DEMO-REPLY-")
                    + '</select><button type="submit">ثبت پاسخ DEMO</button>'
                    '</form></section>'
                )
            rows = ''.join(
                '<li>پرسش آزمایشی ' + str(q["question_revision"])
                + ' · نسخه ورودی ' + str(q["bound_input_revision"])
                + ' · وضعیت ' + escape(q["response_state"])
                + (' · ارجاع پاسخ ' + escape(q["response_ref"])
                   if q["response_ref"] else '')
                + (' · ارجاع شاهد ' + escape(q["evidence_ref"])
                   if q["evidence_ref"] else '')
                + (' · متصل به رسید مرحله ' + escape(q["stage_ref"])
                   + ' · نسخه رسید ' + str(q["stage_observation_revision"])
                   if q.get("stage_ref") else '')
                + (' · نسخه فعلی' if q["is_current_input_version"]
                   else ' · نسخه تاریخی')
                + '</li>'
                for q in notes["questions"]
            )
            body = (
                '<article class="panel"><h2>تاریخچه پاسخ‌های ساختاری خانوار '
                '(فقط DEMO)</h2>'
                '<p>پرونده ' + escape(notes["case_ref"])
                + ' · نسخه ' + str(notes["case_version"]) + '</p>'
                + ('<ul>' + rows + '</ul>' if rows else
                   '<p>هنوز پرسشی درباره ورودی خانوار ثبت نشده است.</p>')
                + '<p>این پاسخ‌ها صرفاً ارجاع مصنوعی هستند؛ '
                'رضایت خانوار، بررسی کفایت داده، تصمیم متخصص یا '
                'برنامه پذیرفته‌شده محسوب نمی‌شوند.</p>'
                '<p>در این صفحه فرم دریافت اطلاعات واقعی یا '
                'فرمان تأیید/رد وجود ندارد.</p>'
                + reply_form
                + '<p><a href="/my-drafts/' + quote(ref)
                + '/input-revisions">بازگشت به تاریخچه نسخه‌ها</a></p>'
                '</article>'
            )
            return page(
                "روناس — پاسخ‌های آزمایشی خانوار",
                body, logged_in=True, local_test_form=True,
            )

        @router.post("/my-drafts/{ref}/question-responses/demo-reply")
        async def household_demo_reply(
            ref: str, request: Request,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> RedirectResponse:
            principal, form = await checked_browser_form(
                request, sid, fields=frozenset({
                    "csrf", "action_id", "case_version", "input_revision",
                    "question_revision", "scenario",
                }),
            )
            if form["scenario"] not in ("DEMO-REPLY-ALPHA", "DEMO-REPLY-BETA"):
                raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM")
            try:
                saved = household_input_ledger.append_owned_question_response(
                    ref, principal,
                    action_id=form["action_id"],
                    track="HOUSEHOLD_INPUT_ADEQUACY",
                    expected_case_version=form_version(
                        form["case_version"], zero_allowed=False,
                    ),
                    expected_input_revision=form_version(
                        form["input_revision"], zero_allowed=False,
                    ),
                    expected_question_revision=form_version(
                        form["question_revision"], zero_allowed=False,
                    ),
                    answer_ref=form["scenario"],
                    evidence_ref="DEMO-OWNER-PENDING-REF",
                )
            except ReviewQuestionConflict as exc:
                raise HTTPException(
                    409, detail="SYNTHETIC_RESPONSE_VERSION_CONFLICT",
                ) from exc
            except LedgerIntegrityError as exc:
                raise HTTPException(
                    503, detail="SYNTHETIC_QUESTION_RESPONSE_UNAVAILABLE",
                ) from exc
            except ValueError as exc:
                raise HTTPException(422, detail="INVALID_LOCAL_TEST_FORM") from exc
            if saved is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            return RedirectResponse(
                "/my-drafts/" + quote(ref) + "/question-responses",
                status_code=303,
            )

    if (technical_review_ledger is not None
            and owned_case_ledger is technical_review_ledger):
        @router.get("/my-drafts/{ref}")
        def household_detail(
            ref: str,
            sid: str | None = Cookie(default=None, alias=cookie_name),
        ) -> HTMLResponse:
            try:
                session = flow.session(sid)
            except InvalidToken:
                raise HTTPException(401, detail="INVALID_SESSION") from None
            principal = Principal(session.subject, session.roles)
            # The owner-specific facade checks exact immutable ownership,
            # review integrity and records the read atomically.
            result = technical_review_ledger.read_owned_domestic_status(
                ref, principal,
            )
            if result is None:
                raise HTTPException(404, detail="DRAFT_NOT_FOUND")
            states = {
                "UNREQUESTED": "درخواستی برای بررسی فنی ثبت نشده است.",
                "EVIDENCE_REVIEW_REQUESTED": "درخواست بررسی شواهد ثبت شده است.",
                "HUMAN_RESPONSE_RECORDED":
                    "مرجع پاسخ انسانی ثبت شده؛ این وضعیت تأیید پرونده نیست.",
            }
            state = states[result["technical_review_state"]]
            journey_html = ""
            if isinstance(household_input_ledger,
                          SqliteSyntheticHouseholdInputLedger):
                input_info = household_input_ledger.read_owned_input_revisions(
                    ref, principal,
                )
                question_info = (
                    household_input_ledger.read_owned_question_responses(
                        ref, principal,
                    )
                    if isinstance(household_input_ledger,
                                  SqliteSyntheticExpertQuestionLedger)
                    else None
                )
                if (input_info is None or
                        (isinstance(household_input_ledger,
                                    SqliteSyntheticExpertQuestionLedger)
                         and question_info is None)):
                    raise HTTPException(404, detail="DRAFT_NOT_FOUND")
                try:
                    next_step = owner_next_action(input_info, question_info)
                except JourneyEvidenceMismatch as exc:
                    raise HTTPException(
                        503, detail="SYNTHETIC_JOURNEY_UNAVAILABLE",
                    ) from exc
                next_page = (
                    "/my-drafts/" + quote(ref) +
                    ("/question-responses#owner-demo-reply"
                     if next_step == "RESPOND_TO_EXPERT_QUESTION_DEMO" else
                     "/question-responses"
                     if next_step == "RESPONSE_RECORDED_WAIT_FOR_EXPERT_DEMO" else
                     "/input-revisions#domestic-demo-correction")
                )
                guidance = {
                    "RESPOND_TO_EXPERT_QUESTION_DEMO":
                        "پرسش ساختاری جاری منتظر پاسخ مرجعی نمونه است",
                    "RESPONSE_RECORDED_WAIT_FOR_EXPERT_DEMO":
                        "پاسخ ثبت شده؛ بررسی و تأیید تخصصی هنوز انجام نشده است",
                    "PREPARE_OR_REVISE_INPUT_DEMO":
                        "نسخه اطلاعات آزمایشی را بررسی یا اصلاح کنید",
                }[next_step]
                journey_html = (
                    '<nav class="journey" aria-label="اقدام بعدی پرونده خانوار">'
                    '<h3>اقدام بعدی در پرونده</h3><p>'
                    + escape(guidance) + '</p><p><a href="'
                    + escape(next_page, quote=True) +
                    '">رفتن به مرحله مرتبط</a></p>'
                    '<p>این راهنما پیشنهاد ناوبری است؛ '
                    'رضایت، طرح کشت یا تأیید علمی نیست.</p></nav>'
                )
            body = (
                '<article class="panel"><h2>پرونده ساختگی '
                + escape(result["ref"]) + '</h2>'
                '<p>نسخه پرونده: ' + str(result["version"]) + '</p>'
                '<p>وضعیت پرونده: DRAFT_ONLY</p>'
                '<p>پیگیری فنی: ' + escape(state) + '</p>'
                + journey_html
                + readonly_domestic_preparation_html(
                    result["cultivation_preparation"]
                )
                + '<p>هیچ تصمیم تجاری یا عملیاتی ثبت نشده است.</p>'
                '<p><a href="/my-drafts/' +
                escape(result["ref"], quote=True) +
                '/versions">مشاهده تاریخچه نسخه‌ها</a></p>'
                + ('<p><a href="/my-drafts/'
                   + quote(ref) + '/input-revisions">'
                   'تاریخچه آزمایشی اصلاح اطلاعات خانوار</a></p>'
                   if household_input_ledger is not None else '')
                + ('<p><a href="/my-drafts/' + quote(ref)
                   + '/cultivation-inputs">اطلاعات ساختاریافته پرونده کشت</a></p>'
                   if (household_profile_schema is not None
                       and household_profile_access_authority is not None) else '')
                + ('<p><a href="/my-drafts/' + quote(ref)
                   + '/progress-notes">یادداشت پیشرفت ساختگی (DEMO)</a></p>'
                   if household_input_ledger is not None else '')
                + ('<form method="get" action="/my-drafts/' + quote(ref)
                   + '/surplus-publication-readiness">'
                   '<label for="surplus-offer-ref">شناسه پیشنهاد مازاد (DEMO)</label>'
                   '<input id="surplus-offer-ref" name="offer_ref" required '
                   'pattern="DEMO-[A-Za-z0-9._:-]{1,96}" maxlength="101">'
                   '<button type="submit">بررسی آمادگی فنی</button></form>'
                   if household_surplus_publication_authority is not None else '')
                + ('<p><a href="/my-drafts/' + quote(ref)
                   + '/question-responses">'
                   'پرسش و پاسخ مرجعی خانوار (فقط DEMO)</a></p>'
                   if isinstance(household_input_ledger,
                                 SqliteSyntheticExpertQuestionLedger) else '')
                + '<p><a href="/">بازگشت به پرونده‌های من</a></p>'
                '</article>'
            )
            return page("روناس — وضعیت پرونده من (آزمایشی)",
                        body, logged_in=True)


    def technical_worklist(engine: str, principal: Principal,
                           after_ref: str | None) -> str:
        if technical_review_ledger is None:
            return ""
        try:
            result = technical_review_ledger.list_technical_review_worklist(
                engine, principal, after_ref=after_ref, limit=20
            )
        except LedgerIntegrityError:
            # The application owns the fail-closed 503 for corrupted audit.
            raise
        except ValueError as exc:
            raise HTTPException(422, detail="INVALID_WORKLIST_QUERY") from exc
        links = []
        for item in result["items"]:
            ref = escape(item["ref"])
            url = ("/api/v1/admin/domestic/household-intake/drafts/"
                   if engine == "DOMESTIC" else
                   "/api/v1/admin/export/research/drafts/")
            links.append(
                '<li><a href="' + url + ref + '/technical-review">'
                + ref + '</a> — ' + escape(item["technical_review_state"])
                + ' · DRAFT_ONLY'
                + (' · <a href="/admin/export/research/drafts/'
                   + quote(item["ref"]) + '">فضای پژوهش صادرات</a>'
                   if engine == "EXPORT" else '')
                + '</li>'
            )
        body = ('<ul>' + ''.join(links) + '</ul>' if links
                else '<p>پرونده ساختگی تخصیص‌یافته‌ای برای این بخش وجود ندارد.</p>')
        if result["next_cursor"]:
            parameter = ("domestic_after_ref" if engine == "DOMESTIC"
                         else "export_after_ref")
            body += ('<a href="/admin?' + parameter + '='
                     + quote(result["next_cursor"]) + '">پرونده‌های بعدی</a>')
        return ('<section class="section"><h3>فهرست فنی بررسی شواهد'
                ' (فقط نمونه آزمایشی)</h3>' + body + '</section>')

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
