"""
This module centralizes the configuration for the RAG News Generation system.

It includes settings for Kafka, the Congress.gov API, the database, LLM endpoints,
and the target bills to be processed.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Kafka Configuration ---
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPICS = ["query.input", "article.input", "error.output"]
KAFKA_QUERY_TOPIC = "query.input"
KAFKA_ARTICLE_TOPIC = "article.input"
KAFKA_LINK_CHECK_TOPIC = "link.check.input"
KAFKA_ARTICLE_VALIDATED_TOPIC = "article.validated.input"
KAFKA_ERROR_TOPIC = "error.output"

# --- Congress.gov API ---
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY")
CONGRESS_API_BASE_URL = "https://api.congress.gov/v3"

# --- Database Configuration ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./output/tasks.db")

# --- Target Bills ---
TARGET_BILLS = [
    {"id": "hr1", "type": "hr", "congress": 118},
    {"id": "hr5371", "type": "hr", "congress": 117},
    {"id": "hr5401", "type": "hr", "congress": 117},
    {"id": "s2296", "type": "s", "congress": 118},
    {"id": "s24", "type": "s", "congress": 118},
    {"id": "s2882", "type": "s", "congress": 117},
    {"id": "s499", "type": "s", "congress": 118},
    {"id": "sres412", "type": "sres", "congress": 118},
    {"id": "hres353", "type": "hres", "congress": 118},
    {"id": "hr1968", "type": "hr", "congress": 118},
]

# --- Questions ---
QUESTIONS = {
    1: "What does this bill do? Where is it in the process?",
    2: "What committees is this bill in?",
    3: "Who is the sponsor?",
    4: "Who cosponsored this bill? Are any of the cosponsors on the committee that the bill is in?",
    5: "Have any hearings happened on the bill? If so, what were the findings?",
    6: "Have any amendments been proposed on the bill? If so, who proposed them and what do they do?",
    7: "Have any votes happened on the bill? If so, was it a party-line vote or a bipartisan one?",
}

# --- Output ---
OUTPUT_FILE = "output/articles.json"
ANSWERS_FILE = "output/answers.json"

# LLM Configuration
LM_STUDIO_IP = "192.168.1.224"
LLM_API_BASE = f"http://{LM_STUDIO_IP}:1234"
LLM_MODEL = "gemma-3-4b-it"
EMBEDDING_API_BASE = f"http://{LM_STUDIO_IP}:1234"
EMBEDDING_MODEL = "text-embedding-embeddinggemma-300m"
