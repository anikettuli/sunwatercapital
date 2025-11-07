"""
Handles interactions with the Congress.gov API and the local LLM.

This module provides functions for fetching bill data, generating answers to
specific questions using retrieval-augmented generation (RAG), creating news
articles from those answers, and adding relevant hyperlinks to the content.
"""
import re
import requests
import json
import time
from unidecode import unidecode
from .config import (
    LLM_API_BASE,
    LLM_MODEL,
    EMBEDDING_API_BASE,
    EMBEDDING_MODEL,
)
from .metrics import metrics


def normalize_unicode_to_ascii(text: str) -> str:
    """
    Normalizes unicode characters to their ASCII equivalents.
    
    Uses the unidecode library to convert unicode characters (like smart quotes,
    em dashes, etc.) to their ASCII equivalents for proper Markdown rendering.
    
    Args:
        text (str): The text containing unicode characters.
        
    Returns:
        str: The text with unicode characters replaced by ASCII equivalents.
    """
    return unidecode(text)


def _get_bill_sub_resource(
    base_url: str, api_key: str, sub_resource: str
) -> dict:
    """A helper function to fetch sub-resources for a bill."""
    url = f"{base_url}/{sub_resource}?api_key={api_key}"
    try:
        start_time = time.time()
        response = requests.get(url)
        response.raise_for_status()
        metrics.add_congress_api_time(time.time() - start_time)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {sub_resource} data from {url}: {e}")
        return {}


def _extract_bill_number(bill_id: str) -> str:
    """Extracts bill number from bill_id (e.g., 'hr4313' -> '4313')."""
    match = re.match(r"[a-zA-Z]+(\d+)", bill_id)
    if not match:
        raise ValueError(f"Invalid bill_id format: {bill_id}")
    return match.group(1)


def get_all_bill_data(
    bill_id: str, bill_type: str, congress: str, api_key: str
) -> dict:
    """
    Fetches comprehensive data for a bill including details, amendments, committees, hearings, votes, and reports.
    """
    try:
        bill_number = _extract_bill_number(bill_id)
    except ValueError as e:
        print(f"Error: {e}")
        return {}

    base_url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}"
    bill_data = get_bill_data(bill_id, bill_type, congress, api_key)
    
    if not bill_data or "bill" not in bill_data:
        return {}

    # Fetch all sub-resources
    sub_resources = ["amendments", "committees", "hearings", "votes", "reports"]
    for resource in sub_resources:
        resource_data = _get_bill_sub_resource(base_url, api_key, resource)
        bill_data["bill"][resource] = resource_data.get(resource, [])

    return bill_data


def get_bill_data(bill_id: str, bill_type: str, congress: str, api_key: str) -> dict:
    """
    Fetches detailed data for a specific bill from the Congress.gov API.

    Args:
        bill_id (str): The identifier of the bill (e.g., "hr1").
        bill_type (str): The type of the bill (e.g., "hr", "s").
        congress (str): The congressional session (e.g., "118").
        api_key (str): The API key for accessing the Congress.gov API.

    Returns:
        dict: A dictionary containing the bill's data, or an empty dictionary if the request fails.
    """
    try:
        bill_number = _extract_bill_number(bill_id)
    except ValueError as e:
        print(f"Error: {e}")
        return {}

    url = f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}?api_key={api_key}"

    try:
        start_time = time.time()
        response = requests.get(url)
        response.raise_for_status()
        metrics.add_congress_api_time(time.time() - start_time)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching API data from {url}: {e}")
        return {}


def get_answer_from_bill(bill_data: dict, question: str) -> str:
    """
    Answers a specific question about a bill using data and an LLM.

    This function constructs a prompt that includes the bill's JSON data and
    the question, then sends it to the local LLM to generate a factual answer.

    Args:
        bill_data (dict): The bill's data fetched from the Congress.gov API.
        question (str): The question to be answered.

    Returns:
        str: The LLM-generated answer to the question.
    """
    print(f"LLM: Answering question '{question}'")

    bill_text = json.dumps(bill_data.get("bill", {}))

    prompt = f"""
    Based on the following JSON data for a legislative bill, please provide a concise and factual answer to the question.

    Bill Data:
    {bill_text}

    Question: {question}
    """

    try:
        start_time = time.time()
        response = requests.post(
            f"{LLM_API_BASE}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
        )
        response.raise_for_status()
        metrics.add_llm_api_time(time.time() - start_time)
        return response.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.RequestException as e:
        print(f"Error calling LLM API for answering question: {e}")
        return f"Error generating answer: Could not connect to LLM."


def _load_article_template() -> str:
    """
    Loads the article template from the template file.
    
    The app runs from /app (WORKDIR in Dockerfile), and the template is at
    src/article_template.md relative to that directory.
    
    Returns:
        str: The content of the article template file.
    """
    template_path = "src/article_template.md"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: Template file not found at {template_path}. Using default prompt.")
        return ""
    except Exception as e:
        print(f"Warning: Error reading template file at {template_path}: {e}. Using default prompt.")
        return ""


