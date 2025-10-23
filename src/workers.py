"""
This module defines the worker threads that form the core of the processing
pipeline. Each worker is a long-running thread that consumes messages from a
specific Kafka topic, performs a task, and may produce messages to another
topic for the next stage of processing.
"""
import json
import threading

from kafka import KafkaConsumer, KafkaProducer
from . import config
from .config import QUESTIONS
from .db_manager import db_manager
from .llm import get_bill_data, get_answer_from_bill, generate_article_from_answers, add_hyperlinks
from .metrics import file_write_lock


class QueryWorker(threading.Thread):
    """
    Consumes tasks from the query topic to answer questions about bills.

    For each task, it fetches data from the Congress.gov API, uses the LLM to
    generate an answer to a specific question, and stores the answer in the
    database. Once all questions for a bill are answered, it dispatches a task
    to the article generation topic.
    """

    def __init__(self):
        """Initializes the QueryWorker, setting up Kafka consumer and producer."""
        super().__init__()
        self.daemon = True
        self.consumer = KafkaConsumer(
            config.KAFKA_QUERY_TOPIC,
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            group_id="query-workers",
            auto_offset_reset="earliest",
        )
        self.producer = KafkaProducer(
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        self.db_manager = db_manager
        self.dispatched_bills = set()

    def run(self):
        """
        The main loop for the worker.

        Continuously fetches tasks from the query topic and processes them.
        """
        print(f"--- Query Worker Started ---")
        for message in self.consumer:
            data = message.value
            bill_id = data["bill_id"]
            bill_type = data["bill_type"]
            congress = data["congress"]
            question_id = data["question_id"]
            question = QUESTIONS.get(question_id)

            print(f"\n[Query Worker] Received task for Bill {bill_id.upper()}, Q{question_id}")

            print(f"[Query Worker] Making API call to Congress.gov for {bill_id.upper()}")
            bill_data = get_bill_data(bill_id, bill_type, congress, config.CONGRESS_API_KEY)

            if not bill_data:
                answer = "Could not retrieve bill data."
                print(f"[Query Worker] Failed to retrieve data for {bill_id.upper()}")
            else:
                print(f"[Query Worker] Sending to LLM for Q{question_id}: '{question}'")
                answer = get_answer_from_bill(bill_data, question)

            self.db_manager.store_answer(bill_id, question_id, question, answer)
            self.db_manager.mark_answer_complete(bill_id, question_id)
            print(f"[Query Worker] Stored answer for {bill_id.upper()}, Q{question_id}")

            if self.db_manager.are_all_questions_answered(bill_id):
                if bill_id not in self.dispatched_bills:
                    print(f"\n[Query Worker] All questions for {bill_id.upper()} are answered. Triggering article generation.")
                    self.producer.send(
                        config.KAFKA_ARTICLE_TOPIC,
                        {"bill_id": bill_id, "bill_type": bill_type, "congress": congress},
                    )
                    self.dispatched_bills.add(bill_id)
                    self.save_answers_to_file(bill_id)

    def save_answers_to_file(self, bill_id: str):
        """
        Retrieves all answers for a bill and saves them to a JSON file.

        This method is designed to be thread-safe.

        Args:
            bill_id (str): The ID of the bill whose answers are to be saved.
        """
        answers = self.db_manager.get_answers_for_bill(bill_id)
        output_data = {"bill_id": bill_id, "answers": answers}

        with file_write_lock:
            try:
                with open(config.ANSWERS_FILE, "r+") as f:
                    all_answers = json.load(f)
                    all_answers.append(output_data)
                    f.seek(0)
                    json.dump(all_answers, f, indent=4)
            except (FileNotFoundError, json.JSONDecodeError):
                with open(config.ANSWERS_FILE, "w") as f:
                    json.dump([output_data], f, indent=4)
        print(f"[Query Worker] Saved all answers for {bill_id.upper()} to {config.ANSWERS_FILE}")


class ArticleWorker(threading.Thread):
    """
    Consumes tasks from the article topic to generate news articles.

    For each task, it retrieves all the stored answers for a bill from the
    database, uses the LLM to generate a cohesive news article, adds relevant
    hyperlinks, and dispatches the article for link checking.
    """

    def __init__(self):
        """Initializes the ArticleWorker, setting up Kafka consumer/producer."""
        super().__init__()
        self.daemon = True
        self.consumer = KafkaConsumer(
            config.KAFKA_ARTICLE_TOPIC,
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            group_id="article-workers",
            auto_offset_reset="earliest",
        )
        self.producer = KafkaProducer(
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        self.db_manager = db_manager

    def run(self):
        """
        The main loop for the worker.

        Continuously fetches tasks from the article topic and processes them.
        """
        print(f"--- Article Worker Started ---")
        for message in self.consumer:
            data = message.value
            bill_id = data["bill_id"]
            bill_type = data["bill_type"]
            congress = data["congress"]
            print(f"\n[Article Worker] Received task for Bill {bill_id.upper()}")

            print(f"[Article Worker] Retrieving all answers for {bill_id.upper()} from database.")
            answers = self.db_manager.get_answers_for_bill(bill_id)

            print(f"[Article Worker] Retrieving full bill data for {bill_id.upper()}.")
            bill_data = get_bill_data(bill_id, bill_type, congress, config.CONGRESS_API_KEY)

            print(f"[Article Worker] Sending to LLM to generate article for {bill_id.upper()}.")
            article_text = generate_article_from_answers(answers)

            print(f"[Article Worker] Adding hyperlinks for {bill_id.upper()}.")
            article_text = add_hyperlinks(article_text, bill_data)

            self.producer.send(
                config.KAFKA_LINK_CHECK_TOPIC,
                {
                    "bill_id": bill_id,
                    "article_text": article_text,
                    "bill_data": bill_data,
                },
            )


class LinkCheckWorker(threading.Thread):
    """
    Consumes generated articles to validate the hyperlinks within them.

    For each article, it extracts all URLs and sends HEAD requests to check
    their validity (i.e., they return an HTTP 200 status). It then dispatches
    the validated article to the final processing stage.
    """

    def __init__(self):
        """Initializes the LinkCheckWorker, setting up Kafka consumer/producer."""
        super().__init__()
        self.daemon = True
        self.consumer = KafkaConsumer(
            config.KAFKA_LINK_CHECK_TOPIC,
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            group_id="link-check-workers",
            auto_offset_reset="earliest",
        )
        self.producer = KafkaProducer(
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

    def run(self):
        """
        The main loop for the worker.

        Continuously fetches tasks from the link check topic and processes them.
        """
        print(f"--- Link Check Worker Started ---")
        for message in self.consumer:
            data = message.value
            bill_id = data["bill_id"]
            article_text = data["article_text"]
            bill_data = data["bill_data"]
            print(f"\n[Link Check Worker] Received task for Bill {bill_id.upper()}")

            validated_text, broken_links = self.validate_and_correct_links(article_text)

            if broken_links:
                print(f"[Link Check Worker] Found {len(broken_links)} broken links for bill {bill_id.upper()}.")
            else:
                print(f"[Link Check Worker] All links are valid for {bill_id.upper()}.")

            self.producer.send(
                config.KAFKA_ARTICLE_VALIDATED_TOPIC,
                {
                    "bill_id": bill_id,
                    "article_text": validated_text,
                    "bill_data": bill_data,
                },
            )

    def validate_and_correct_links(self, text: str) -> tuple[str, list[str]]:
        """
        Validates all hyperlinks in a given text.

        Args:
            text (str): The text containing hyperlinks to validate.

        Returns:
            tuple[str, list[str]]: A tuple containing the original text and a
                                   list of any URLs that were found to be broken.
        """
        import re
        import requests

        urls = re.findall(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+", text)
        broken_links = []
        for url in urls:
            try:
                response = requests.head(url, allow_redirects=True, timeout=5)
                if response.status_code != 200:
                    broken_links.append(url)
            except requests.RequestException:
                broken_links.append(url)

        return text, broken_links


class ValidatedArticleWorker(threading.Thread):
    """
    Consumes validated articles and writes them to the final output file.

    This is the final stage of the pipeline. This worker takes the validated
    article, extracts the required metadata, formats it into the final JSON
    structure, and appends it to the `articles.json` output file.
    """

    def __init__(self):
        """Initializes the worker, setting up the Kafka consumer."""
        super().__init__()
        self.daemon = True
        self.consumer = KafkaConsumer(
            config.KAFKA_ARTICLE_VALIDATED_TOPIC,
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            group_id="validated-article-workers",
            auto_offset_reset="earliest",
        )
        self.db_manager = db_manager

    def run(self):
        """
        The main loop for the worker.

        Continuously fetches tasks from the validated article topic and writes
        the final output.
        """
        print(f"--- Validated Article Worker Started ---")
        for message in self.consumer:
            data = message.value
            bill_id = data["bill_id"]
            article_text = data["article_text"]
            bill_data = data["bill_data"]
            print(f"\n[Validated Article Worker] Received task for Bill {bill_id.upper()}")

            bill_title = bill_data.get("bill", {}).get("title", "N/A")
            sponsor_info = bill_data.get("bill", {}).get("sponsors", [{}])[0]
            sponsor_bioguide_id = sponsor_info.get("bioguideId", "N/A")
            committees_data = bill_data.get("bill", {}).get("committees", {}).get("items", [])
            committee_ids = [c.get("systemCode") for c in committees_data if c.get("systemCode")]

            output_data = {
                "bill_id": bill_id,
                "bill_title": bill_title,
                "sponsor_bioguide_id": sponsor_bioguide_id,
                "bill_committee_ids": committee_ids,
                "article_content": article_text,
            }

            output_file = "output/articles.json"
            try:
                with open(output_file, "r+") as f:
                    try:
                        all_articles = json.load(f)
                    except json.JSONDecodeError:
                        all_articles = []
                    all_articles.append(output_data)
                    f.seek(0)
                    json.dump(all_articles, f, indent=4)
            except FileNotFoundError:
                with open(output_file, "w") as f:
                    json.dump([output_data], f, indent=4)

            print(f"[Validated Article Worker] Successfully wrote final article for {bill_id.upper()} to {output_file}")
