#!/bin/bash

# Ensure the server is running
echo "Checking if the FastAPI server is running..."
response=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health)

if [ "$response" != "200" ]; then
    echo "Server does not appear to be running. Please start it with: uvicorn app.main:app --reload"
    exit 1
fi

echo "Server is running. Running the test script..."

# Run the test script
python tests/test_categories.py
