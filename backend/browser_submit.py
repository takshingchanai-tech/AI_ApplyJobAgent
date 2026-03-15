"""
HITL (Human-In-The-Loop) browser submission.
Opens a headed Playwright browser pre-filled with the cover letter
so the user can review and click Submit manually.
"""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


async def open_for_review(job: dict, settings: dict) -> None:
    """
    Launch a headed Playwright browser to the job's proposal page.
    Pre-fills cover letter text. Stays open for the user to submit.
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

        # Wait for page to settle
        await asyncio.sleep(2)

        # Try to find and click "Apply Now" or similar button
        try:
            apply_btn = page.locator("button:has-text('Apply Now'), a:has-text('Apply Now'), button:has-text('Submit a Proposal')")
            if await apply_btn.count() > 0:
                await apply_btn.first.click()
                await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Could not find apply button: {e}")

        # Try to fill cover letter textarea
        if cover_letter_text:
            try:
                selectors = [
                    "textarea[name='cover_letter']",
                    "textarea[placeholder*='cover letter']",
                    "textarea[placeholder*='Cover letter']",
                    "[data-test='cover-letter-text'] textarea",
                    "div[aria-label*='cover letter'] textarea",
                    "textarea",
                ]
                for selector in selectors:
                    try:
                        el = page.locator(selector).first
                        if await el.count() > 0 and await el.is_visible():
                            await el.click()
                            await el.fill(cover_letter_text)
                            logger.info("Cover letter pre-filled")
                            break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"Could not pre-fill cover letter: {e}")

        # Attach files if paths are set
        resume_path = settings.get("resume_path", "")
        portfolio_path = settings.get("portfolio_path", "")

        for file_path, label in [(resume_path, "resume"), (portfolio_path, "portfolio")]:
            if file_path and os.path.exists(file_path):
                try:
                    file_input = page.locator("input[type='file']").first
                    if await file_input.count() > 0:
                        await file_input.set_input_files(file_path)
                        logger.info(f"Attached {label}: {file_path}")
                except Exception as e:
                    logger.warning(f"Could not attach {label}: {e}")

        logger.info("Browser open — waiting for user to submit or close")

        # Keep the browser open until the user closes it
        try:
            while True:
                if not context.pages:
                    break
                all_closed = all(p.is_closed() for p in context.pages)
                if all_closed:
                    break
                await asyncio.sleep(1)
        except Exception:
            pass

        logger.info("Browser closed by user")
