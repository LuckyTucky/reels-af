"""Article URL → Essence (one harness call: fetch + distill)."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import aiohttp
from readability import Document

from reel_af.models import Essence

# Hard caps so a hostile URL can't blow up the pipeline.
FETCH_TIMEOUT_S = 30.0
MAX_BODY_CHARS = 50_000
PROMPT_BODY_CHARS = 14_000
# Real browser identity: many sites (stupiddope, lifestyle/news pages, etc.)
# serve an empty shell or a block page to non-browser agents, which makes
# readability find no article body. A normal Chrome UA fixes most of these.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _resolve_google_news(url: str) -> str:
    """Google News RSS links (news.google.com/rss/articles/CBMi…) are encoded
    redirects that resolve to a consent/JS page with no article. Best-effort:
    decode the id and pull the real destination URL out of it. Fail-safe —
    returns the original URL unchanged if anything doesn't line up."""
    import base64

    m = re.search(r"news\.google\.com/(?:rss/)?articles/([A-Za-z0-9_\-]+)", url)
    if not m:
        return url
    token = m.group(1)
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except Exception:  # noqa: BLE001
        return url
    for cand in re.findall(rb"https?://[A-Za-z0-9._~:/?#@!$&'()*+,;=%\[\]-]+", raw):
        u = cand.decode("utf-8", "replace")
        if "google.com" not in u:
            return u
    return url


_SYSTEM = """You are reading an article and extracting ITS ESSENCE for a short-form vertical video reel. ONE shot. The hook is the single most surprising or counter-intuitive thing in the piece — NOT the article's overall topic, NOT a tidy summary. The buzz-worthy claim that makes a thumb stop scrolling.

Rules:
  - core_claim: the ONE most surprising/counter-intuitive sentence the author would recognize. ≤25 words. This is the hook's raw material.
  - mechanism: 1-2 sentences explaining WHY the claim is true / HOW it works. The payoff to the hook.
  - evidence: 1-3 concrete grounding items — numbers, named entities, specific examples — verbatim or near-verbatim from the article. NOT paraphrases. NOT your own analysis.
  - content_mode: "scientific" ONLY if the source is a research paper / preprint / technical write-up with method + result + baseline shape (a Medium post explaining a paper still counts). Otherwise "general".
  - domain: one word for the subject area (e.g. "technology", "biology", "finance", "philosophy", "health", "design").

Stay faithful. Don't invent examples. Don't soften surprising claims. Pick the one thing in this article that, stated as a thumbnail, would make a stranger tap."""


# Signes qu'un simple téléchargement HTTP n'a PAS obtenu l'article : la page
# exige JavaScript, ou renvoie une page de redirection/anti-robot quasi vide.
_JS_GATE_MARKERS = (
    "javascript is required",
    "enable javascript",
    "please enable js",
    "requires javascript",
    "you are being redirected",
    "checking your browser",
    "cf-browser-verification",
    "just a moment",
)


async def _fetch(url: str) -> tuple[str, str]:
    """Fetch URL, return (raw_html, final_url)."""
    url = _resolve_google_news(url)
    timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT_S)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    }
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True, max_redirects=5) as resp:
            resp.raise_for_status()
            text = await resp.text(errors="replace")
            return text, str(resp.url)


async def _fetch_rendered(url: str) -> tuple[str, str]:
    """Repli : charge la page dans un vrai navigateur (Chromium headless) qui
    EXÉCUTE le JavaScript, puis renvoie le HTML rendu. Gère les pages
    JS-gated et suit nativement les redirections Google News."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        try:
            page = await browser.new_page(user_agent=USER_AGENT, locale="en-US")
            await page.goto(
                url, wait_until="domcontentloaded",
                timeout=int(FETCH_TIMEOUT_S * 1000),
            )
            # Laisse le JS peupler le contenu (best-effort, on n'échoue pas dessus).
            try:
                await page.wait_for_load_state(
                    "networkidle", timeout=int(FETCH_TIMEOUT_S * 1000)
                )
            except Exception:  # noqa: BLE001
                pass
            html = await page.content()
            final = page.url
            return html, final
        finally:
            await browser.close()


def _clean(html: str) -> tuple[str, str]:
    """Run readability for clean title + body. Pure CPU."""
    doc = Document(html)
    title = (doc.short_title() or doc.title() or "").strip()
    content_html = doc.summary(html_partial=True)
    text = re.sub(r"<[^>]+>", " ", content_html)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS]
    return title, text


def _insuffisant(title: str, body: str) -> bool:
    """Vrai si l'extraction HTTP simple n'a manifestement pas récupéré l'article
    (corps vide/trop court, ou message « activez JavaScript » / anti-robot)."""
    if len(body) < 200:
        return True
    t = f"{title} {body}".lower()
    return any(m in t for m in _JS_GATE_MARKERS)


async def extract_essence(app: Any, url: str) -> Essence:
    """Single harness: fetch the article, extract the most surprising
    claim + mechanism + evidence + content_mode + domain.

    Chemin rapide : téléchargement HTTP + readability. Si la page est vide ou
    verrouillée par JavaScript, on bascule automatiquement sur un navigateur
    headless (Chromium) qui exécute le JS, puis on ré-extrait."""
    loop = asyncio.get_event_loop()
    final_url = url
    try:
        html, final_url = await _fetch(url)
        title, body = await loop.run_in_executor(None, _clean, html)
    except Exception:  # noqa: BLE001
        # Le téléchargement HTTP a échoué (403/anti-robot, timeout, réseau…).
        # On force le repli navigateur headless ci-dessous.
        title, body = "", ""

    if _insuffisant(title, body):
        # Repli navigateur headless : exécute le JS ET présente une vraie
        # empreinte de navigateur — contourne souvent les blocages 403 et
        # les pages « activez JavaScript ».
        try:
            html, final_url = await _fetch_rendered(url)
            title, body = await loop.run_in_executor(None, _clean, html)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Extraction impossible depuis {url} : la page est bloquée "
                f"(anti-robot) ou exige JavaScript, et le navigateur headless "
                f"a aussi échoué ({exc}). Essaie l'URL directe de l'article."
            )

    if not body:
        raise RuntimeError(
            f"Impossible d'extraire un texte lisible depuis {final_url}, "
            "même avec le navigateur headless. La page n'a peut-être pas de "
            "véritable article. Essaie l'URL directe de l'article."
        )

    user = (
        f"ARTICLE\n"
        f"  url   : {final_url}\n"
        f"  title : {title or '(no title)'}\n\n"
        f"FULL BODY (cleaned, truncated to fit context):\n{body[:PROMPT_BODY_CHARS]}"
    )

    return await app.ai(system=_SYSTEM, user=user, schema=Essence)


async def essence_from_text(app: Any, text: str) -> Essence:
    """text_to_reel mode='brute' : même distillation que extract_essence,
    mais SANS fetch/readability — le texte collé remplace directement le
    corps d'article dans le prompt."""
    body = text.strip()[:PROMPT_BODY_CHARS]
    user = (
        f"ARTICLE\n"
        f"  url   : (texte collé, aucune URL)\n"
        f"  title : (aucun — texte brut)\n\n"
        f"FULL BODY (as pasted, truncated to fit context):\n{body}"
    )
    return await app.ai(system=_SYSTEM, user=user, schema=Essence)
