"""macOS notification via osascript."""

import subprocess
import logging

logger = logging.getLogger(__name__)


def send_notification(title: str, message: str, subtitle: str = "") -> None:
    try:
        script = (
            f'display notification "{message}" '
            f'with title "{title}"'
        )
        if subtitle:
            script += f' subtitle "{subtitle}"'
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )
    except Exception as e:
        logger.warning(f"Notification failed: {e}")
