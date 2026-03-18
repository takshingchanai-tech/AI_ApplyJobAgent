"""
Upwork scraping agent — hybrid Playwright + LLM.
Deterministic Playwright handles all navigation/extraction;
LLM is used only for login-wall detection and field-level fallback.
Puts SSE events into a global asyncio.Queue consumed by /agent/stream.
"""

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

from playwright.async_api import async_playwright
from openai import AsyncOpenAI

# ---------------------------------------------------------------------------
# Selector constants
# ---------------------------------------------------------------------------

_JOB_CARD_SELECTORS = [
    "[data-test='job-tile']",
    "article[data-test='job-tile']",
    ".job-tile",
    "[data-job-uid]",
    "section.up-card-section",
    "div[class*='JobTile']",
]

_JOB_TITLE_LINK_SELECTORS = [
    "[data-test='job-tile-title-link']",
    "h2[data-test='job-title'] a",
    "h3 a[href*='/jobs/']",
    ".job-tile-title a",
    "a[href*='~']",
]

_SEE_MORE_SELECTORS = [
    "button[data-test='see-more-btn']",
    "button:has-text('See More')",
    "button:has-text('Show More')",
    "a:has-text('See More')",
    "span[data-test='expand']",
]

_AUTH_WALL_SELECTORS = [
    "input[name='username']",
    "input[name='password']",
    "h1:has-text('Log In')",
    "h1:has-text('Sign In')",
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "#challenge-form",
]

_FIELD_SELECTORS = {
    "title": [
        "h1[data-test='job-title']",
        "h1.m-0-bottom",
        "h1",
    ],
    "client_name": [
        "[data-test='client-name']",
        "[data-test='company-name']",
        ".client-name",
    ],
    "budget": [
        "[data-test='budget']",
        "[data-test='price']",
        ".up-rate",
        "strong[class*='budget']",
    ],
    "job_type": [
        "[data-test='job-type']",
        "[data-test='employment-type']",
        "li:has-text('Fixed') strong",
        "li:has-text('Hourly') strong",
    ],
    "experience": [
        "[data-test='experience-level']",
        "[data-test='contractor-tier']",
        "li:has-text('Level') strong",
    ],
    "description": [
        "[data-test='job-description-text']",
        "[data-test='description']",
        ".break div",
        ".job-description",
        "div[class*='description']",
    ],
    "skills": [
        "[data-test='attr-item']",
        "[data-test='skill-badge']",
        ".air3-token",
        "span[class*='skill']",
    ],
}

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_budget_value(budget_str: str) -> Optional[float]:
    """Extract first numeric value from a budget string like '$500', '$25/hr', '$500-$1,000'."""
    if not budget_str:
        return None
    numbers = re.findall(r'[\d]+(?:\.\d+)?', budget_str.replace(',', ''))
    if numbers:
        try:
            return float(numbers[0])
        except ValueError:
            pass
    return None


def _apply_filters(jobs: list, settings: dict) -> list:
    """Filter scraped jobs by budget, job type, and experience level from settings."""
    budget_min = float(settings.get("budget_min", 0) or 0)
    budget_max = float(settings.get("budget_max", 0) or 0)
    job_type_filter = (settings.get("job_type", "any") or "any").lower()
    experience_filter = (settings.get("experience", "any") or "any").lower()

    filtered = []
    for job in jobs:
        # Budget filter (only apply if min or max is non-zero)
        if budget_min > 0 or budget_max > 0:
            val = _parse_budget_value(job.get("budget", ""))
            if val is not None:
                if budget_min > 0 and val < budget_min:
                    continue
                if budget_max > 0 and val > budget_max:
                    continue

        # Job type filter
        if job_type_filter != "any":
            jt = (job.get("job_type", "") or "").lower()
            if job_type_filter == "fixed" and "fixed" not in jt:
                continue
            if job_type_filter == "hourly" and "hourly" not in jt:
                continue

        # Experience filter
        if experience_filter != "any":
            exp = (job.get("experience", "") or "").lower()
            exp_map = {
                "entry": ["entry"],
                "intermediate": ["intermediate"],
                "expert": ["expert"],
            }
            allowed = exp_map.get(experience_filter, [])
            if not any(a in exp for a in allowed):
                continue

        filtered.append(job)

    return filtered


