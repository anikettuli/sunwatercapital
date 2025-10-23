"""
The main entrypoint for the RAG News Generation application.

This script orchestrates the entire workflow, from initialization to completion.
It sets up Kafka topics and the database, starts the worker threads, dispatches
the initial tasks, and monitors for the completion of all articles before
shutting down.
"""
import time
import json
import os

from . import config, kafka_manager, db_manager
from .workers import (
    QueryWorker,
    ArticleWorker,
    LinkCheckWorker,
    ValidatedArticleWorker,
)
from .metrics import metrics


def main():
    """
    Main controller for the RAG News Generation system.

    This function orchestrates the entire process:
    1.  Clears previous output files and ensures the output directory exists.
    2.  Initializes all necessary Kafka topics.
    3.  Initializes the database connection and schema.
    4.  Starts all worker threads (Query, Article, LinkCheck, ValidatedArticle).
    5.  Dispatches the initial set of query tasks to Kafka for each target bill.
    6.  Enters a monitoring loop, checking for the final output file to determine
        when all articles have been successfully generated.
    7.  Prints the total processing time and exits.
    """
    app_start_time = time.time()
    print("--- Starting RAG News Generation System ---")

    output_dir = os.path.dirname(config.OUTPUT_FILE)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    if os.path.exists(config.OUTPUT_FILE):
        os.remove(config.OUTPUT_FILE)
    if os.path.exists(config.ANSWERS_FILE):
        os.remove(config.ANSWERS_FILE)
    print(f"Cleared output files.")

    print("Initializing Kafka topics...")
    kafka_manager.create_kafka_topics()

    print("Initializing database...")
    _ = db_manager  # Ensures the singleton is initialized

    print("Starting worker threads...")
    num_query_workers = 4
    num_article_workers = 2

    worker_threads = []
    for _ in range(num_query_workers):
        worker_threads.append(QueryWorker())
    for _ in range(num_article_workers):
        worker_threads.append(ArticleWorker())

    worker_threads.extend([
        LinkCheckWorker(),
        ValidatedArticleWorker()
    ])

    for worker in worker_threads:
        worker.start()

    print("\n--- Dispatching Tasks ---")
    producer = kafka_manager.get_kafka_producer()

    for bill in config.TARGET_BILLS:
        print(f"\nGenerating tasks for bill: {bill['id'].upper()}")
        for q_id in config.QUESTIONS.keys():
            task_message = {
                "bill_id": bill["id"],
                "bill_type": bill["type"],
                "congress": bill["congress"],
                "question_id": q_id,
            }
            producer.send(config.KAFKA_QUERY_TOPIC, task_message)
            print(f"  - Dispatched task for Q{q_id}")

    producer.flush()
    print("\nAll initial tasks have been dispatched.")

    while True:
        try:
            with open(config.OUTPUT_FILE, 'r') as f:
                articles = json.load(f)
                if len(articles) == len(config.TARGET_BILLS):
                    print("\n--- All 10 articles generated! ---")
                    break
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        time.sleep(0.5)

    end_time = time.time()
    total_time = end_time - app_start_time
    print(f"Total application processing time: {total_time:.2f} seconds.")
    print(f"  - Time spent on Congress.gov API calls: {metrics.congress_api_time:.2f} seconds.")
    print(f"  - Time spent on LLM API calls: {metrics.llm_api_time:.2f} seconds.")
    print(f"Output written to {config.OUTPUT_FILE}")


if __name__ == "__main__":
    main()
