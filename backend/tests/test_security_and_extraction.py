import asyncio
import io

import pytest
from PIL import Image

from app.services import extraction_service as ex
from app.services import image_service, url_extractor
from app.utils import security
from app.utils.security import UnsafeURL, is_public_ip, parse_url, validate_url


# ---------------- SSRF ----------------
@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254", "0.0.0.0", "100.64.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "224.0.0.1", "255.255.255.255"],
)
def test_private_and_special_ips_blocked(ip):
    assert not is_public_ip(ip)


def test_public_ip_allowed():
    assert is_public_ip("8.8.8.8") and is_public_ip("2606:4700:4700::1111")


@pytest.mark.parametrize(
    "url",
    [
        "", "ftp://example.com/x", "file:///etc/passwd", "gopher://example.com", "javascript:alert(1)",
        "http://user:pw@example.com/", "http://example.com:8080/", "http://example.com:22/", "http://localhost/", "http://foo.localhost/",
        "http://printer.local/", "http://service.internal/", "https://exa mple.com", "http:///nohost", "http://example.com/\x00",
    ],
)
def test_bad_urls_rejected(url):
    with pytest.raises(UnsafeURL):
        parse_url(url)


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest/meta-data/", "http://10.1.2.3/", "http://2130706433/", "http://0x7f.1/"])
def test_literal_private_hosts_rejected(url):
    with pytest.raises(UnsafeURL):
        asyncio.run(validate_url(url))


def test_dns_resolving_to_private_is_rejected(monkeypatch):
    async def fake_getaddrinfo(self, host, port, **kw):
        return [(2, 1, 6, "", ("93.184.216.34", port)), (2, 1, 6, "", ("10.0.0.1", port))]  # one public + one private

    monkeypatch.setattr(asyncio.get_running_loop if False else asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURL):
        asyncio.run(validate_url("http://rebind.example.test/"))


def test_public_dns_accepted(monkeypatch):
    async def fake_getaddrinfo(self, host, port, **kw):
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)
    t = asyncio.run(validate_url("https://example.test/jobs?id=1"))
    assert t.ip == "93.184.216.34" and t.port == 443 and t.path_qs == "/jobs?id=1"


def test_redirect_to_private_is_blocked(monkeypatch):
    """A public page that redirects to an internal address must be refused (validated on every hop)."""
    import httpx

    calls = []

    async def fake_validate(url):
        calls.append(url)
        if "internal" in url or "169.254" in url:
            raise UnsafeURL("private")
        return security.SafeTarget(url=url, scheme="https", host="a.test", port=443, ip="93.184.216.34", path_qs="/")

    async def fake_once(client, t, deadline):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"}), b""

    monkeypatch.setattr(url_extractor, "validate_url", fake_validate)
    monkeypatch.setattr(url_extractor, "_fetch_once", fake_once)
    with pytest.raises(url_extractor.FetchError) as e:
        asyncio.run(url_extractor.fetch_page("https://a.test/"))
    assert e.value.code == "unsafe_redirect"


# ---------------- HTML parsing ----------------
def test_parse_html_extracts_text_and_jsonld_and_ignores_scripts():
    html = """<html><head><title>AI Intern</title><meta property="og:description" content="Join us">
    <script type="application/ld+json">{"@type":"JobPosting","title":"AI Intern","hiringOrganization":{"name":"Dobbe AI"}}</script>
    <script>alert('x')</script></head><body><nav>menu</nav><h1>AI Intern</h1><p>Remote role.</p><footer>f</footer></body></html>"""
    p = url_extractor.parse_html(html, "https://x.test/j")
    assert p.title == "AI Intern" and p.description == "Join us"
    assert "Remote role." in p.text and "alert" not in p.text and "menu" not in p.text
    assert p.json_ld and p.json_ld[0]["title"] == "AI Intern"


# ---------------- images ----------------
def make_img(fmt="PNG", size=(50, 40)):
    b = io.BytesIO()
    Image.new("RGB", size, "white").save(b, fmt)
    return b.getvalue()