def _extract_jobs_from_text(text: str) -> list:
    """Try multiple strategies to extract a jobs list from LLM output."""
    if not text:
        return []

    # Strategy 1: strip markdown fences, then parse whole text as JSON
    clean = re.sub(r'```(?:json)?\s*', '', text).strip().rstrip('`').strip()
    try:
        data = json.loads(clean)
        if isinstance(data, dict) and "jobs" in data:
            return data.get("jobs", [])
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # Strategy 2: grab outermost { ... } block
    start = clean.find('{')
    end = clean.rfind('}')
    if start != -1 and end > start:
        try:
            data = json.loads(clean[start:end + 1])
            if isinstance(data, dict) and "jobs" in data:
                return data.get("jobs", [])
        except json.JSONDecodeError:
            pass

    # Strategy 3: grab outermost [ ... ] array
    start = clean.find('[')
    end = clean.rfind(']')
    if start != -1 and end > start:
        try:
            data = json.loads(clean[start:end + 1])
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return []


# ---------------------------------------------------------------------------
# Cookie extraction (macOS Chrome → Playwright injection)
# ---------------------------------------------------------------------------

def _extract_chrome_cookies_for_host(chrome_profile_path: str, host_suffix: str) -> list:
    """
    Decrypt Chrome cookies for a host using the macOS Keychain encryption key.
    Returns a list of Playwright-compatible cookie dicts.
    """
    import subprocess, sqlite3, shutil, tempfile, hashlib
    try:
        # 1. Get Chrome's Safe Storage password from macOS Keychain
        # Use a short timeout — when called from a background process the dialog never shows
        res = subprocess.run(
            ["security", "find-generic-password", "-s", "Chrome Safe Storage", "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if res.returncode != 0:
            return []
        password = res.stdout.strip().encode()

        # 2. Derive 16-byte AES key via PBKDF2-HMAC-SHA1
        key = hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, dklen=16)

        # 3. Copy Cookies DB (avoid SQLite lock contention)
        cookies_path = os.path.join(chrome_profile_path, "Cookies")
        if not os.path.exists(cookies_path):
            return []
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        tmp.close()
        shutil.copy2(cookies_path, tmp.name)

        # 4. Decrypt each cookie value
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend

        conn = sqlite3.connect(tmp.name)
        rows = conn.execute(
            "SELECT name, encrypted_value, path, host_key, expires_utc, is_secure "
            "FROM cookies WHERE host_key LIKE ?",
            (f"%{host_suffix}%",),
        ).fetchall()
        conn.close()
        os.unlink(tmp.name)

        result = []
        for name, enc_val, path, host_key, expires_utc, is_secure in rows:
            try:
                if enc_val[:3] == b"v10":
                    cipher = Cipher(
                        algorithms.AES(key), modes.CBC(b" " * 16),
                        backend=default_backend(),
                    )
                    decryptor = cipher.decryptor()
                    raw = decryptor.update(enc_val[3:]) + decryptor.finalize()
                    padding = raw[-1]
                    value = raw[:-padding].decode("utf-8")
                else:
                    value = enc_val.decode("utf-8", errors="ignore")
                result.append({
                    "name": name, "value": value,
                    "domain": host_key.lstrip("."), "path": path or "/",
                    "secure": bool(is_secure),
                })
            except Exception:
                continue
        return result
    except Exception as e:
        logger.warning(f"[cookies] Could not extract Chrome cookies: {e}")
        return []


# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------

async def _detect_auth_wall(page, settings: dict) -> bool:
    """Return True if the page looks like a login wall or CAPTCHA."""
    # 1. Fast DOM check
    for sel in _AUTH_WALL_SELECTORS:
        try:
            if await page.locator(sel).first.count() > 0:
                return True
        except Exception:
            continue
    # 2. URL/title heuristic (no LLM call needed in most cases)
    title = await page.title()
    url = page.url
    if any(kw in title.lower() for kw in ["log in", "sign in", "captcha", "verify", "just a moment"]):
        return True
    if any(kw in url.lower() for kw in ["login", "signin", "captcha", "challenge"]):
        return True
    # 3. LLM confirmation only if heuristics inconclusive and key available
    api_key = settings.get("openai_api_key", "") or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return False
    client = AsyncOpenAI(api_key=api_key)
    resp = await client.chat.completions.create(
        model=settings.get("model", "gpt-4o-mini"),
        messages=[{"role": "user", "content":
            f"Page title: '{title}'\nURL: {url}\n"
            "Is this a login page, sign-in wall, or CAPTCHA? Answer only 'yes' or 'no'."}],
        max_tokens=3, temperature=0,
    )
    return (resp.choices[0].message.content or "").strip().lower().startswith("yes")


async def _expand_description(page) -> None:
    """Click 'See More' / 'Show More' to reveal full job description."""
    for sel in _SEE_MORE_SELECTORS:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                await el.click()
                await asyncio.sleep(0.5)
                return
        except Exception:
            continue


async def _extract_field_with_llm(field_name: str, context_html: str, settings: dict):
    """LLM fallback when DOM selectors find nothing for a field."""
    api_key = settings.get("openai_api_key", "") or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return [] if field_name == "skills" else ""
    model_name = settings.get("model", "gpt-4o-mini")
    if model_name == "qwen-max":
        client = AsyncOpenAI(
            api_key=settings.get("dashscope_api_key", "") or os.getenv("DASHSCOPE_API_KEY", ""),
            base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        )
    else:
        client = AsyncOpenAI(api_key=api_key)
    instructions = {
        "title": "Extract only the job title text.",
        "client_name": "Extract only the client or company name. Return empty string if absent.",
        "budget": "Extract only the budget or rate (e.g. '$500', '$25/hr'). Return empty string if absent.",
        "job_type": "Return only 'Fixed' or 'Hourly'. Return empty string if absent.",
        "experience": "Return only 'Entry Level', 'Intermediate', or 'Expert'. Return empty string if absent.",
        "description": "Extract the full job description text. Do not summarise.",
        "skills": "Extract all skill tags as a comma-separated list.",
    }
    resp = await client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content":
            f"HTML:\n{context_html[:3000]}\n\n{instructions.get(field_name, f'Extract {field_name}.')}\nReturn only the value."}],
        max_tokens=300, temperature=0,
    )
    raw = (resp.choices[0].message.content or "").strip()
    if field_name == "skills":
        return [s.strip() for s in raw.split(",") if s.strip()]
    return raw


