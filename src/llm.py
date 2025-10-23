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
from .config import (
    LLM_API_BASE,
    LLM_MODEL,
    EMBEDDING_API_BASE,
    EMBEDDING_MODEL,
)
from .metrics import metrics


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


def generate_article_from_answers(answers: dict) -> str:
    """
    Generates a news-style article from a set of questions and answers.

    This function constructs a prompt with the collected answers and asks the
    local LLM to write a cohesive, objective news article in Markdown format.

    Args:
        answers (dict): A dictionary of answers, keyed by question ID.

    Returns:
        str: The LLM-generated news article in Markdown format.
    """
    print("LLM: Generating article from answers.")

    formatted_answers = "\n".join([f"- {q_id}: {answer}" for q_id, answer in answers.items()])
    prompt = f"""
    Based on the following questions and answers about a U.S. congressional bill, write a short, high-quality news-style article in Markdown format.
    - The article should be objective and factual.
    - Incorporate the information from the answers into a cohesive narrative.
    - Do not make up information.
    - Start with a headline.

    Questions and Answers:
    {formatted_answers}
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
        return response.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.RequestException as e:
        print(f"Error calling LLM API for article generation: {e}")
        return "Error: Could not generate article."


def add_hyperlinks(text: str, bill_data: dict) -> str:
    """
    Adds relevant Congress.gov hyperlinks to the article text.

    This function searches the text for mentions of the bill, its sponsor, and
    cosponsors, and replaces them with Markdown hyperlinks pointing to their
    respective pages on Congress.gov.

    Args:
        text (str): The article text to which hyperlinks will be added.
        bill_data (dict): The bill's data, used to find URLs for members.

    Returns:
        str: The article text with embedded Markdown hyperlinks.
    """
    print("System: Adding hyperlinks to text.")
    bill = bill_data.get("bill", {})
    if not bill:
        return text

    # Link for the bill itself
    if bill.get("congress") and bill.get("type") and bill.get("number"):
        bill_url = f"https://www.congress.gov/bill/{bill['congress']}th-congress/{bill['type'].lower()}-bill/{bill['number']}"
        text = text.replace(f"{bill['type']}{bill['number']}", f"[{bill['type']}{bill['number']}]({bill_url})")

    # Links for sponsors and cosponsors
    sponsors = bill.get("sponsors", [])
    cosponsors_data = bill.get("cosponsors", {})
    cosponsors = cosponsors_data.get("items", []) if isinstance(cosponsors_data, dict) else []
    members = sponsors + cosponsors
    for member in members:
        if member.get("fullName"):
            member_url = member.get("url", "").split('?')[0]  # Get base URL
            if member_url:
                 text = text.replace(member.get("fullName"), f"[{member.get('fullName')}]({member_url})")

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
