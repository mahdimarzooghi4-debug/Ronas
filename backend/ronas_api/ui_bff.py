"""Two authenticated, strictly role-scoped HTML shells for opt-in Keycloak BFF.

The default production entrypoint never mounts these routes. The HTML is
rendered from fixed templates, not client-supplied text or arbitrary files.
No live workflow or personal data exists in this UI foundation.
"""
from html import escape
from urllib.parse import quote
from pathlib import Path

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse

from .auth import InvalidToken, Principal
from .human_review_sqlite import SqliteSyntheticHumanReviewLedger, STATES as TECHNICAL_STATES
from .scoped_drafts import _synthetic_ref
from .grant_ledger_sqlite import LedgerIntegrityError, SqliteSyntheticGrantLedger
from .household_input_ledger_sqlite import SqliteSyntheticHouseholdInputLedger
from .oidc_browser import BrowserOIDC
from .business_gate_evidence import (BUSINESS_SOURCE_SHA, dossier_detail,
                                     visible_dossiers, verify_pinned_business_sources,
                                     BusinessSourceSnapshotError, SOURCE_INTEGRITY_STATE)
from .shared_workspaces import USER_ROLES, visible_user_workspaces
from .agronomy_workspace import SyntheticAgronomyWorkspace
from .export_supplier_workspace import (
    SyntheticSupplierUnavailable, SyntheticSupplierWorkspace,
)
from .domestic_partner_workspace import (
    FIELDS as DOMESTIC_PARTNER_FIELDS, SyntheticDomesticPartnerUnavailable,
    SyntheticDomesticPartnerWorkspace,
)
from .domestic_preparation_preview import (
    REVIEW_STATES, domestic_preparation_preview,
)
from .gate_evidence_handoff_sqlite import SqliteSyntheticGateEvidenceHandoff
from .gate_evidence_authority_enquiry_sqlite import SqliteSyntheticAuthorityEnquiryLedger
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
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const status = await fetch('/api/auth/session', {credentials:'same-origin', cache:'no-store'});
      if (!status.ok) throw Error('NO_ACTIVE_SESSION');
      const data = await status.json();
      const result = await fetch('/api/auth/logout', {
        method:'POST', credentials:'same-origin', cache:'no-store',
        headers:{'X-CSRF-Token':data.csrf}
      });
      if (!result.ok) throw Error('LOGOUT_REJECTED');
      window.location.replace('/');
    } catch {
      button.disabled = false;
      const notice = document.getElementById('logout-message');
      if (notice) notice.textContent = 'خروج تأیید نشد؛ نشست را بسته فرض نکنید.';
    }
  });
});"""

def page(title: str, body: str, *, logged_in: bool, code: int = 200) -> HTMLResponse:
    logout = (
        '<button type="button" id="ronas-logout">خروج امن</button>'
        '<p id="logout-message" role="status" aria-live="polite"></p>'
        if logged_in else '<a class="btn" href="/api/auth/start">ورود با Keycloak</a>'
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
            '<script src="/assets/ronas-auth.js" defer></script></body></html>')
    response = HTMLResponse(html, status_code=code)
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'; object-src 'none'"
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
    gate_handoff_ledger: SqliteSyntheticGateEvidenceHandoff | None = None,
    authority_enquiry_ledger: SqliteSyntheticAuthorityEnquiryLedger | None = None,
    agronomy_workspace: SyntheticAgronomyWorkspace | None = None,
    export_supplier_workspace: SyntheticSupplierWorkspace | None = None,
    domestic_partner_workspace: SyntheticDomesticPartnerWorkspace | None = None,
) -> APIRouter:
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
            body = (
                '<article class="panel"><h2>پیش‌نمای پرونده خانوار (فقط DEMO): '
                + escape(data["ref"]) + '</h2>'
                '<p>نسخه پرونده: ' + str(data["case_version"])
                + ' · وضعیت: DRAFT_ONLY</p>'
                + readonly_domestic_preparation_html(
                    data["cultivation_preparation"]
                )
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
                '<p><a href="/workspace/agronomy_expert">'
                'بازگشت به فضای کار کارشناس کشاورزی</a></p>'
                '</article>'
            )
            return page("روناس — فضای کار کارشناس کشاورزی (آزمایشی)",
                        body, logged_in=True)

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
                '<p><a href="/agronomy/assigned-drafts/' + quote(ref)
                + '">بازگشت به پرونده تخصیص‌یافته</a></p></article>'
            )
            return page(
                "روناس — آماده‌سازی بررسی مستقل برنامه کشت (DEMO)",
                body, logged_in=True,
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
                '<p><a href="/my-drafts/' + quote(ref)
                + '">بازگشت به پرونده من</a></p></article>'
            )
            return page("روناس — تاریخچه اصلاح آزمایشی اطلاعات خانوار",
                        body, logged_in=True)

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
            body = (
                '<article class="panel"><h2>پرونده ساختگی '
                + escape(result["ref"]) + '</h2>'
                '<p>نسخه پرونده: ' + str(result["version"]) + '</p>'
                '<p>وضعیت پرونده: DRAFT_ONLY</p>'
                '<p>پیگیری فنی: ' + escape(state) + '</p>'
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
                '<p>محصول: تعیین نشده · مقصد: تعیین نشده · HS: تعیین نشده</p>'
                '<p>مرجع منبع صرفاً آزمایشی: '
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
                        body, logged_in=True)

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
                        logged_in=False, code=401)
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
            cards.append('<article class="panel"><h2>' + escape(label) + '</h2><p>'
                         + escape(note) + '</p>' + worklist + gate_links
                         + '</article>')
        return page("مدیریت روناس — پنل واحد با دسترسی مجزا",
                    '<div class="columns">' + ''.join(cards) + '</div>', logged_in=True)

    return router
