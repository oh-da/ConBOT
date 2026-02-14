"""
LLM prompt templates for conference content analysis.

Provides structured prompts for OpenAI GPT to:
- Summarize content changes
- Extract deadline information
- Classify change significance
"""

SYSTEM_PROMPT = """You are an AI assistant specializing in analyzing academic and industry conference websites.

Your task is to analyze changes detected on conference websites and extract relevant information about Call for Papers (CFP), submission deadlines, and important dates.

Focus on:
- Conference submission deadlines (abstract, paper, poster)
- Registration deadlines
- Event dates
- Changes to CFP requirements or procedures

Be concise, factual, and highlight actionable information for researchers who need to submit papers."""

CHANGE_SUMMARY_PROMPT = """Analyze the following conference website content changes and provide a structured summary.

Conference: {conference_name}

Changed Content Snippets:
{changed_snippets}

Relevant Keywords Found:
{relevant_keywords}

Deadlines Already Extracted:
{extracted_deadlines}

Provide a JSON response with:
{{
    "summary": "2-4 sentence summary of what changed",
    "relevance_score": 0.0-1.0 (how important is this change?),
    "categories": ["CFP", "Dates", "Registration", "Program", "Other"],
    "key_changes": ["specific change 1", "specific change 2", ...],
    "potential_dates": [
        {{
            "date_text": "text mentioning a date",
            "context": "what this date is for",
            "confidence": "low|medium|high"
        }}
    ]
}}

Important:
- If no significant changes, set relevance_score < 0.3
- Only include potential_dates if you see date-like text that wasn't already extracted
- Be concise and factual
- Categories should be array of applicable types"""

NO_DATES_ANALYSIS_PROMPT = """The conference website changed, but no specific deadlines were automatically extracted.

Conference: {conference_name}

Content Snippets:
{snippets}

Analyze and provide JSON response:
{{
    "summary": "What changed on the website",
    "is_cfp_related": true/false,
    "urgency": "low|medium|high",
    "recommendations": ["action item 1", "action item 2"],
    "watch_closely": true/false (should we monitor more frequently?)
}}

Focus on whether this indicates an upcoming CFP announcement."""

CLASSIFICATION_PROMPT = """Classify this conference website content.

Content:
{content}

Provide JSON response:
{{
    "is_cfp": true/false (is this a Call for Papers?),
    "submission_types": ["abstracts", "papers", "posters", "workshops"],
    "conference_theme": "brief description of conference focus",
    "estimated_date_range": "when the conference likely occurs",
    "confidence": 0.0-1.0
}}"""


def format_change_summary_prompt(
    conference_name: str,
    changed_snippets: list[str],
    relevant_keywords: list[str],
    extracted_deadlines: list[dict]
) -> str:
    """
    Format the change summary prompt with actual data.

    Args:
        conference_name: Name of the conference
        changed_snippets: List of changed text snippets
        relevant_keywords: Keywords found in changes
        extracted_deadlines: Already extracted deadline information

    Returns:
        Formatted prompt string

    Example:
        >>> prompt = format_change_summary_prompt(
        ...     "UITP Summit",
        ...     ["Call for papers now open"],
        ...     ["call for papers", "deadline"],
        ...     [{"date": "2026-03-15", "type": "abstract"}]
        ... )
    """
    # Format snippets
    snippets_text = "\n".join(f"- {snippet}" for snippet in changed_snippets[:20])
    if not snippets_text:
        snippets_text = "(No specific snippets available)"

    # Format keywords
    keywords_text = ", ".join(relevant_keywords[:10])
    if not keywords_text:
        keywords_text = "(No keywords matched)"

    # Format deadlines
    if extracted_deadlines:
        deadlines_text = "\n".join(
            f"- {dl.get('date', 'N/A')} ({dl.get('type', 'general')}): {dl.get('source_text', '')[:100]}"
            for dl in extracted_deadlines[:5]
        )
    else:
        deadlines_text = "None extracted yet"

    return CHANGE_SUMMARY_PROMPT.format(
        conference_name=conference_name,
        changed_snippets=snippets_text,
        relevant_keywords=keywords_text,
        extracted_deadlines=deadlines_text
    )


def format_no_dates_prompt(
    conference_name: str,
    snippets: list[str]
) -> str:
    """
    Format the no-dates analysis prompt.

    Args:
        conference_name: Name of the conference
        snippets: Content snippets showing changes

    Returns:
        Formatted prompt string
    """
    snippets_text = "\n".join(f"- {snippet}" for snippet in snippets[:15])
    if not snippets_text:
        snippets_text = "(No specific content available)"

    return NO_DATES_ANALYSIS_PROMPT.format(
        conference_name=conference_name,
        snippets=snippets_text
    )


def format_classification_prompt(content: str, max_length: int = 4000) -> str:
    """
    Format the classification prompt.

    Args:
        content: Conference content to classify
        max_length: Maximum content length (for token limits)

    Returns:
        Formatted prompt string
    """
    # Truncate if too long
    if len(content) > max_length:
        content = content[:max_length] + "... (truncated)"

    return CLASSIFICATION_PROMPT.format(content=content)
