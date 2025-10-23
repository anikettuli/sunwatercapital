#!/bin/bash
# This script automates the process of building and running the application.

start_script_time=$(date +%s)
echo "--- Stopping existing containers... ---"
sudo docker-compose down --remove-orphans

echo "--- Building and starting services... ---"
# The --exit-code-from flag tells docker-compose to exit with the exit code
# of the specified container. The main app will exit when it's done,
# which will cause this command to finish.
sudo docker-compose up --build --exit-code-from app --remove-orphans

end_script_time=$(date +%s)
echo "--- Script finished ---"
echo "Total script execution time: $((end_script_time - start_script_time)) seconds."
