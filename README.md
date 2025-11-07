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
    "bill_id": "hr4313",
    "bill_title": "Hospital Inpatient Services Modernization Act",
    "sponsor_bioguide_id": "B001260",
    "bill_committee_ids": [
        "hswm00"
    ],
    "article_content": "# Hospital Bill Inches Closer to House Vote After Committee Markup\n\nBy Sarah Miller - Washington, D.C. - November 8, 2025\n\n**Immediate Context:** The \"Hospital Inpatient Services Modernization Act\" ([HR4313](https://www.congress.gov/bill/119th-congress/hr-bill/4313)), spearheaded by Rep. Vern Buchanan (R-FL-16), moved a step closer to potential floor action today as it remained placed on the House Union Calendar.  The bill, focused on health policy, has undergone committee review but remains without amendments and pending further votes.\n\n**Inside the Room:** The bill's journey through the House system is currently centered within the [Ways and Means Committee](https://api.congress.gov/v3/committee/house/hswm00).  On September 17, 2025, the committee marked up [HR4313](https://www.congress.gov/bill/119th-congress/hr-bill/4313), a procedural vote that placed it on the Union Calendar (Calendar No. 311) on October 31, 2025. Rep. Buchanan, serving on the [Ways and Means Committee](https://api.congress.gov/v3/committee/house/hswm00), is one of eight cosponsors.  Notably, there have been no amendments proposed at this stage.\n\n**Politics:** The bill's placement on the Union Calendar signals a degree of support within the House, though specifics regarding the vote's partisan makeup remain unclear based on available data.  While Rep. Buchanan's involvement suggests potential backing from his Florida district - and perhaps broader Republican circles - the absence of reported votes or amendments adds an element of uncertainty to its prospects. \n\n**What's Next:**  The bill now awaits further action on the House floor. The precise timing of any vote remains unknown, contingent upon scheduling decisions within the House leadership.  Its path through the legislative process will depend entirely on future committee considerations and ultimately, a full House vote.  The current status - Calendar No. 311 - represents a crucial milestone in its consideration.\n\n**Closing Graf:** With no amendments yet introduced and a lack of recorded votes, [HR4313](https://www.congress.gov/bill/119th-congress/hr-bill/4313)'s momentum hinges now on the broader dynamics within the House, where Republican and Democratic leadership will ultimately determine whether it reaches the floor for a potentially pivotal vote."
}
```

### Markdown Files (`output/{bill_id}.md`)

In addition to the JSON file, the system generates individual markdown files for each bill, named using the bill ID (e.g., `hr4313.md`, `s2318.md`). These files contain the article content in markdown format with proper formatting. Special characters such as newlines (`\n`), tabs (`\t`), and carriage returns (`\r`) are properly decoded and formatted in the markdown files, making them ready for direct viewing or further processing.