async def _scrape_with_playwright(search_url, max_jobs, chrome_profile, settings, emit) -> list:
    """Deterministic Playwright scraper with LLM field-fallback."""
    async with async_playwright() as p:
        # Priority 1: connect to agent Chrome launched by start.sh via CDP (bypasses Cloudflare)
        connected_via_cdp = False
        context = None
        try:
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            connected_via_cdp = True
            await emit({"type": "log", "level": "info",
                        "message": "Connected to agent Chrome via CDP (real browser session)."})
        except Exception:
            await emit({"type": "log", "level": "warn",
                        "message": (
                            "Chrome not running with remote debugging on port 9222. "
                            "To bypass Cloudflare, pre-launch Chrome before starting the agent: "
                            "open -a 'Google Chrome' --args --remote-debugging-port=9222 "
                            "--disable-blink-features=AutomationControlled"
                        )})

        # Priority 2: launch persistent context with user's Chrome profile
        if not connected_via_cdp:
            if chrome_profile:
                import shutil, tempfile
                tmpdir = tempfile.mkdtemp(prefix="pw-profile-")
                profile_copy = os.path.join(tmpdir, "Default")
                try:
                    shutil.copytree(chrome_profile, profile_copy, symlinks=False,
                                    ignore=shutil.ignore_patterns(
                                        "SingletonLock", "SingletonCookie", "SingletonSocket",
                                        "lockfile", "CrashpadMetrics*"))
                except Exception:
                    tmpdir = None
                if tmpdir:
                    context = await p.chromium.launch_persistent_context(profile_copy, headless=True)
                else:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context()
            else:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()

        page = await context.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

        # Inject real Chrome cookies (cf_clearance + Upwork session) so Cloudflare passes
        if chrome_profile:
            await emit({"type": "log", "level": "info",
                        "message": "Extracting Chrome cookies — approve macOS Keychain dialog if it appears..."})
            cookies = _extract_chrome_cookies_for_host(chrome_profile, "upwork.com")
            if cookies:
                cf = [c for c in cookies if c["name"] == "cf_clearance"]
                await context.add_cookies(cookies)
                await emit({"type": "log", "level": "info",
                            "message": f"Injected {len(cookies)} Chrome cookies ({len(cf)} cf_clearance) into Playwright."})
            else:
                await emit({"type": "log", "level": "warn",
                            "message": "No Upwork cookies found in Chrome profile. Make sure you are logged into Upwork in Chrome and have visited Upwork recently. Will continue without cookies."})

        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        try:
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        try:
            page_title = await page.title()
        except Exception:
            page_title = ""
        page_url = page.url
        logger.info(f"[playwright] Landed on: {page_url} | title: {page_title}")
        await emit({"type": "log", "level": "info",
                    "message": f"Landed on: {page_url} | title: {page_title}"})

        if await _detect_auth_wall(page, settings):
            if connected_via_cdp:
                # Headed Chrome is visible — ask user to solve CAPTCHA
                await emit({"type": "log", "level": "warn",
                            "message": "⚠️ Cloudflare challenge detected. Please solve the CAPTCHA in the Chrome window that opened. Waiting up to 60 seconds..."})
                for _ in range(30):
                    await asyncio.sleep(2)
                    try:
                        # wait_until="domcontentloaded" gives page a chance to finish navigation
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    try:
                        t = await page.title()
                        body_check = await page.inner_text("body")
                    except Exception:
                        # Execution context destroyed mid-navigation — wait and retry
                        continue
                    still_blocked = any(kw in t.lower() for kw in [
                        "just a moment", "challenge", "log in", "sign in", "captcha", "verify"
                    ]) or "cloudflare ray id" in body_check.lower()
                    if not still_blocked:
                        await emit({"type": "log", "level": "info",
                                    "message": f"✅ Cloudflare passed! Continuing scrape (title: {t})"})
                        break
                else:
                    await emit({"type": "log", "level": "warn",
                                "message": "CAPTCHA not solved in time. Falling back to browser-use."})
                    await page.close()
                    return []
            else:
                await emit({"type": "log", "level": "warn",
                            "message": f"Cloudflare / login wall detected on Playwright (title: '{page_title}'). Falling back to browser-use."})
                await page.close()
                if not connected_via_cdp:
                    await context.close()
                return []

        # Find job cards
        cards = None
        for sel in _JOB_CARD_SELECTORS:
            els = page.locator(sel)
            count = await els.count()
            if count > 0:
                cards = els
                await emit({"type": "log", "level": "info",
                            "message": f"Found {count} job cards with selector: {sel}"})
                break
        if not cards:
            # Save HTML for selector diagnostics
            html_snapshot = await page.content()
            debug_path = os.path.join(os.path.dirname(__file__), "..", "data", "debug_search_page.html")
            try:
                os.makedirs(os.path.dirname(debug_path), exist_ok=True)
                with open(debug_path, "w", encoding="utf-8") as _f:
                    _f.write(html_snapshot)
            except Exception:
                pass
            body_text = await page.inner_text("body")
            snippet = body_text[:500].replace("\n", " ").strip()
            logger.warning(f"[playwright] No job cards found. Page text: {snippet}")
            await emit({"type": "log", "level": "warn",
                        "message": f"No job cards found — selectors may be stale. Page text: {snippet}"})
            await context.close()
            return []

        # Collect job URLs from cards
        job_urls = []
        count = min(await cards.count(), max_jobs)
        for i in range(count):
            card = cards.nth(i)
            for link_sel in _JOB_TITLE_LINK_SELECTORS:
                el = card.locator(link_sel).first
                if await el.count() > 0:
                    href = await el.get_attribute("href")
                    if href:
                        if not href.startswith("http"):
                            href = "https://www.upwork.com" + href
                        job_urls.append(href)
                        break

        # Visit each job detail page
        results = []
        for job_url in job_urls:
            try:
                await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(1.5)
                if await _detect_auth_wall(page, settings):
                    break
                await _expand_description(page)

                job = {"job_url": page.url, "id": _extract_id_from_url(page.url)}
                html_snapshot = await page.content()

                for field, selectors in _FIELD_SELECTORS.items():
                    value = None
                    for sel in selectors:
                        try:
                            if field == "skills":
                                els = page.locator(sel)
                                n = await els.count()
                                if n > 0:
                                    value = [
                                        (await els.nth(i).inner_text()).strip()
                                        for i in range(n)
                                        if (await els.nth(i).inner_text()).strip()
                                    ]
                                    break
                            else:
                                el = page.locator(sel).first
                                if await el.count() > 0 and await el.is_visible():
                                    text = (await el.inner_text()).strip()
                                    if text:
                                        value = text
                                        break
                        except Exception:
                            continue
                    if not value:
                        value = await _extract_field_with_llm(field, html_snapshot, settings)
                    job[field] = value or ([] if field == "skills" else "")

                results.append(job)
            except Exception as e:
                await emit({"type": "log", "level": "warn", "message": f"Skipping job (error): {e}"})
                continue

        await page.close()
        if not connected_via_cdp:
            await context.close()
        return results


