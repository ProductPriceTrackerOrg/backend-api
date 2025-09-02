#!/bin/bash

# Helper script for Docker operations on PricePulse API

# Function to display help message
show_help() {
    echo "PricePulse API Docker Helper Script"
    echo ""
    echo "Usage:"
    echo "  ./docker-helper.sh [command]"
    echo ""
    echo "Commands:"
    echo "  build       Build the Docker image"
    echo "  up          Start the services in detached mode"
    echo "  down        Stop and remove the containers"
    echo "  restart     Restart the services"
    echo "  logs        Show logs from the containers"
    echo "  exec        Execute a command in the API container"
    echo "  ps          Show running containers status"
    echo "  help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  ./docker-helper.sh build     # Build the Docker image"
    echo "  ./docker-helper.sh up        # Start all services in the background"
    echo "  ./docker-helper.sh logs      # Show container logs"
    echo "  ./docker-helper.sh exec bash # Get a shell in the API container"
    echo ""
}

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed or not in your PATH"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "Error: Docker Compose is not installed or not in your PATH"
    exit 1
fi

# Process command
case "$1" in
    build)
        echo "Building PricePulse API Docker image..."
        docker-compose build
        ;;
    up)
        echo "Starting PricePulse API services in detached mode..."
        docker-compose up -d
        echo "Services are now running in the background"
        echo "API is available at http://localhost:8000"
        echo "API Documentation: http://localhost:8000/docs"
        ;;
    down)
        echo "Stopping PricePulse API services..."
        docker-compose down
        ;;
    restart)
        echo "Restarting PricePulse API services..."
        docker-compose restart
        ;;
    logs)
        echo "Showing logs from PricePulse API services..."
        docker-compose logs -f
        ;;
    exec)
        if [ -z "$2" ]; then
            echo "Error: Please specify a command to execute"
            echo "Example: ./docker-helper.sh exec bash"
            exit 1
        fi
        echo "Executing command in API container: $2"
        docker-compose exec api "$2"
        ;;
    ps)
        echo "Current container status:"
        docker-compose ps
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "Unknown command: $1"
        show_help
        exit 1
        ;;
esac

exit 0
