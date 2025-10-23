#!/bin/bash
# This script automates the process of running the test suite in a clean Docker environment.

echo "--- Building image and running test suite... ---"

# The --build flag ensures any changes to the Dockerfile or code are included.
# The --rm flag ensures the container is removed after the tests complete.
sudo docker-compose run --build --rm app python3 -m pytest tests/