def test_valid_images_accepted_and_reencoded():
    for fmt, name in (("PNG", "a.png"), ("JPEG", "a.jpg"), ("WEBP", "a.webp")):
        out, mime = image_service.process_image(make_img(fmt), name, 5_000_000)
        assert mime in ("image/png", "image/jpeg") and out


def test_exif_is_stripped():
    img = Image.new("RGB", (30, 30), "red")
    exif = img.getexif()
    exif[0x010F] = "SecretCameraMaker"
    b = io.BytesIO()
    img.save(b, "JPEG", exif=exif)
    out, _ = image_service.process_image(b.getvalue(), "p.jpg", 5_000_000)
    assert b"SecretCameraMaker" not in out


@pytest.mark.parametrize(
    "data,name",
    [(b"", "a.png"), (b"not an image", "a.png"), (b"<?php echo 1;?>", "shell.png"), (make_img("PNG"), "a.gif"), (make_img("PNG"), "noext"), (make_img("PNG"), "a.svg")],
)
def test_bad_images_rejected(data, name):
    with pytest.raises(image_service.ImageError):
        image_service.process_image(data, name, 5_000_000)


def test_gif_content_with_png_name_rejected():
    with pytest.raises(image_service.ImageError):
        image_service.process_image(make_img("GIF"), "x.png", 5_000_000)


def test_oversize_rejected():
    with pytest.raises(image_service.ImageError):
        image_service.process_image(make_img("PNG", (800, 800)), "a.png", 100)


# ---------------- extraction post-processing ----------------
def G(**over):
    base = dict(category="Internship Application", suggested_sheet_name="Internship Applications", description="d",
                columns=[ex.GColumn(name="Company", type="text"), ex.GColumn(name="Applied Date", type="date"), ex.GColumn(name="Salary", type="currency")],
                records=[], missing_fields=["Deadline"], confidence=1.7, warnings=[])
    base.update(over)
    return ex.GResult(**base)


def F(c, v, origin="extracted", unc=False):
    return ex.GField(column=c, value=v, origin=origin, uncertain=unc)


def test_finalize_normalises_and_flags():
    g = G(records=[ex.GRecord(fields=[F("Company", "Dobbe AI"), F("Applied Date", "2026-11-23"), F("Salary", "₹1,500"), F("Source", "LinkedIn", "inferred")])])
    out = ex.finalize(g, ex.SourceInfo(type="text"))
    rec = out.records[0]
    assert rec.values == {"Company": "Dobbe AI", "Applied Date": "2026-11-23", "Salary": 1500, "Source": "LinkedIn"}
    assert rec.meta["Source"].origin == "inferred" and rec.meta["Source"].uncertain  # inferred is always flagged
    assert [c.name for c in out.columns] == ["Company", "Applied Date", "Salary", "Source"]  # unknown field adds a column, not dropped
    assert out.category == "internship_application" and out.confidence == 1.0 and out.missing_fields == ["Deadline"]


def test_unparseable_value_is_kept_raw_and_flagged_not_dropped():
    g = G(records=[ex.GRecord(fields=[F("Company", "X"), F("Applied Date", "sometime in fall")])])
    rec = ex.finalize(g, ex.SourceInfo(type="text")).records[0]
    assert rec.values["Applied Date"] is None and rec.meta["Applied Date"].raw == "sometime in fall" and rec.meta["Applied Date"].uncertain


def test_null_values_stay_missing_and_empty_records_rejected():
    g = G(records=[ex.GRecord(fields=[F("Company", None), F("Salary", "  ")])])
    with pytest.raises(Exception) as e:
        ex.finalize(g, ex.SourceInfo(type="text"))
    assert getattr(e.value, "detail", {}).get("code") == "nothing_found"


def test_multiple_records_and_cap():
    recs = [ex.GRecord(fields=[F("Company", f"C{i}")]) for i in range(130)]
    out = ex.finalize(G(records=recs), ex.SourceInfo(type="text"))
    assert len(out.records) == 100 and any("first 100" in w for w in out.warnings)
