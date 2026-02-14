"""
Email templates for conference notifications.

Three templates:
1. NO_CHANGE: Scan completed, no changes
2. CHANGE_NO_DATES: Content changed but no deadlines found
3. CHANGE_WITH_DATES: URGENT - deadlines published
"""

from jinja2 import Environment, BaseLoader
from typing import List
from ..models.conference import Deadline
import logging

logger = logging.getLogger(__name__)


class EmailTemplates:
    """
    Jinja2 email templates for three notification types.

    Example:
        >>> templates = EmailTemplates()
        >>> html = templates.render_change_with_dates(
        ...     conference_name="UITP Summit",
        ...     url="https://...",
        ...     deadlines=[...],
        ...     ...
        ... )
    """

    NO_CHANGE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #f4f4f4; padding: 20px; border-radius: 5px; margin-bottom: 20px; }
        .header h2 { margin: 0; color: #666; }
        .content { padding: 20px; background: white; }
        .info-box { background: #f9f9f9; padding: 15px; border-left: 4px solid #2196F3; margin: 15px 0; }
        .footer { color: #999; font-size: 12px; padding: 20px; text-align: center; border-top: 1px solid #eee; margin-top: 20px; }
        ul { padding-left: 20px; }
        a { color: #2196F3; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>✓ Conference Monitored - No Changes</h2>
        </div>
        <div class="content">
            <p>Hello,</p>
            <p>The following conference website was successfully scanned and tracked:</p>

            <div class="info-box">
                <strong>Conference:</strong> {{ conference_name }}<br>
                <strong>URL:</strong> <a href="{{ url }}">{{ url }}</a><br>
                <strong>Scan Date:</strong> {{ scan_date }}<br>
                <strong>Status:</strong> No changes detected
            </div>

            {% if last_known_deadlines %}
            <p><strong>Previously Known Deadlines:</strong></p>
            <ul>
            {% for dl in last_known_deadlines %}
                <li>{{ dl.date }} - {{ dl.type|upper }}</li>
            {% endfor %}
            </ul>
            {% endif %}

            <p><strong>Next scheduled check:</strong> {{ next_run_date }}</p>
        </div>
        <div class="footer">
            ConBOT - Automated Conference Monitoring<br>
            <small>Watch Mode: {{ watch_mode }}</small>
        </div>
    </div>
</body>
</html>"""

    CHANGE_NO_DATES_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #fff3cd; padding: 20px; border-radius: 5px; border-left: 4px solid #ffc107; margin-bottom: 20px; }
        .header h2 { margin: 0; color: #856404; }
        .content { padding: 20px; background: white; }
        .info-box { background: #f9f9f9; padding: 15px; border-left: 4px solid #2196F3; margin: 15px 0; }
        .summary-box { background: #e7f3ff; padding: 15px; border-left: 4px solid #2196F3; margin: 15px 0; }
        .warning { background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 15px 0; }
        .footer { color: #999; font-size: 12px; padding: 20px; text-align: center; border-top: 1px solid #eee; margin-top: 20px; }
        ul { padding-left: 20px; }
        a { color: #2196F3; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>⚠️ Conference Website Updated</h2>
        </div>
        <div class="content">
            <p>Hello,</p>
            <p>Changes have been detected on a conference website you're monitoring:</p>

            <div class="info-box">
                <strong>Conference:</strong> {{ conference_name }}<br>
                <strong>URL:</strong> <a href="{{ url }}">{{ url }}</a><br>
                <strong>Scan Date:</strong> {{ scan_date }}<br>
                <strong>Change Type:</strong> {{ change_type }}
            </div>

            {% if summary %}
            <div class="summary-box">
                <h3>Summary of Changes</h3>
                {{ summary }}
            </div>
            {% endif %}

            <div class="warning">
                <strong>Note:</strong> No specific submission dates were detected yet.<br>
                <strong>Action:</strong> Monitoring frequency increased to biweekly checks.
            </div>

            <p><strong>Next check:</strong> {{ next_run_date }}</p>

            <p>Visit the conference website to check for Call for Papers announcements.</p>
        </div>
        <div class="footer">
            ConBOT - Automated Conference Monitoring<br>
            <small>Watch Mode: {{ watch_mode }} (upgraded from {{ previous_watch_mode }})</small>
        </div>
    </div>
</body>
</html>"""

    CHANGE_WITH_DATES_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #f8d7da; padding: 20px; border-radius: 5px; border-left: 4px solid #dc3545; margin-bottom: 20px; }
        .header h2 { margin: 0; color: #721c24; }
        .content { padding: 20px; background: white; }
        .urgent-box { background: #fff3cd; padding: 20px; border: 2px solid #dc3545; border-radius: 5px; margin: 20px 0; }
        .urgent-box h3 { margin-top: 0; color: #721c24; }
        .deadlines { background: #f9f9f9; padding: 15px; margin: 15px 0; border-radius: 5px; }
        .deadline-item { padding: 12px; border-left: 4px solid #28a745; margin: 10px 0; background: white; border-radius: 3px; }
        .deadline-date { font-size: 18px; font-weight: bold; color: #dc3545; }
        .summary-box { background: #e7f3ff; padding: 15px; border-left: 4px solid #2196F3; margin: 15px 0; }
        .info-box { background: #f9f9f9; padding: 15px; border-left: 4px solid #2196F3; margin: 15px 0; }
        .footer { color: #999; font-size: 12px; padding: 20px; text-align: center; border-top: 1px solid #eee; margin-top: 20px; }
        ul { padding-left: 20px; }
        a { color: #2196F3; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>🚨 URGENT: Conference Deadlines Published</h2>
        </div>
        <div class="content">
            <div class="urgent-box">
                <h3>⏰ Action Required - Deadlines Detected</h3>
                <p style="margin: 0;"><strong>{{ deadlines|length }}</strong> deadline(s) found for <strong>{{ conference_name }}</strong></p>
            </div>

            <div class="info-box">
                <strong>Conference:</strong> {{ conference_name }}<br>
                <strong>URL:</strong> <a href="{{ url }}">{{ url }}</a><br>
                <strong>Scan Date:</strong> {{ scan_date }}
            </div>

            <div class="deadlines">
                <h3>📅 Important Deadlines</h3>
                {% for deadline in deadlines %}
                <div class="deadline-item">
                    <div class="deadline-date">{{ deadline.date }}</div>
                    <strong>{{ deadline.type|upper }}</strong><br>
                    <em>{{ deadline.source_text[:150] }}{% if deadline.source_text|length > 150 %}...{% endif %}</em><br>
                    <small>Confidence: {{ (deadline.confidence * 100)|int }}%</small>
                </div>
                {% endfor %}
            </div>

            {% if summary %}
            <div class="summary-box">
                <h3>Summary</h3>
                {{ summary }}
            </div>
            {% endif %}

            <p><strong>Monitoring Status:</strong> Switched to URGENT mode (daily checks)</p>
            <p><strong>Next check:</strong> {{ next_run_date }}</p>

            <p><strong>Recommended Actions:</strong></p>
            <ul>
                <li>Review the conference website for full CFP details</li>
                <li>Add deadlines to your calendar</li>
                <li>Start preparing your submission</li>
            </ul>
        </div>
        <div class="footer">
            ConBOT - Automated Conference Monitoring<br>
            <small>Watch Mode: URGENT (upgraded from {{ previous_watch_mode }})</small>
        </div>
    </div>
</body>
</html>"""

    def __init__(self):
        """Initialize email templates."""
        self.env = Environment(loader=BaseLoader())

    def render_no_change(self, **kwargs) -> str:
        """
        Render NO_CHANGE email template.

        Args:
            **kwargs: Template variables (conference_name, url, scan_date, etc.)

        Returns:
            Rendered HTML email
        """
        template = self.env.from_string(self.NO_CHANGE_TEMPLATE)
        html = template.render(**kwargs)
        logger.debug(f"Rendered NO_CHANGE email for {kwargs.get('conference_name')}")
        return html

    def render_change_no_dates(self, **kwargs) -> str:
        """
        Render CHANGE_NO_DATES email template.

        Args:
            **kwargs: Template variables

        Returns:
            Rendered HTML email
        """
        template = self.env.from_string(self.CHANGE_NO_DATES_TEMPLATE)
        html = template.render(**kwargs)
        logger.debug(f"Rendered CHANGE_NO_DATES email for {kwargs.get('conference_name')}")
        return html

    def render_change_with_dates(self, **kwargs) -> str:
        """
        Render CHANGE_WITH_DATES email template.

        Args:
            **kwargs: Template variables

        Returns:
            Rendered HTML email
        """
        template = self.env.from_string(self.CHANGE_WITH_DATES_TEMPLATE)
        html = template.render(**kwargs)
        logger.debug(f"Rendered CHANGE_WITH_DATES email for {kwargs.get('conference_name')}")
        return html
