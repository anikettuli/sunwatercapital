# RAG News Generation System

**Author:** Aniket Tuli

This project is a distributed, high-quality, high-throughput article generation system that produces Markdown-based news stories about U.S. congressional bills using structured data from the Congress.gov API.

## Architecture Overview

The system uses a Retrieval-Augmented Generation (RAG) architecture built on Python and containerized with Docker. It leverages a Kafka message broker for a distributed task queue, allowing for scalable and parallel processing of information.

-   **Main Controller (`src/main.py`)**: Dispatches tasks for each of the 10 target bills.
-   **Kafka**: Manages the flow of tasks between workers through several topics (`query.input`, `article.input`, etc.).
-   **Worker Scripts (`src/workers.py`)**:
    -   `QueryWorker`: Fetches bill data from the Congress.gov API and uses an LLM to answer specific questions.
    -   `ArticleWorker`: Aggregates the answers and generates a cohesive news article using an LLM, following a structured template (`src/article_template.md`) in the style of Politico/Punchbowl News.
    -   `LinkCheckWorker`: Validates hyperlinks within the generated article by checking HTTP status codes.
    -   `ValidatedArticleWorker`: Writes the final, validated article to both JSON (`articles.json`) and individual markdown files (`{bill_id}.md`).
-   **State Management (`src/db_manager.py`)**: A SQLite database tracks the status of each question for each bill.
-   **Kafka Integration (`src/kafka_manager.py`)**: Handles the creation of Kafka producers, consumers, and topics.
-   **LLM (`src/llm.py`)**: Interfaces with a local open-source Large Language Model (via LM Studio) for question answering and article generation. Automatically generates hyperlinks to bills, members, committees, amendments, hearings, votes, and reports when URLs are available. Normalizes Unicode characters to ASCII for proper Markdown rendering.

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

The final output will be saved in two formats:
-   **JSON format**: `output/articles.json` - Contains all articles with metadata in a structured JSON format
-   **Markdown format**: Individual `.md` files named `{bill_id}.md` (e.g., `hr4313.md`, `s2318.md`) - Contains the article content in markdown format with proper formatting for special characters

### Running Tests
The `tests/` folder contains a smoke test and unit tests for the core logic. To run the test suite, execute the `run_tests.sh` script:

```bash
./run_tests.sh
```

## Performance Benchmark

The system was benchmarked processing all 10 bills. Here is a breakdown of the performance, distinguishing between real-world time (wall-clock) and the total computational time summed across all parallel worker threads.

### Wall-Clock Time (Real-World Time)
This is the actual time elapsed from starting the script to completion.

-   **Total Script Execution:** ~175 seconds (~2.9 minutes)
    -   *Includes Docker container startup and shutdown.*
-   **Application Processing Time:** ~161.51 seconds (~2.7 minutes)
    -   *The time from when the application starts processing until the final article is written.*

### Cumulative Processing Time (Across All Threads)
This represents the total computational work performed by the system's parallel components.

-   **Total Congress.gov API Time:** ~94.98 seconds
-   **Total LLM API Time:** ~308.25 seconds

## Optimization Strategy for Speed and Accuracy

### Speed

The primary approach I took to optimize for speed was to introduce parallelism at multiple levels. The system is built on a distributed architecture using Kafka, which decouples tasks and allows them to be processed asynchronously. By configuring the key Kafka topics (`query.input`, `article.input`) with multiple partitions, I enabled parallel consumption. This was coupled with running multiple instances of the consumer worker threads (`QueryWorker`, `ArticleWorker`), allowing the application to make concurrent calls to the LLM and Congress.gov APIs. This strategy significantly reduced the overall wall-clock time required to generate all 10 articles, as evidenced by the performance benchmarks.

### Accuracy

To ensure high accuracy and prevent LLM hallucinations, the system was designed around a strict Retrieval-Augmented Generation (RAG) pattern. Every piece of generated content is directly grounded in structured data fetched from the Congress.gov API. The process is broken down into two distinct LLM steps: first, answering a set of specific, targeted questions based on the provided data, and second, generating a cohesive article from those factual answers. This separation prevents the LLM from straying from the source material.

