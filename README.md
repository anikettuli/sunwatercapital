# RAG News Generation System

**Author:** Aniket Tuli

This project is a distributed, high-quality, high-throughput article generation system that produces Markdown-based news stories about U.S. congressional bills using structured data from the Congress.gov API.

## Architecture Overview

The system uses a Retrieval-Augmented Generation (RAG) architecture built on Python and containerized with Docker. It leverages a Kafka message broker for a distributed task queue, allowing for scalable and parallel processing of information.

-   **Main Controller (`src/main.py`)**: Dispatches tasks for each of the 10 target bills.
-   **Kafka**: Manages the flow of tasks between workers through several topics (`query.input`, `article.input`, etc.).
-   **Worker Scripts (`src/workers.py`)**:
    -   `QueryWorker`: Fetches bill data from the Congress.gov API and uses an LLM to answer specific questions.
    -   `ArticleWorker`: Aggregates the answers and generates a cohesive news article using an LLM.
    -   `LinkCheckWorker`: Validates hyperlinks within the generated article.
    -   `ValidatedArticleWorker`: Writes the final, validated article to the output file.
-   **State Management (`src/db_manager.py`)**: A SQLite database tracks the status of each question for each bill.
-   **Kafka Integration (`src/kafka_manager.py`)**: Handles the creation of Kafka producers, consumers, and topics.
-   **LLM (`src/llm.py`)**: Interfaces with a local open-source Large Language Model (via LM Studio) for question answering and article generation.

## Setup Instructions

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **LM Studio:**
    -   Download and install [LM Studio](https://lmstudio.ai/).
    -   Download the following models within LM Studio:
        -   `gemma-3-4b-it`
        -   `text-embedding-embeddinggemma-300m`
    -   Start the local inference server in LM Studio and ensure it is serving on your local network.

3.  **Environment Variables:**
    -   Create a `.env` file in the project root:
        ```bash
        touch .env
        ```
    -   Add your Congress.gov API key to the `.env` file:
        ```
        CONGRESS_API_KEY=your_api_key_here
        ```
    -   Update the `LM_STUDIO_IP` in `src/config.py` to match the IP address of the machine running LM Studio.

4.  **Docker:**
    -   Ensure you have Docker and Docker Compose installed.

## How to Run the Pipeline

Make the scripts executable first:
```bash
chmod +x start_app.sh run_tests.sh
```

### Running the Application
Execute the `start_app.sh` script to build and run the entire system:

```bash
./start_app.sh
```

The script will:
1.  Stop and remove any existing containers.
2.  Build the application's Docker image.
3.  Start all services (Zookeeper, Kafka, and the application).
4.  Stream the application logs to your terminal.
5.  Automatically shut down all containers once the application has finished generating all articles.

The final output will be saved in `output/articles.json`.

### Running Tests
The `tests/` folder contains a smoke test and unit tests for the core logic. To run the test suite, execute the `run_tests.sh` script:

```bash
./run_tests.sh
```

## Performance Benchmark

The system was benchmarked processing all 10 bills. Here is a breakdown of the performance, distinguishing between real-world time (wall-clock) and the total computational time summed across all parallel worker threads.

### Wall-Clock Time (Real-World Time)
This is the actual time elapsed from starting the script to completion.

-   **Total Script Execution:** 222 seconds (~3.7 minutes)
    -   *Includes Docker container startup and shutdown.*
-   **Application Processing Time:** 205.01 seconds (~3.4 minutes)
    -   *The time from when the application starts processing until the final article is written.*

### Cumulative Processing Time (Across All Threads)
This represents the total computational work performed by the system's parallel components.

-   **Total Congress.gov API Time:** 87.92 seconds
-   **Total LLM API Time:** 340.07 seconds

## Optimization Strategy for Speed and Accuracy

### Speed

The primary approach I took to optimize for speed was to introduce parallelism at multiple levels. The system is built on a distributed architecture using Kafka, which decouples tasks and allows them to be processed asynchronously. By configuring the key Kafka topics (`query.input`, `article.input`) with multiple partitions, I enabled parallel consumption. This was coupled with running multiple instances of the consumer worker threads (`QueryWorker`, `ArticleWorker`), allowing the application to make concurrent calls to the LLM and Congress.gov APIs. This strategy significantly reduced the overall wall-clock time required to generate all 10 articles, as evidenced by the performance benchmarks.

### Accuracy

To ensure high accuracy and prevent LLM hallucinations, the system was designed around a strict Retrieval-Augmented Generation (RAG) pattern. Every piece of generated content is directly grounded in structured data fetched from the Congress.gov API. The process is broken down into two distinct LLM steps: first, answering a set of specific, targeted questions based on the provided data, and second, generating a cohesive article from those factual answers. This separation prevents the LLM from straying from the source material. Furthermore, accuracy is enhanced by programmatically generating hyperlinks to the source bills and sponsors on Congress.gov and including a dedicated `LinkCheckWorker` to validate that all URLs resolve correctly.

## Example Output (`output/articles.json`)

Here is a snippet of the final JSON output for a single bill:
```json
{
    "bill_id": "hr1968",
    "bill_title": "To provide for a limitation on availability of funds for Department of Health and Human Services, Centers for Disease Control and Prevention Injury Prevention and Control for fiscal year 2024.",
    "sponsor_bioguide_id": "B001302",
    "bill_committee_ids": [],
    "article_content": "## Bill Aims to Limit CDC Funding, Referred to Health Subcommittee\\n\\n**Washington D.C.** – Legislation proposing a funding limitation for the Centers for Disease Control and Prevention (CDC) for fiscal year 2024 has been introduced in the U.S. House of Representatives. Designated as H.R. 1968, the bill is currently under review by the Subcommittee on Health.\\n\\nSponsored by Representative Andy Biggs (R-AZ-5), the measure seeks to restrict funding for the CDC. As of April 7, 2023, the bill has been officially referred to this subcommittee for consideration.\\n\\nAccording to available information, five members have cosponsored H.R. 1968, with one cosponsor having subsequently withdrawn their support. However, details regarding the specific committee membership on the Subcommittee on Health remain undisclosed at this time. \\n\\nCurrently, no information is available regarding any hearings or discussions related to the bill’s potential impact. The latest documented action indicates only that it was referred to the subcommittee – without further outlining any prior proceedings or debate. Furthermore, no amendments have been reported in connection with H.R. 1968."
}
```