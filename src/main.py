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

from . import config, kafka_manager
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

    # Ensure output directory exists
    output_dir = os.path.dirname(config.OUTPUT_FILE)
    os.makedirs(output_dir, exist_ok=True)
    
    # Clear previous output files
    for file_path in [config.OUTPUT_FILE, config.ANSWERS_FILE]:
        if os.path.exists(file_path):
            os.remove(file_path)
    
    # Clear database
    db_path = config.DATABASE_URL.split("///")[-1]
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Removed existing database file at {db_path}.")

    print("Cleared output files.")

    print("Initializing Kafka topics...")
    kafka_manager.create_kafka_topics()

    print("Initializing database...")
    from . import db_manager  # Import here to ensure it runs after DB deletion
    from .workers import (
        QueryWorker,
        ArticleWorker,
        LinkCheckWorker,
        ValidatedArticleWorker,
    )
    _ = db_manager  # Ensures the singleton is initialized

    print("Starting worker threads...")
    num_workers = len(config.TARGET_BILLS)
    print(f"  - Query workers: {num_workers}")
    print(f"  - Article workers: {num_workers}")

    # Create and start all worker threads
    worker_threads = (
        [QueryWorker() for _ in range(num_workers)] +
        [ArticleWorker() for _ in range(num_workers)] +
        [LinkCheckWorker(), ValidatedArticleWorker()]
    )
    
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

    # Wait for all articles to be generated
    while True:
        try:
            with open(config.OUTPUT_FILE, 'r') as f:
                articles = json.load(f)
                if len(articles) >= len(config.TARGET_BILLS):
                    print(f"\n--- All {len(config.TARGET_BILLS)} articles generated! ---")
                    break
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(0.5)

    end_time = time.time()
    total_time = end_time - app_start_time
    print(f"\n{'='*60}", flush=True)
    print(f"PERFORMANCE METRICS", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"Total application processing time: {total_time:.2f} seconds.", flush=True)
    print(f"  - Time spent on Congress.gov API calls: {metrics.congress_api_time:.2f} seconds.", flush=True)
    print(f"  - Time spent on LLM API calls: {metrics.llm_api_time:.2f} seconds.", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"Output written to {config.OUTPUT_FILE}", flush=True)
    
    # Small delay to ensure all output is flushed before container exit
    time.sleep(1)


if __name__ == "__main__":
    main()
