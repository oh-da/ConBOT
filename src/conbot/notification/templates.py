"""
Email template for the scan report.

One email per run lists every conference that was scanned, grouped by outcome:
1. CHANGE_WITH_DATES: deadlines published
2. CHANGE_NO_DATES: content changed but no deadlines found
3. ERROR: the scan failed
4. NO_CHANGE: scan completed, no changes
"""

from jinja2 import Environment, BaseLoader
import logging

logger = logging.getLogger(__name__)


class EmailTemplates:
    """
    Jinja2 template for the per-run report email.

    Example:
        >>> templates = EmailTemplates()
        >>> html = templates.render_report(
        ...     scan_date="2026-03-01 05:17 UTC",
        ...     with_dates=[...],
        ...     no_dates=[...],
        ...     errors=[...],
        ...     no_change=[...],
        ... )
    """

    REPORT_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #f4f4f4; padding: 20px; border-radius: 5px; margin-bottom: 20px; }
        .header h2 { margin: 0; color: #444; }
        h3 { margin: 25px 0 10px; padding-bottom: 5px; border-bottom: 1px solid #eee; }
        .item { padding: 12px 15px; margin: 10px 0; background: #f9f9f9; border-radius: 3px; }
        .urgent { border-left: 4px solid #dc3545; }
        .updated { border-left: 4px solid #ffc107; }
        .error { border-left: 4px solid #dc3545; background: #f8d7da; }
        .quiet { border-left: 4px solid #2196F3; }
        .deadline-date { font-weight: bold; color: #dc3545; }
        .meta { color: #777; font-size: 13px; }
        .summary { background: #e7f3ff; padding: 10px; margin-top: 8px; }
        .footer { color: #999; font-size: 12px; padding: 20px; text-align: center; border-top: 1px solid #eee; margin-top: 20px; }
        code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-family: monospace; word-break: break-all; }
        ul { padding-left: 20px; margin: 5px 0; }
        a { color: #2196F3; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>ConBOT Scan Report</h2>
            <div class="meta">{{ scan_date }} &middot; {{ total }} conference(s) scanned</div>
        </div>

        {% if with_dates %}
        <h3>🚨 Deadlines published</h3>
        {% for c in with_dates %}
        <div class="item urgent">
            <strong><a href="{{ c.url }}">{{ c.conference_name }}</a></strong>
            <ul>
            {% for d in c.deadlines %}
                <li><span class="deadline-date">{{ d.date }}</span> &ndash; {{ d.type|upper }}
                    <div class="meta">{{ d.source_text[:150]|e }}{% if d.source_text|length > 150 %}...{% endif %}
                    ({{ (d.confidence * 100)|int }}% confidence)</div></li>
            {% endfor %}
            </ul>
            {% if c.summary %}<div class="summary">{{ c.summary }}</div>{% endif %}
            <div class="meta">Now checked daily (URGENT, was {{ c.previous_watch_mode }}). Next check: {{ c.next_run_date }}</div>
        </div>
        {% endfor %}
        {% endif %}

        {% if no_dates %}
        <h3>⚠️ Website updated</h3>
        {% for c in no_dates %}
        <div class="item updated">
            <strong><a href="{{ c.url }}">{{ c.conference_name }}</a></strong>
            <div class="meta">Change type: {{ c.change_type }}. No submission dates detected yet.</div>
            {% if c.summary %}<div class="summary">{{ c.summary }}</div>{% endif %}
            <div class="meta">Watch mode: {{ c.watch_mode }} (was {{ c.previous_watch_mode }}). Next check: {{ c.next_run_date }}</div>
        </div>
        {% endfor %}
        {% endif %}

        {% if errors %}
        <h3>❌ Scan errors</h3>
        {% for c in errors %}
        <div class="item error">
            <strong><a href="{{ c.url }}">{{ c.conference_name }}</a></strong>
            <div><code>{{ c.error_message[:500]|e }}</code></div>
            <div class="meta">Failed {{ c.error_count }} time(s) in a row. It will be retried on the next run.</div>
        </div>
        {% endfor %}
        {% endif %}

        {% if no_change %}
        <h3>✓ No changes</h3>
        {% for c in no_change %}
        <div class="item quiet">
            <strong><a href="{{ c.url }}">{{ c.conference_name }}</a></strong>
            {% if c.last_known_deadlines %}
            <div class="meta">Known deadlines:
                {% for d in c.last_known_deadlines %}{{ d.date }} ({{ d.type }}){% if not loop.last %}, {% endif %}{% endfor %}</div>
            {% endif %}
            <div class="meta">Next check: {{ c.next_run_date }} ({{ c.watch_mode }})</div>
        </div>
        {% endfor %}
        {% endif %}

        <div class="footer">ConBOT - Automated Conference Monitoring</div>
    </div>
</body>
</html>"""

    def __init__(self):
        """Initialize email templates."""
        self.env = Environment(loader=BaseLoader(), autoescape=False)

    def render_report(self, **kwargs) -> str:
        """
        Render the report email.

        Args:
            **kwargs: scan_date, total, and one list of entries per section
                (with_dates, no_dates, errors, no_change)

        Returns:
            Rendered HTML email
        """
        template = self.env.from_string(self.REPORT_TEMPLATE)
        return template.render(**kwargs)
