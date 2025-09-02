#!/bin/bash

# Run tests inside the Docker container

if [ "$1" == "--help" ] || [ "$1" == "-h" ]; then
  echo "Usage: ./docker-test.sh [test_path]"
  echo ""
  echo "Examples:"
  echo "  ./docker-test.sh                     # Run all tests"
  echo "  ./docker-test.sh tests/test_trending.py  # Run specific test file"
  exit 0
fi

TEST_PATH=${1:-tests/}

# Check if container is running
if ! docker-compose ps -q api &>/dev/null; then
  echo "API container is not running. Starting it..."
  docker-compose up -d api
  
  # Wait for container to be ready
  echo "Waiting for container to be ready..."
  sleep 5
fi

echo "Running tests: $TEST_PATH"
docker-compose exec api python -m pytest $TEST_PATH -v

exit_code=$?
echo ""
if [ $exit_code -eq 0 ]; then
  echo "Tests passed successfully!"
else
  echo "Tests failed with exit code: $exit_code"
fi

exit $exit_code