Articles follow a structured template (`src/article_template.md`) inspired by Politico and Punchbowl News, ensuring consistent formatting and style. The system automatically generates hyperlinks to bills, members, committees, amendments, hearings, votes, and reports when URLs are available from the Congress.gov API. Links are placed directly on entity names (e.g., `[H.R.3633](URL)`) rather than next to them, and the system only creates links when URLs are available to avoid broken references.

Accuracy is further enhanced by:
- **Unicode normalization**: All Unicode characters (smart quotes, em dashes, etc.) are converted to ASCII equivalents for proper Markdown rendering
- **Link validation**: The `LinkCheckWorker` validates all hyperlinks by checking HTTP status codes
- **Strict linking rules**: The LLM is instructed to never create brackets without URLs, ensuring all links are valid

## Output Files

The system generates output in two formats:

### JSON Output (`output/articles.json`)

Contains all articles with metadata in a structured JSON format. Here is a snippet of the JSON output for a single bill:
```json
{
    "bill_id": "hr3633",
    "bill_title": "Digital Asset Market Clarity Act of 2025",
    "sponsor_bioguide_id": "H001072",
    "bill_committee_ids": [
        "hsba00",
        "hsag00",
        "ssbk00"
    ],
    "article_content": "### Committee Referrals Digital Asset Clarity Act Amid Growing Scrutiny\n\nBy Eleanor Reynolds - September 24, 2025\n\nThe [Digital Asset Market Clarity Act of 2025](https://www.congress.gov/bill/119th-congress/hr-bill/3633) is moving through the congressional process, with its latest referral to the Senate's [Banking, Housing, and Urban Affairs Committee](https://api.congress.gov/v3/committee/senate/ssbk00) marking a significant step - and raising questions about potential bipartisan support. The bill, sponsored by [Rep. Hill, J. French](https://api.congress.gov/v3/member/H001072) (R-AR-2), aims to provide clarity regarding digital assets, currently referred to the [Financial Services Committee](https://api.congress.gov/v3/committee/house/hsba00) and the [Agriculture Committee](https://api.congress.gov/v3/committee/house/hsag00) in the House.\n\nThe bill's referral to the Senate Banking Committee follows a September 18th decision to refer it to that chamber, where it was subsequently referred to the committee. Data indicates no specific vote details regarding party affiliation at the time of referral - merely noting its placement within the committee structure. Twenty-one members cosponsored [H.R. 3633](https://www.congress.gov/bill/119th-congress/hr-bill/3633), including [Rep. Hill, J. French](https://api.congress.gov/v3/member/H001072) who sits on the Banking Committee.\n\nDuring a markup session, the committee considered proposed amendments, with Amendment HAMDT 48 - adopted by agreement to the Rules amendment (A001) - receiving approval. This amendment, originating from the Committees on [Agriculture](https://api.congress.gov/v3/committee/house/hsag00) and [Financial Services](https://api.congress.gov/v3/committee/house/hsba00), was modified by House Report 119-199. This underscores the potential for significant changes to the legislation as it moves forward.\n\n\"We are committed to ensuring a clear regulatory framework for digital assets,\" stated [Rep. Hill, J. French](https://api.congress.gov/v3/member/H001072) in a recent statement. \"This bill is a crucial step toward fostering innovation and protecting consumers.\"\n\nLooking ahead, the bill will likely continue its consideration within the Senate Banking Committee. While no hearings have been recorded as of today, September 24th, 2025, the passage of Amendment HAMDT 48 suggests potential for further debate and adjustments prior to a possible floor vote. The path forward remains uncertain, with the bill's ultimate fate hinging on committee consensus and broader legislative priorities within Congress."
}
```

### Markdown Files (`output/{bill_id}.md`)

In addition to the JSON file, the system generates individual markdown files for each bill, named using the bill ID (e.g., `hr4313.md`, `s2318.md`). These files contain the article content in markdown format with proper formatting. Special characters such as newlines (`\n`), tabs (`\t`), and carriage returns (`\r`) are properly decoded and formatted in the markdown files, making them ready for direct viewing or further processing.