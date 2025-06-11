#!/bin/bash
# Sherlog Canvas Launcher Script
# This script starts all the components needed for Sherlog Canvas using Docker Compose

# Environment setup
set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Ensure .env file exists
if [ ! -f .env ]; then
    echo "Error: .env file not found. Please create one from .env.example."
    exit 1
fi

# Load environment variables
set -a
source .env
set +a

# Function to check if Docker is running
check_docker() {
    if ! docker info >/dev/null 2>&1; then
        echo "Error: Docker is not running or not installed."
        echo "Please start Docker and try again."
        exit 1
    fi
    
    # Check for Docker Compose
    if ! command -v docker-compose >/dev/null 2>&1; then
        echo "Warning: Docker Compose is not installed."
        echo "Please install Docker Compose, then try again."
        exit 1
    fi
}

# We now use git inside the Docker build process
check_git() {
    # Git is no longer required locally as it's used inside the containers
    echo "Git check skipped - now used inside containers where needed"
}

# Main execution
echo "Starting Sherlog Canvas..."

# Check prerequisites
check_docker
check_git

# Create directories needed for volumes
mkdir -p data

# Print steps as they execute
set -x

# Stop any running containers
echo "Stopping running containers..."
docker-compose down

# Pull necessary Docker images manually if needed
echo "Pulling ghcr.io/navneet-mkr/logai-mcp:0.1.5 if not present..."
docker pull ghcr.io/navneet-mkr/logai-mcp:0.1.5

echo "Pulling ghcr.io/github/github-mcp-server:latest if not present..."
docker pull ghcr.io/github/github-mcp-server:latest

# Remove any old images to ensure clean build
echo "Removing old Docker images..."
docker-compose rm -f

# Build all services with no cache to ensure latest changes
echo "Building Docker images..."
docker-compose build

# Start services in detached mode, force recreate
echo "Starting containers..."
docker-compose up -d --force-recreate

# Show running containers
echo "Services started. Status:"
docker-compose ps

echo "Sherlog Canvas is now running!"
echo "Backend API: http://localhost:9091/api"
echo "Frontend UI: http://localhost:3000"
echo ""
echo "To stop all services, run:"
echo "docker-compose down"
echo ""
echo "To view logs, run:"
echo "docker-compose logs -f"