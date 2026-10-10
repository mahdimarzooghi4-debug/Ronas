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
from .human_review_sqlite import SqliteSyntheticHumanReviewLedger
from .grant_ledger_sqlite import LedgerIntegrityError, SqliteSyntheticGrantLedger
from .oidc_browser import BrowserOIDC
from .shared_workspaces import USER_ROLES, visible_user_workspaces
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


def build_authenticated_ui_router(
    flow: BrowserOIDC,
    technical_review_ledger: SqliteSyntheticHumanReviewLedger | None = None,
    owned_case_ledger: SqliteSyntheticGrantLedger | None = None,
) -> APIRouter:
    # Only the opt-in same-instance ledger injected by create_app may
    # provide the synthetic worklist. Never trust a client-side role list.
    if (technical_review_ledger is not None
            and not isinstance(technical_review_ledger, SqliteSyntheticHumanReviewLedger)):
        raise ValueError("technical review worklist requires explicit ledger")
    if (owned_case_ledger is not None
            and not isinstance(owned_case_ledger, SqliteSyntheticGrantLedger)):
        raise ValueError("owned household list requires explicit grant ledger")
    router = APIRouter()
    cookie_name = "__Host-ronas_session"

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

    def household_worklist(principal: Principal, after_ref: str | None) -> str:
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
                )
            else:
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
               if progress_enabled else '') + '</li>'
            for item in result["items"]
        ]
        body = ('<ul>' + ''.join(rows) + '</ul>' if rows else
                '<p>پرونده ساختگی متعلق به این حساب وجود ندارد.</p>')
        if result["next_cursor"]:
            body += ('<a href="/?household_after_ref='
                     + quote(result["next_cursor"]) + '">پرونده‌های بعدی</a>')
        return ('<section class="section"><h3>پرونده‌های من'
                ' (فقط نمونه آزمایشی)</h3>' + body + '</section>')

    @router.get("/workspace/{role}")
    def user_role_workspace(
        role: str,
        sid: str | None = Cookie(default=None, alias=cookie_name),
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
        )
        assigned = next((w for w in active if w["role"] == role), None)
        if assigned is None:
            # Unknown and unassigned partner roles are indistinguishable.
            raise HTTPException(404, detail="WORKSPACE_NOT_FOUND")
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

    @router.get("/")
    def public_ui(
        sid: str | None = Cookie(default=None, alias=cookie_name),
        household_after_ref: str | None = None,
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
                    Principal(session.subject, session.roles), household_after_ref,
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
                '<p>رضایت واقعی احراز نشده و طرح کشت به تأیید متخصص '
                'نرسیده است. هیچ تصمیم تجاری یا عملیاتی ثبت نشده است.</p>'
                '<p><a href="/">بازگشت به پرونده‌های من</a></p>'
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
                + ' · DRAFT_ONLY</li>'
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
                    worklist = technical_worklist(
                        "EXPORT", Principal(session.subject, session.roles),
                        export_after_ref,
                    )
            cards.append('<article class="panel"><h2>' + escape(label) + '</h2><p>'
                         + escape(note) + '</p>' + worklist + '</article>')
        return page("مدیریت روناس — پنل واحد با دسترسی مجزا",
                    '<div class="columns">' + ''.join(cards) + '</div>', logged_in=True)

    return router
