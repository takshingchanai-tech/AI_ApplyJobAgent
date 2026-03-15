"""
Cover letter generation: LLM text + reportlab PDF.
"""

import logging
import textwrap
from pathlib import Path

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

COVER_LETTERS_DIR = Path(__file__).parent.parent / "data" / "cover_letters"


def _get_llm_client(settings: dict) -> AsyncOpenAI:
    model = settings.get("model", "gpt-4o-mini")
    if model == "qwen-max":
        return AsyncOpenAI(
            api_key=settings.get("dashscope_api_key", ""),
            base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        )
    return AsyncOpenAI(api_key=settings.get("openai_api_key", ""))


async def generate_cover_letter_text(job: dict, settings: dict) -> str:
    """Call LLM to generate a cover letter for the given job."""
    client = _get_llm_client(settings)
    model = settings.get("model", "gpt-4o-mini")

    freelancer_name = settings.get("freelancer_name", "")
    freelancer_bio = settings.get("freelancer_bio", "")
    freelancer_skills = settings.get("freelancer_skills", [])
    if isinstance(freelancer_skills, list):
        skills_str = ", ".join(freelancer_skills)
    else:
        skills_str = str(freelancer_skills)

    prompt = f"""Write a professional Upwork cover letter for the following job posting.

Job Title: {job.get('title', '')}
Client: {job.get('client_name', '')}
Budget: {job.get('budget', '')}
Job Type: {job.get('job_type', '')}
Job Description:
{job.get('description', '')[:2000]}

Freelancer Profile:
Name: {freelancer_name}
Bio: {freelancer_bio}
Skills: {skills_str}

Instructions:
- Write a compelling, personalised cover letter (200-350 words)
- Address the client's specific needs from the job description
- Highlight relevant experience and skills
- End with a clear call to action
- Do NOT use placeholders like [Your Name] — use the actual name above
- Write in first person, professional but approachable tone
- Do NOT include a subject line or "Dear Hiring Manager" header
- Start directly with an engaging opening sentence"""

    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.7,
    )
    return response.choices[0].message.content or ""


def generate_pdf(job_id: str, text: str) -> str:
    """Generate a PDF from cover letter text. Returns relative path."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch

    COVER_LETTERS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{job_id}_cover.pdf"
    filepath = COVER_LETTERS_DIR / filename

    c = canvas.Canvas(str(filepath), pagesize=letter)
    width, height = letter
    margin = inch
    text_width = width - 2 * margin

    c.setFont("Helvetica", 11)
    y = height - margin

    # Wrap text into lines that fit the page width
    lines = []
    for paragraph in text.split("\n"):
        if paragraph.strip() == "":
            lines.append("")
        else:
            wrapped = textwrap.wrap(paragraph, width=90)
            lines.extend(wrapped if wrapped else [""])

    for line in lines:
        if y < margin + 20:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = height - margin
        c.drawString(margin, y, line)
        y -= 16

    c.save()
    logger.info(f"Cover letter PDF saved: {filepath}")
    return f"data/cover_letters/{filename}"
