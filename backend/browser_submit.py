"""
HITL (Human-In-The-Loop) browser submission.
Opens a headed Playwright browser pre-filled with the cover letter
so the user can review and click Submit manually.
"""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

# Upwork 2025/2026 selectors (ordered by specificity, broad fallbacks last)
_APPLY_BTN_SELECTORS = [
    "[data-test='apply-button']",
    "[data-test='submit-proposal-button']",
    "button[data-cy='apply-button']",
    "button:has-text('Apply Now')",
    "a:has-text('Apply Now')",
    "button:has-text('Submit a Proposal')",
    "button:has-text('Send Proposal')",
    "a:has-text('Submit a Proposal')",
]

_COVER_LETTER_SELECTORS = [
    "[data-test='cover-letter-text'] textarea",
    "[data-test='cover-letter'] textarea",
    "textarea[data-test='cover-letter-text']",
    "textarea[data-test='cover-letter']",
    "div[data-test='cover-letter'] textarea",
    "textarea[name='cover_letter']",
    "textarea[placeholder*='cover letter' i]",
    "textarea[aria-label*='cover letter' i]",
    ".cover-letter-text textarea",
    "[class*='cover-letter'] textarea",
    "textarea",  # broad fallback
]

_FILE_INPUT_SELECTORS = [
    "input[type='file'][accept*='pdf']",
    "input[type='file'][accept*='application']",
    "input[type='file']",
]


async def open_for_review(job: dict, settings: dict) -> None:
    """
    Launch a headed Playwright browser to the job's proposal page.
    Pre-fills cover letter text and attaches files. Stays open for the user to submit.
    """
    from playwright.async_api import async_playwright

    job_url = job.get("job_url", "")
    cover_letter_text = job.get("cover_letter_text", "")
    chrome_profile = settings.get("chrome_profile", "") or os.getenv("CHROME_PROFILE_PATH", "")

    if not job_url:
        raise ValueError("Job has no URL")

    logger.info(f"Opening headed browser for: {job.get('title', job.get('id'))}")

    async with async_playwright() as p:
        if chrome_profile:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=chrome_profile,
                headless=False,
                args=["--start-maximized"],
                no_viewport=True,
            )
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
            context = await browser.new_context(no_viewport=True)
            page = await context.new_page()

        # Navigate to the job page
        await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Click "Apply Now" or equivalent button
        apply_clicked = False
        for selector in _APPLY_BTN_SELECTORS:
            try:
                el = page.locator(selector).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(2)
                    apply_clicked = True
                    logger.info(f"Clicked apply button: {selector}")
                    break
            except Exception:
                continue

        if not apply_clicked:
            logger.warning("Could not find apply button — page may already be on proposal form")

        # Pre-fill cover letter textarea
        if cover_letter_text:
            prefilled = False
            for selector in _COVER_LETTER_SELECTORS:
                try:
                    el = page.locator(selector).first
                    if await el.count() > 0 and await el.is_visible():
                        await el.click()
                        await el.fill(cover_letter_text)
                        prefilled = True
                        logger.info(f"Cover letter pre-filled using selector: {selector}")
                        break
                except Exception:
                    continue

            if not prefilled:
                logger.warning(
                    "Could not pre-fill cover letter textarea — Upwork DOM may have changed. "
                    "Please paste the cover letter manually."
                )

        # Attach resume and portfolio if they exist
        resume_path = settings.get("resume_path", "")
        portfolio_path = settings.get("portfolio_path", "")

        for file_path, label in [(resume_path, "resume"), (portfolio_path, "portfolio")]:
            if not file_path or not os.path.exists(file_path):
                continue
            attached = False
            for selector in _FILE_INPUT_SELECTORS:
                try:
                    inputs = page.locator(selector)
                    count = await inputs.count()
                    for i in range(count):
                        el = inputs.nth(i)
                        if await el.count() > 0:
                            await el.set_input_files(file_path)
                            attached = True
                            logger.info(f"Attached {label}: {file_path}")
                            break
                    if attached:
                        break
                except Exception:
                    continue
            if not attached:
                logger.warning(f"Could not attach {label} — file input not found")

        logger.info("Browser open — waiting for user to review and submit")

        # Keep alive until user closes the browser
        try:
            while True:
                if not context.pages:
                    break
                if all(pg.is_closed() for pg in context.pages):
                    break
                await asyncio.sleep(1)
        except Exception:
            pass

        logger.info("Browser closed by user")