async def run_scrape_agent(
    sse_queue: asyncio.Queue,
    settings: dict,
    run_id: str,
) -> None:
    """
    Main scraping loop. Searches Upwork for jobs matching keywords,
    deduplicates, generates cover letters, and saves to DB.
    """
    from services.jobs import job_exists, upsert_job, get_job_counts
    from cover_letter import generate_cover_letter_text, generate_pdf
    from notifications import send_notification

    async def emit(event: dict):
        await sse_queue.put(event)

    await emit({"type": "agent_started", "run_id": run_id, "timestamp": _now()})
    await emit({"type": "log", "level": "info", "message": "Agent starting up..."})

    keywords: list = settings.get("keywords", [])
    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except Exception:
            keywords = [keywords]

    if not keywords:
        await emit({"type": "log", "level": "warn", "message": "No keywords configured. Add keywords in Settings."})
        await emit({"type": "agent_stopped", "reason": "done"})
        return

    max_jobs = int(settings.get("max_jobs_per_run", 10))
    chrome_profile = settings.get("chrome_profile", "") or os.getenv("CHROME_PROFILE_PATH", "")

    await emit({"type": "log", "level": "info", "message": f"Searching for: {', '.join(keywords)} (max {max_jobs} jobs)"})

    jobs_found = 0
    jobs_ready = 0

    try:
        query = " ".join(keywords)
        search_url = f"https://www.upwork.com/nx/search/jobs/?q={quote_plus(query)}&sort=recency"

        await emit({"type": "log", "level": "info", "message": "Launching headless browser (Playwright)..."})

        try:
            scraped_jobs = await _scrape_with_playwright(
                search_url=search_url,
                max_jobs=max_jobs,
                chrome_profile=chrome_profile,
                settings=settings,
                emit=emit,
            )
            if not scraped_jobs:
                raise RuntimeError("Playwright returned no jobs — triggering browser-use fallback")

        except Exception as pw_err:
            await emit({"type": "log", "level": "warn",
                        "message": f"Playwright scraper issue ({pw_err}). Trying browser-use fallback..."})
            try:
                from browser_use import Agent as BrowserAgent
                from browser_use.browser.profile import BrowserProfile
                from browser_use.llm.openai.chat import ChatOpenAI as BUChatOpenAI

                openai_api_key = settings.get("openai_api_key", "") or os.getenv("OPENAI_API_KEY", "")
                dashscope_api_key = settings.get("dashscope_api_key", "") or os.getenv("DASHSCOPE_API_KEY", "")

                # browser-use works best with gpt-4o-mini (reliable structured outputs, fast)
                # Fall back to qwen-max only when no OpenAI key is available
                if openai_api_key:
                    llm = BUChatOpenAI(
                        model="gpt-4o-mini",
                        api_key=openai_api_key,
                        temperature=0.1,
                    )
                else:
                    llm = BUChatOpenAI(
                        model="qwen-max",
                        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                        api_key=dashscope_api_key,
                        temperature=0.1,
                        add_schema_to_system_prompt=True,
                        dont_force_structured_output=True,
                    )

                profile_kwargs = {"headless": True}
                if chrome_profile:
                    profile_kwargs["user_data_dir"] = chrome_profile

                browser_profile = BrowserProfile(**profile_kwargs)

                task = f"""Go to {search_url}

If you are redirected to a login page, sign-in wall, or CAPTCHA, return immediately:
{{"error": "login_required", "jobs": []}}

Wait up to 5 seconds for job listings to load. Scroll down once to reveal all visible jobs.

Find up to {max_jobs} job listings. For EACH job listing:
1. Click the job title link to open the full job detail page.
2. Wait up to 5 seconds for the page to load fully.
3. Extract these fields from the detail page:
   - title: the full job title
   - client_name: client or company name if visible, else empty string
   - budget: e.g. "$500", "$25/hr", "$500-$1,000" (the posted budget or rate)
   - job_type: "Fixed" or "Hourly"
   - experience: "Entry Level", "Intermediate", or "Expert"
   - description: the COMPLETE, untruncated job description text (do not summarise)
   - skills: list of skill/expertise tags shown on the page
   - job_url: the current full page URL
   - id: the job ID from the URL (e.g. ~01234567890abcdef)
4. Click the browser Back button to return to the search results page.
5. Proceed to the next job listing.

After processing all jobs, return ONLY valid JSON — no markdown fences, no explanation, no extra text:
{{
  "jobs": [
    {{
      "id": "~01234567890abcdef",
      "title": "Job Title",
      "client_name": "Client Name or empty string",
      "budget": "$500 or $25/hr",
      "job_type": "Fixed or Hourly",
      "experience": "Entry Level / Intermediate / Expert",
      "description": "Full job description text",
      "skills": ["skill1", "skill2"],
      "job_url": "https://www.upwork.com/jobs/..."
    }}
  ]
}}"""

                agent = BrowserAgent(task=task, llm=llm, browser_profile=browser_profile)

                history = await agent.run()

                result_text = history.final_result() or ""
                if not result_text:
                    extracted = history.extracted_content()
                    result_text = "\n".join(extracted) if extracted else ""

                logger.info(f"[agent] Raw result (first 500 chars): {result_text[:500]}")
                await emit({"type": "log", "level": "info",
                            "message": f"Browser result received ({len(result_text)} chars)"})

                scraped_jobs = _extract_jobs_from_text(result_text)
                if not scraped_jobs:
                    await emit({"type": "log", "level": "warn",
                                "message": f"Could not parse job listings. Raw: {result_text[:300]}"})

            except ImportError:
                await emit({"type": "log", "level": "warn",
                            "message": "browser-use not available, using mock data"})
                scraped_jobs = _get_mock_jobs(keywords)
            except Exception as e:
                await emit({"type": "log", "level": "error", "message": f"Browser agent error: {e}"})
                scraped_jobs = []

        # Apply user-configured filters (budget/type/experience)
        before_count = len(scraped_jobs)
        scraped_jobs = _apply_filters(scraped_jobs, settings)
        filtered_out = before_count - len(scraped_jobs)
        if filtered_out > 0:
            await emit({"type": "log", "level": "info", "message": f"Filtered out {filtered_out} jobs by budget/type/experience settings"})

        await emit({"type": "log", "level": "info", "message": f"Processing {len(scraped_jobs)} jobs after filtering"})

        # Process each job
        for raw_job in scraped_jobs[:max_jobs]:
            job_id = raw_job.get("id") or _extract_id_from_url(raw_job.get("job_url", ""))
            if not job_id:
                job_id = str(uuid.uuid4())[:16]

            title = raw_job.get("title", "Untitled")
            jobs_found += 1

            # Dedup check
            if job_exists(job_id):
                await emit({"type": "job_skipped", "job_id": job_id, "reason": "already seen"})
                await emit({"type": "log", "level": "info", "message": f"Skipped (seen): {title}"})
                continue

            await emit({"type": "job_found", "job_id": job_id, "title": title, "budget": raw_job.get("budget", "")})
            await emit({"type": "log", "level": "info", "message": f"Processing: {title}"})

            # Save as 'seen' immediately so it appears in the UI even if cover letter fails
            job_data = {
                "id": job_id,
                "title": title,
                "client_name": raw_job.get("client_name", ""),
                "budget": raw_job.get("budget", ""),
                "job_type": raw_job.get("job_type", ""),
                "experience": raw_job.get("experience", ""),
                "description": raw_job.get("description", ""),
                "skills": raw_job.get("skills", []),
                "job_url": raw_job.get("job_url", ""),
                "status": "seen",
            }
            upsert_job(job_data)

            # Generate cover letter with up to 3 retries (exponential backoff)
            await emit({"type": "generating_cover_letter", "job_id": job_id, "title": title})
            await emit({"type": "log", "level": "info", "message": f"Generating cover letter for: {title}"})

            for attempt in range(1, 4):
                try:
                    cover_text = await generate_cover_letter_text(job_data, settings)
                    pdf_path = generate_pdf(job_id, cover_text)

                    from services.jobs import update_job
                    update_job(job_id, {
                        "status": "ready",
                        "cover_letter_text": cover_text,
                        "cover_letter_pdf": pdf_path,
                    })

                    jobs_ready += 1
                    await emit({
                        "type": "job_ready",
                        "job_id": job_id,
                        "title": title,
                        "job_url": raw_job.get("job_url", ""),
                    })
                    await emit({"type": "log", "level": "info", "message": f"Ready: {title}"})
                    send_notification("Upwork Job Ready", title, subtitle="Cover letter generated")
                    break

                except Exception as e:
                    if attempt < 3:
                        wait = 2 ** attempt  # 2s then 4s
                        await emit({"type": "log", "level": "warn",
                                    "message": f"Cover letter attempt {attempt} failed for '{title}': {e}. Retrying in {wait}s..."})
                        await asyncio.sleep(wait)
                    else:
                        await emit({"type": "error", "message": str(e), "job_id": job_id})
                        await emit({"type": "log", "level": "error",
                                    "message": f"Cover letter failed after 3 attempts for '{title}': {e}. Job saved as 'seen' — retry from the Pending tab."})

            # Emit updated counts after each job
            counts = get_job_counts()
            await emit({"type": "counts_updated", "counts": counts})

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        await emit({"type": "agent_stopped", "reason": "cancelled"})
        return
    except Exception as e:
        logger.error(f"Agent error: {e}")
        await emit({"type": "error", "message": str(e)})
        await emit({"type": "agent_stopped", "reason": "error"})
        return

    await emit({"type": "done", "jobs_found": jobs_found, "jobs_ready": jobs_ready})
    await emit({"type": "agent_stopped", "reason": "done"})
    await emit({"type": "log", "level": "info", "message": f"Done. Found: {jobs_found}, Ready: {jobs_ready}"})


