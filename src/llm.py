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


def get_all_bill_data(
    bill_id: str, bill_type: str, congress: str, api_key: str
) -> dict:
    """
    Fetches comprehensive data for a bill including details, amendments, committees, hearings, votes, and reports.
    """
    match = re.match(r"[a-zA-Z]+(\d+)", bill_id)
    if not match:
        print(f"Error: Invalid bill_id format: {bill_id}")
        return {}
    bill_number = match.group(1)

    base_url = (
        f"https://api.congress.gov/v3/bill/{congress}/{bill_type}/{bill_number}"
    )

    bill_data = get_bill_data(bill_id, bill_type, congress, api_key)
    if not bill_data or "bill" not in bill_data:
        return {}  # Stop if the main bill data failed

    amendments = _get_bill_sub_resource(base_url, api_key, "amendments")
    committees = _get_bill_sub_resource(base_url, api_key, "committees")
    hearings = _get_bill_sub_resource(base_url, api_key, "hearings")
    votes = _get_bill_sub_resource(base_url, api_key, "votes")
    reports = _get_bill_sub_resource(base_url, api_key, "reports")

    # Combine all data into one dictionary
    bill_data["bill"]["amendments"] = amendments.get("amendments", [])
    bill_data["bill"]["committees"] = committees.get("committees", [])
    bill_data["bill"]["hearings"] = hearings.get("hearings", [])
    bill_data["bill"]["votes"] = votes.get("votes", [])
    bill_data["bill"]["reports"] = reports.get("reports", [])

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
        dict: A dictionary containing the bill's data, or an empty dictionary
              if the request fails.
    """
    match = re.match(r"[a-zA-Z]+(\d+)", bill_id)
    if not match:
        print(f"Error: Invalid bill_id format: {bill_id}")
        return {}
    bill_number = match.group(1)

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
    
    Returns:
        str: The content of the article template file.
    """
    try:
        with open("./article_template.md", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print("Warning: Template file not found at ./article_template.md. Using default prompt.")
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
        
        # Bill URL
        if bill.get("congress") and bill.get("type") and bill.get("number"):
            bill_url = f"https://www.congress.gov/bill/{bill['congress']}th-congress/{bill['type'].lower()}-bill/{bill['number']}"
            bill_number_str = f"{bill['type'].upper().replace('RES', '.Res. ')}{bill['number']}"
            links.append(f"- Bill: {bill_number_str} -> {bill_url}")
        
        # Member URLs (sponsors and cosponsors)
        sponsors = bill.get("sponsors", [])
        cosponsors_data = bill.get("cosponsors", {})
        cosponsors = cosponsors_data.get("items", []) if isinstance(cosponsors_data, dict) else []
        members = sponsors + cosponsors
        for member in members:
            if member.get("fullName") and member.get("url"):
                member_url = member.get("url", "").split('?')[0]
                full_name = member.get("fullName", "")
                links.append(f"- Member: {full_name} -> {member_url}")
        
        # Committee URLs
        committees = bill.get("committees", [])
        for committee in committees:
            if committee.get("name") and committee.get("url"):
                committee_url = committee.get("url", "").split('?')[0]
                links.append(f"- Committee: {committee.get('name')} -> {committee_url}")
        
        # Amendment URLs - include multiple formats for matching
        amendments = bill.get("amendments", [])
        for amendment in amendments:
            if amendment.get("number") and amendment.get("url"):
                amendment_url = amendment.get("url", "").split('?')[0]
                amendment_number = amendment.get("number", "")
                # Include both formats: "Amendment 48" and "HAMDT 48" or "SAMDT 48"
                amendment_type = amendment.get("type", "").upper()
                if amendment_type:
                    links.append(f"- Amendment: {amendment_type} {amendment_number} -> {amendment_url}")
                links.append(f"- Amendment: Amendment {amendment_number} -> {amendment_url}")
        
        # Hearing URLs - check both hearings array and actions that mention hearings
        hearings = bill.get("hearings", [])
        if isinstance(hearings, list):
            for hearing in hearings:
                if isinstance(hearing, dict) and hearing.get("url"):
                    hearing_url = hearing.get("url", "").split('?')[0]
                    hearing_title = hearing.get("title") or hearing.get("name") or f"Hearing {hearing.get('number', '')}"
                    links.append(f"- Hearing: {hearing_title} -> {hearing_url}")
        
        # Vote URLs - check votes array and also look in actions
        votes = bill.get("votes", [])
        if isinstance(votes, list):
            for vote in votes:
                if isinstance(vote, dict) and vote.get("url"):
                    vote_url = vote.get("url", "").split('?')[0]
                    vote_desc = vote.get("description") or vote.get("title") or f"Vote {vote.get('number', '')}"
                    links.append(f"- Vote: {vote_desc} -> {vote_url}")
        
        # Report URLs - check reports array
        reports = bill.get("reports", [])
        if isinstance(reports, list):
            for report in reports:
                if isinstance(report, dict) and report.get("url"):
                    report_url = report.get("url", "").split('?')[0]
                    report_citation = report.get("citation") or report.get("number") or f"Report {report.get('number', '')}"
                    # Also include common formats like "House Report 119-199" or "H. Rept. 119-199"
                    if report.get("number"):
                        links.append(f"- Report: House Report {report.get('number')} -> {report_url}")
                        links.append(f"- Report: H. Rept. {report.get('number')} -> {report_url}")
                    links.append(f"- Report: {report_citation} -> {report_url}")
        
        if links:
            link_info = f"""

AVAILABLE HYPERLINKS:
When mentioning any of the following entities in your article, include them as inline Markdown links using the format [Entity Name](URL). 

CRITICAL RULES:
- The link text MUST match EXACTLY how you mention the entity in your text
- The link should go ON TOP OF the entity name, not next to it
- For example: If you write "Amendment HAMDT 48", use "[Amendment HAMDT 48](URL)" - match the exact text including "HAMDT"
- For bills: Use the exact format shown (e.g., "[H.R.3633](URL)" or "[S. 2587](URL)")
- For members: Use ONLY the member's name in the link text. Do NOT include party/state info in brackets inside the link. 
  Example: Write "[Rep. John Smith](URL)" NOT "[Rep. John Smith [R-TX-5](URL)]"
  If you mention party/state info, put it OUTSIDE the link: "[Rep. John Smith](URL) (R-TX-5)"
- For committees: Use the exact committee name provided. Only link committees that have URLs in the list below.

Available links:
{chr(10).join(links)}
"""
    
    prompt = f"""
You are a professional journalist writing for a publication like Politico or Punchbowl News. Based on the following questions and answers about a U.S. congressional bill, write a high-quality news-style article following the provided template structure and style guidelines.

ARTICLE TEMPLATE AND STYLE GUIDE:
{template}

QUESTIONS AND ANSWERS ABOUT THE BILL:
{formatted_answers}
{link_info}
INSTRUCTIONS:
1. Follow the template structure EXACTLY: 
   - Headline: Use ## for the headline (h2), make it tight, active, and insider-sounding - signaling motion or tension, never just describing.
   - Byline: Format as "By [Reporter Name] – [Date]" (use a generic reporter name and current date)
   - Opening Paragraph (Lede): One to two sentences capturing the action AND its Hill significance
   - Section Headers: Use **bold** formatting for ALL section headers:
     * **Immediate Context:** (or **PARAGRAPH 2: Immediate Context / Stakes**)
     * **Inside the Room:** (or **PARAGRAPH 3–4: Inside the Room**)
     * **Politics:** (or **PARAGRAPH 5: The Politics**)
     * **What's Next:** (or **PARAGRAPH 6: What's Next**)
     * **Closing Graf:** (or **CLOSING GRAF**)
   - Each section should be separated by blank lines

2. Write in the style described in the template - tight, active, insider-sounding headlines; brisk ledes with "moment + meaning"; focus on power dynamics and strategic positioning.

3. Use only the information provided in the answers. Do not make up information, quotes, or details not present in the answers.

4. If certain information is not available (e.g., no hearings, no amendments, no votes), adapt the structure accordingly but maintain the overall flow.

5. IMPORTANT: Use only standard ASCII characters. Use straight quotes (') and (") instead of curly quotes, use hyphens (-) instead of en dashes or em dashes, and avoid any unicode characters.

6. Write the article in Markdown format with proper formatting. Use **bold** for section headers, not plain text.

7. CRITICAL: When mentioning bills, members, committees, amendments, hearings, votes, or reports, use the provided URLs to create inline Markdown links. The link text should match EXACTLY how you mention the entity. For example:
   - If you write "Amendment HAMDT 48", use "[Amendment HAMDT 48](URL)" not "[Amendment 48](URL)"
   - If you write "H.R.3633", use "[H.R.3633](URL)"
   - For members: Use ONLY the member's name in the link text. Do NOT include party/state info in brackets inside the link.
     CORRECT: "[Rep. John Smith](URL)" or "[Rep. John Smith](URL) (R-TX-5)"
     WRONG: "[Rep. John Smith [R-TX-5](URL)]"
   - Place links directly on top of the entity name, not next to it (e.g., "[H.R.3633](URL)" not "H.R.3633 (link)")
   - Only link entities that have URLs provided in the AVAILABLE HYPERLINKS section below

8. Ensure the article flows naturally and reads like a professional Hill publication piece.
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
