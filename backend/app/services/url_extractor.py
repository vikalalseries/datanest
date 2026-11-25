"""Safely fetch a public web page and reduce it to text + metadata for the AI.

Security: SSRF-validated, IP-pinned connections, manual redirect handling (each hop re-validated),
size/time limits, content-type allowlist. Pages are only parsed as text; scripts are never executed.
"""
import json
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.utils.security import SafeTarget, UnsafeURL, is_public_ip, validate_url

MAX_BYTES = 2 * 1024 * 1024
TOTAL_TIMEOUT = 12.0
MAX_REDIRECTS = 3
MAX_TEXT_CHARS = 15_000
ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
UA = "Mozilla/5.0 (compatible; DataNestBot/0.1; +personal-use)"

LOGIN_HINTS = ("sign in to", "log in to", "login to view", "join to view", "authwall", "create an account to", "please enable javascript")


class FetchError(Exception):
    """Fetch failed. `code` is machine-readable; message is user-safe."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class PageContent:
    final_url: str
    title: str | None
    description: str | None
    text: str
    json_ld: list[dict] = field(default_factory=list)
    truncated: bool = False


async def _fetch_once(client: httpx.AsyncClient, t: SafeTarget, deadline: float) -> tuple[httpx.Response, bytes]:
    # Connect to the validated IP (prevents DNS rebinding); keep Host/SNI as the real hostname.
    netloc_ip = f"[{t.ip}]" if ":" in t.ip else t.ip
    default_port = 443 if t.scheme == "https" else 80
    netloc = netloc_ip if t.port == default_port else f"{netloc_ip}:{t.port}"
    headers = {"Host": t.host, "User-Agent": UA, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9", "Accept-Language": "en"}
    ext = {"sni_hostname": t.host} if t.scheme == "https" else {}
    async with client.stream("GET", f"{t.scheme}://{netloc}{t.path_qs}", headers=headers, extensions=ext, follow_redirects=False) as resp:
        if resp.status_code in (301, 302, 303, 307, 308):
            return resp, b""
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if resp.status_code < 400 and ctype not in ALLOWED_TYPES:
            raise FetchError("unsupported_content", "That link isn't a web page we can read (for example a file or image). Upload it as a screenshot instead.")
        buf = bytearray()
        truncated = False
        async for chunk in resp.aiter_bytes():
            buf.extend(chunk)
            if len(buf) > MAX_BYTES:
                truncated = True
                del buf[MAX_BYTES:]
                break
            if time.monotonic() > deadline:
                raise FetchError("timeout", "The website took too long to respond.")
        resp.extensions["truncated"] = truncated
        return resp, bytes(buf)


async def fetch_page(url: str) -> PageContent:
    try:
        target = await validate_url(url)
    except UnsafeURL as e:
        raise FetchError("invalid_url", str(e))
    deadline = time.monotonic() + TOTAL_TIMEOUT
    timeout = httpx.Timeout(connect=5, read=8, write=5, pool=5)
    async with httpx.AsyncClient(timeout=timeout, verify=True, trust_env=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                resp, body = await _fetch_once(client, target, deadline)
            except FetchError:
                raise
            except (httpx.TimeoutException,):
                raise FetchError("timeout", "The website took too long to respond.")
            except httpx.HTTPError:
                raise FetchError("fetch_failed", "We couldn't open that website. It may be down or blocking automated access.")
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    raise FetchError("fetch_failed", "The website redirected us somewhere invalid.")
                try:
                    target = await validate_url(urljoin(target.url, loc))  # re-validate every hop
                except UnsafeURL:
                    raise FetchError("unsafe_redirect", "That link redirects to an address we can't open for safety reasons.")
                continue
            break
        else:
            raise FetchError("too_many_redirects", "That link redirects too many times.")

    if resp.status_code in (401, 403, 999) or resp.status_code == 429:
        raise FetchError("needs_manual_text", "That page needs you to sign in or blocks automated access. Open it yourself, copy the text, and paste it into the Text tab.")
    if resp.status_code == 404 or resp.status_code == 410:
        raise FetchError("not_found", "That page doesn't exist (404). Check the link.")
    if resp.status_code >= 400:
        raise FetchError("fetch_failed", f"The website returned an error ({resp.status_code}).")

    encoding = resp.charset_encoding or "utf-8"
    try:
        html = body.decode(encoding, errors="replace")
    except LookupError:
        html = body.decode("utf-8", errors="replace")
    page = parse_html(html, target.url)
    low = page.text.lower()
    thin = len(page.text) < 200 and not page.json_ld
    if thin or (len(page.text) < 600 and any(h in low for h in LOGIN_HINTS) and not page.json_ld):
        raise FetchError(
            "needs_manual_text",
            "We couldn't read the content of that page. It probably requires login or loads its content with JavaScript. "
            "Open it yourself, copy the text, and paste it into the Text tab.",
        )
    page.truncated = bool(resp.extensions.get("truncated"))
    return page


def parse_html(html: str, url: str) -> PageContent:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string.strip() if soup.title and soup.title.string else None)

    def meta(*names: str) -> str | None:
        for n in names:
            tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
        return None

    description = meta("og:description", "description", "twitter:description")
    json_ld: list[dict] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and "@graph" in item and isinstance(item["@graph"], list):
                json_ld.extend(x for x in item["@graph"] if isinstance(x, dict))
            elif isinstance(item, dict):
                json_ld.append(item)
    json_ld = [j for j in json_ld if str(j.get("@type", "")) in ("JobPosting", "Event", "Product", "Organization", "Article", "NewsArticle", "LocalBusiness", "Person", "Course")][:5]
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "form", "iframe", "header"]):
        tag.decompose()
    text = re.sub(r"[ \t\r\f\v]+", " ", soup.get_text("\n"))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return PageContent(final_url=url, title=title, description=description, text=text[:MAX_TEXT_CHARS], json_ld=json_ld)


def page_to_prompt_text(page: PageContent) -> str:
    parts = [f"URL: {page.final_url}"]
    if page.title:
        parts.append(f"Title: {page.title}")
    if page.description:
        parts.append(f"Description: {page.description}")
    if page.json_ld:
        parts.append("Structured data (JSON-LD):\n" + json.dumps(page.json_ld, ensure_ascii=False)[:6000])
    parts.append("Page text:\n" + page.text)
    return "\n\n".join(parts)
