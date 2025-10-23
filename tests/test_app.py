"""
Comprehensive tests for the RAG News Generation application.
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

# Add the project root to the Python path to allow for correct module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.db_manager import DBManager
from src.llm import get_bill_data, add_hyperlinks
from src.workers import QueryWorker

# --- Mocks and Fixtures ---

@pytest.fixture(scope="module")
def mock_config():
    """Mocks the config module for the entire test session."""
    with patch('src.config') as mock_config_instance:
        mock_config_instance.QUESTIONS = {
            1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4", 5: "Q5", 6: "Q6", 7: "Q7"
        }
        mock_config_instance.KAFKA_ARTICLE_TOPIC = 'article.input'
        mock_config_instance.CONGRESS_API_KEY = 'test_key'
        yield mock_config_instance

@pytest.fixture
def db_manager():
    """Provides an in-memory SQLite database manager for testing."""
    return DBManager(db_url="sqlite:///:memory:")


# --- Test Cases ---

def test_smoke_imports():
    """
    Smoke Test: Ensures all main application modules can be imported.
    """
    try:
        from src import config, db_manager, kafka_manager, llm, main, workers
    except ImportError as e:
        pytest.fail(f"Failed to import a core module: {e}")

def test_db_storage_and_retrieval(db_manager):
    """
    Tests that the DBManager can store, update, and retrieve answers correctly.
    """
    bill_id = "hr123"
    db_manager.store_answer(bill_id, 1, "Question 1", "Answer 1")
    db_manager.store_answer(bill_id, 2, "Question 2", "Answer 2")
    db_manager.store_answer(bill_id, 1, "Question 1", "Updated Answer 1") # Update

    answers = db_manager.get_answers_for_bill(bill_id)
    assert len(answers) == 2
    assert answers[1] == "Updated Answer 1"
    assert answers[2] == "Answer 2"

def test_api_url_formatting(mock_config):
    """
    Tests that the get_bill_data function formats the API URL correctly.
    """
    with patch('src.llm.requests.get') as mock_get:
        get_bill_data("s567", "s", "117", "test_key")
        expected_url = "https://api.congress.gov/v3/bill/117/s/567?api_key=test_key"
        mock_get.assert_called_once_with(expected_url)

def test_hyperlink_generation():
    """
    Tests that the add_hyperlinks function correctly adds Markdown links.
    """
    sample_text = "This article is about hr987, sponsored by Jane Smith."
    sample_bill_data = {
        "bill": {
            "congress": "118", "type": "hr", "number": "987",
            "sponsors": [{"fullName": "Jane Smith", "url": "https://congress.gov/member/jane-smith"}]
        }
    }
    result = add_hyperlinks(sample_text, sample_bill_data)
    assert "[hr987](https://www.congress.gov/bill/118th-congress/hr-bill/987)" in result
    assert "[Jane Smith](https://congress.gov/member/jane-smith)" in result

@patch('src.workers.KafkaProducer')
@patch('src.workers.KafkaConsumer')
@patch('src.workers.get_bill_data', return_value={"bill": "data"})
@patch('src.workers.get_answer_from_bill', return_value="Test Answer")
def test_query_worker_stores_answer(mock_get_answer, mock_get_bill, mock_KafkaConsumer, mock_KafkaProducer, db_manager, mock_config):
    """
    Tests that the QueryWorker processes a message and correctly stores the answer.
    """
    mock_consumer_instance = mock_KafkaConsumer.return_value
    mock_message = MagicMock()
    mock_message.value = {"bill_id": "hr123", "bill_type": "hr", "congress": "118", "question_id": 1}
    mock_consumer_instance.__iter__.return_value = [mock_message]

    worker = QueryWorker()
    worker.db_manager = db_manager
    worker.run()

    answers = db_manager.get_answers_for_bill("hr123")
    assert answers[1] == "Test Answer"

@patch('src.workers.KafkaProducer')
@patch('src.workers.KafkaConsumer')
@patch('src.workers.get_bill_data', return_value={"bill": "data"})
@patch('src.workers.get_answer_from_bill', return_value="Test Answer")
def test_article_worker_trigger(mock_get_answer, mock_get_bill, mock_KafkaConsumer, mock_KafkaProducer, db_manager, mock_config):
    """
    Tests that the QueryWorker dispatches an article task when all questions are answered.
    """
    mock_producer_instance = mock_KafkaProducer.return_value
    mock_consumer_instance = mock_KafkaConsumer.return_value
    mock_message = MagicMock()
    mock_message.value = {"bill_id": "hr123", "bill_type": "hr", "congress": "118", "question_id": 7}
    mock_consumer_instance.__iter__.return_value = [mock_message]

    worker = QueryWorker()
    worker.db_manager = db_manager

    with patch.object(worker.db_manager, 'are_all_questions_answered', return_value=True):
        worker.run()

    mock_producer_instance.send.assert_called_once_with(
        mock_config.KAFKA_ARTICLE_TOPIC,
        {"bill_id": "hr123", "bill_type": "hr", "congress": "118"}
    )
