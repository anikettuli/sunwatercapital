"""
This module manages shared state for performance metrics.

It provides a centralized place to track timing for different parts of the
application, such as total time spent on LLM calls or external API requests.
"""
import time
import threading

class AppMetrics:
    """A thread-safe class to store and manage application metrics."""
    def __init__(self):
        self._lock = threading.Lock()
        self.llm_api_time = 0.0
        self.congress_api_time = 0.0

    def add_llm_api_time(self, duration: float):
        """Adds to the total time spent on LLM API calls."""
        with self._lock:
            self.llm_api_time += duration

    def add_congress_api_time(self, duration: float):
        """Adds to the total time spent on Congress.gov API calls."""
        with self._lock:
            self.congress_api_time += duration

# Global instance to be used across the application
metrics = AppMetrics()

# Global lock for file writing operations
file_write_lock = threading.Lock()