def _extract_id_from_url(url: str) -> str:
    """Extract Upwork job ID from URL (e.g. ~01234567890abcdef)."""
    match = re.search(r'(~[0-9a-f]{16,})', url)
    return match.group(1) if match else ""


def _get_mock_jobs(keywords: list) -> list:
    """Return mock jobs for testing when browser-use is unavailable."""
    return [
        {
            "id": "~mock001",
            "title": f"Python Developer for {keywords[0] if keywords else 'Web'} Project",
            "client_name": "Test Client",
            "budget": "$500 - $1,000",
            "job_type": "Fixed",
            "experience": "Intermediate",
            "description": "We need an experienced Python developer to build a web scraping tool. "
                           "The ideal candidate has experience with FastAPI, Playwright, and SQLite. "
                           "This is a short-term project with potential for ongoing work.",
            "skills": ["Python", "FastAPI", "Playwright", "SQLite"],
            "job_url": "https://www.upwork.com/jobs/~mock001",
        },
        {
            "id": "~mock002",
            "title": f"AI Agent Developer — {keywords[0] if keywords else 'Automation'}",
            "client_name": "Startup Co",
            "budget": "$30/hr",
            "job_type": "Hourly",
            "experience": "Expert",
            "description": "Looking for an AI agent developer to build automation workflows "
                           "using LLMs. Must have experience with LangChain, OpenAI API, and "
                           "browser automation. Remote work, flexible hours.",
            "skills": ["Python", "LangChain", "OpenAI", "LLM", "browser-use"],
            "job_url": "https://www.upwork.com/jobs/~mock002",
        },
    ]