def generate_article_from_answers(answers: dict, bill_data: dict = None) -> str:
    """
    Generates a news-style article from a set of questions and answers.

    This function constructs a prompt with the collected answers and the article
    template, then asks the local LLM to write a cohesive, objective news article
    following the Politico/Punchbowl style guide in Markdown format.

    Args:
        answers (dict): A dictionary of answers, keyed by question ID.
        bill_data (dict): Optional bill data containing URLs for hyperlinks.

    Returns:
        str: The LLM-generated news article in Markdown format.
    """
    print("LLM: Generating article from answers.")

    # Load the article template
    template = _load_article_template()
    
    formatted_answers = "\n".join([f"- Q{q_id}: {answer}" for q_id, answer in answers.items()])
    
    # Extract URLs for hyperlinks if bill_data is provided
    link_info = ""
    if bill_data:
        bill = bill_data.get("bill", {})
        links = []
        
        # Helper to clean URL (remove query params)
        def clean_url(url: str) -> str:
            return url.split('?')[0] if url else ""
        
        # Bill URL
        if bill.get("congress") and bill.get("type") and bill.get("number"):
            bill_url = f"https://www.congress.gov/bill/{bill['congress']}th-congress/{bill['type'].lower()}-bill/{bill['number']}"
            bill_number_str = f"{bill['type'].upper().replace('RES', '.Res. ')}{bill['number']}"
            links.append(f"- Bill: {bill_number_str} -> {bill_url}")
        
        # Member URLs (sponsors and cosponsors)
        sponsors = bill.get("sponsors", [])
        cosponsors = bill.get("cosponsors", {}).get("items", []) if isinstance(bill.get("cosponsors"), dict) else []
        for member in sponsors + cosponsors:
            if member.get("fullName") and member.get("url"):
                links.append(f"- Member: {member.get('fullName')} -> {clean_url(member.get('url'))}")
        
        # Committee URLs
        for committee in bill.get("committees", []):
            if committee.get("name") and committee.get("url"):
                links.append(f"- Committee: {committee.get('name')} -> {clean_url(committee.get('url'))}")
        
        # Amendment URLs - include multiple formats
        for amendment in bill.get("amendments", []):
            if amendment.get("number") and amendment.get("url"):
                url = clean_url(amendment.get("url"))
                number = amendment.get("number")
                amendment_type = amendment.get("type", "").upper()
                if amendment_type:
                    links.append(f"- Amendment: {amendment_type} {number} -> {url}")
                links.append(f"- Amendment: Amendment {number} -> {url}")
        
        # Hearing, Vote, and Report URLs - similar pattern
        for hearing in bill.get("hearings", []):
            if isinstance(hearing, dict) and hearing.get("url"):
                title = hearing.get("title") or hearing.get("name") or f"Hearing {hearing.get('number', '')}"
                links.append(f"- Hearing: {title} -> {clean_url(hearing.get('url'))}")
        
        for vote in bill.get("votes", []):
            if isinstance(vote, dict) and vote.get("url"):
                desc = vote.get("description") or vote.get("title") or f"Vote {vote.get('number', '')}"
                links.append(f"- Vote: {desc} -> {clean_url(vote.get('url'))}")
        
        for report in bill.get("reports", []):
            if isinstance(report, dict) and report.get("url"):
                url = clean_url(report.get("url"))
                citation = report.get("citation") or report.get("number") or f"Report {report.get('number', '')}"
                links.append(f"- Report: {citation} -> {url}")
                if report.get("number"):
                    links.append(f"- Report: House Report {report.get('number')} -> {url}")
                    links.append(f"- Report: H. Rept. {report.get('number')} -> {url}")
        
        if links:
            link_info = f"""

AVAILABLE HYPERLINKS:
When mentioning any of the following entities in your article, include them as inline Markdown links using the format [Entity Name](URL). 

CRITICAL RULES:
- ONLY create links for entities that have URLs listed below. DO NOT use brackets [like this] without a URL - if there's no URL available, just write the entity name normally without brackets.
- The link text MUST match EXACTLY how you mention the entity in your text
- The link should go ON TOP OF the entity name, not next to it
- For example: If you write "Amendment HAMDT 48", use "[Amendment HAMDT 48](URL)" - match the exact text including "HAMDT"
- For bills: Use the exact format shown (e.g., "[H.R.3633](URL)" or "[S. 2587](URL)") ONLY if a URL is provided below
- For members: Use ONLY the member's name in the link text. Do NOT include party/state info in brackets inside the link. 
  Example: Write "[Rep. John Smith](URL)" NOT "[Rep. John Smith [R-TX-5](URL)]"
  If you mention party/state info, put it OUTSIDE the link: "[Rep. John Smith](URL) (R-TX-5)"
- For committees: Use the exact committee name provided. Only link committees that have URLs in the list below.
- NEVER write brackets without URLs. If an entity is not in the list below, write it normally without brackets.

Available links:
{chr(10).join(links)}
"""
        else:
            link_info = """

HYPERLINK INSTRUCTIONS:
- NO URLs are available for this bill. DO NOT use brackets [like this] anywhere in your article.
- Write all entity names normally without brackets (e.g., write "H.R.3633" not "[H.R.3633]")
- Write member names normally (e.g., "Rep. John Smith" not "[Rep. John Smith]")
- Write committee names normally (e.g., "Ways and Means Committee" not "[Ways and Means Committee]")
- NEVER create brackets without URLs - this creates broken links and poor formatting.
"""
    
    prompt = f"""
You are a professional journalist writing for Politico or Punchbowl News. Write a news article about a congressional bill using ONLY the information provided in the Q&A section below.

QUESTIONS AND ANSWERS ABOUT THE BILL:
{formatted_answers}
{link_info}

ARTICLE STRUCTURE:
Write a news article with the following structure:

1. HEADLINE (use ### markdown)
   - Make it tight, active, and insider-sounding
   - Signal motion or tension, never just describe
   - Example format: "Committee Advances [Bill Topic] Amid [Political Context]"

2. BYLINE
   - Format: "By [Reporter Name] - [Date]"
   - Use a generic reporter name and the current date

3. OPENING PARAGRAPH (Lede)
   - One to two sentences capturing the action AND its Hill significance
   - Include: what happened, when, which committee/chamber, why it matters

4. IMMEDIATE CONTEXT
   - Why this matters right now
   - Tie to timing, leadership goals, or broader negotiations

5. INSIDE THE ROOM (if hearings/markups occurred)
   - Describe markup/hearing dynamics
   - Mention amendments if any were proposed
   - Include vote tallies if available
   - Use transitions like "During the markup..." or "The committee considered..."

6. THE POLITICS
   - Explain power dynamics or strategic positioning
   - How this fits the larger Hill story
   - Bipartisan dynamics or party-line tensions

7. WHAT'S NEXT
   - What happens next procedurally
   - Floor votes, companion bills, or next committee action

8. CLOSING GRAF
   - Forward-looking or reflective note
   - Quote from sponsor/key member if mentioned in answers
   - Hint at bigger stakes or challenges ahead

CRITICAL RULES:
- Use ONLY information from the Q&A answers above. If information isn't in the answers, DON'T include it.
- If the answers say "no amendments" or "no votes" - then DON'T invent any.
- If the answers say "no hearings" - skip or minimize the "Inside the Room" section.
- DO NOT invent vote tallies, amendment details, or quotes not in the answers.
- When answers are vague about votes (e.g., "placed on calendar"), DON'T fabricate specific vote counts.
- Use straight quotes (') and (") - no curly quotes.
- Use hyphens (-) - no em dashes or en dashes.
- Write in Markdown format.
- Include hyperlinks using the URLs provided in the AVAILABLE HYPERLINKS section above.
- Link format: [Entity Name](URL) - place links directly on entity names, not next to them.

STYLE:
- Tight, active writing
- Insider tone focusing on process and power dynamics
- Brisk ledes with "moment + meaning"
- Congressional jargon when appropriate (markup, floor action, etc.)
"""

    try:
        start_time = time.time()
        response = requests.post(
            f"{LLM_API_BASE}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
        )
        response.raise_for_status()
        metrics.add_llm_api_time(time.time() - start_time)
        article_text = response.json()["choices"][0]["message"]["content"].strip()
        # Normalize unicode characters to ASCII
        article_text = normalize_unicode_to_ascii(article_text)
        return article_text
    except requests.exceptions.RequestException as e:
        print(f"Error calling LLM API for article generation: {e}")
        return "Error: Could not generate article."


def add_hyperlinks(text: str, bill_data: dict) -> str:
    """
    Legacy function - hyperlinks are now generated directly by the LLM.
    
    This function is kept for backward compatibility but no longer performs
    any operations since links are included in the LLM-generated article.
    
    Args:
        text (str): The article text (already contains links from LLM).
        bill_data (dict): Unused, kept for compatibility.
        
    Returns:
        str: The article text unchanged.
    """
    # Links are now generated by the LLM directly, so this is a no-op
    return text


def get_embedding(text: str) -> list[float]:
    """
    Generates an embedding for a given text using the local embedding model.

    Args:
        text (str): The text to be embedded.

    Returns:
        list[float]: A list of floats representing the text's embedding, or an
                     empty list if the request fails.
    """
    try:
        start_time = time.time()
        response = requests.post(
            f"{EMBEDDING_API_BASE}/v1/embeddings",
            headers={"Content-Type": "application/json"},
            json={"model": EMBEDDING_MODEL, "input": [text]},
        )
        response.raise_for_status()
        metrics.add_llm_api_time(time.time() - start_time)
        return response.json()["data"][0]["embedding"]
    except requests.exceptions.RequestException as e:
        print(f"Error calling Embedding API: {e}")
        return []
