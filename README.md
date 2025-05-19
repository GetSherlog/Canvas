# Sherlog Canvas (Alpha)

**Note: Sherlog is still in development and there might be quite a few kinks and issues. We are actively working on fixing those. Whenever you find an problem, feel free to create an issue and we will try to resolve ASAP**

Sherlog Canvas is a reactive jupyter notebook like interface for software engineering investigation tasks, focused on debugging, log analysis, metric analysis, and database queries. It integrates advanced AI capabilities to assist with complex investigations.

## Features

- **Reactive Notebook Interface**: Changes to cells automatically update dependent cells
- **Multi-Agent AI System**: Creates investigation plans and generates cells based on user queries
- **Multiple Data Source Integration**: Connect to Log sources, github, filesystem, code repos, metric sources, docker etc via the power of MCP
- **Specialized Cell Types**: SQL, log queries, metrics, Python code, and more
- **Collaborative Investigation Environment**: AI and users work together to solve problems

## Supported Cell Types

| Cell Type | Purpose |
|-----------|---------|
| `markdown` | Rich-text documentation |
| `python` | Execute Python code inside an isolated sandbox |
| `github` | Interact with the GitHub API |
| `logai`  | Log ai analysis tools 
| `filesystem` | Read-only access to a host directory (needs `SHERLOG_HOST_FS_ROOT`) |
| `summarization` | AI-generated summaries |
| `investigation_report` | Render a structured investigation write-up |

## Architecture

Sherlog Canvas consists of:

1. **Backend**:
   - FastAPI server with WebSocket support
   - Dependency tracking system for reactivity
   - MCP server integration for data sources
   - AI orchestration for query planning

## Quick Start

Getting from clone to a fully working instance only requires two steps: create a `.env` file and run the bundled launcher script.

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/sherlog-canvas.git
   cd sherlog-canvas
   ```

2. **Clone the `.env.example` file and rename to  `.env` file** (minimum required configuration)

   ```env
   # .env – minimal setup
   SHERLOG_OPENROUTER_API_KEY=your_openrouter_api_key_here   # required for the AI models (internally sherlog uses a host of different LLMs depending on the task so we use openrouter)

   # Optional – expose a read-only slice of your local filesystem to *filesystem* cells
   # SHERLOG_HOST_FS_ROOT=/Users/$(whoami)

   # The internal database defaults to SQLite at ./data/sherlog.db – nothing to change for basic use.
   ```

   Don't worry about memorising every knob – the [Configuration](#configuration) section lists them all with sensible defaults.

3. **Launch everything**

   ```bash
   ./start.sh
   ```

   The script will build and start the **backend API**, **frontend UI**, **Redis cache**, and any first-party MCP servers defined in `docker-compose.yml`.

4. **Open Sherlog Canvas**

   * Frontend UI:  http://localhost:3000
   * Backend API: http://localhost:9091/api

5. **Stop or view logs**

   ```bash
   # Stop all containers
   docker-compose down

   # Tail logs for every service
   docker-compose logs -f
   ```

That's it – you now have a fully-functional, AI-powered investigative notebook running locally.

## Detailed Setup Guide

This guide provides more comprehensive instructions for setting up Sherlog Canvas. You can choose between a Docker-based setup.

### Prerequisites

Before you begin, ensure you have the following installed:

*   **Git**: For cloning the repository.
*   **Docker and Docker Compose**: (Recommended for an easier setup) For running the application and its dependencies in containers.

### Option 1: Docker-Based Setup (Recommended)

This is the easiest way to get Sherlog Canvas up and running. The `start.sh` script utilizes Docker Compose to manage all services.

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/yourusername/sherlog-canvas.git
    cd sherlog-canvas
    ```

2.  **Create and configure your environment file**:
    Create a `.env` file (there is no example committed yet) and add at least your `SHERLOG_OPENROUTER_API_KEY`. You may also override other settings as needed (see the [Configuration](#configuration) section).
    ```env
    SHERLOG_OPENROUTER_API_KEY=your_openrouter_api_key_here
    SHERLOG_DB_TYPE=sqlite # Default configuration uses SQLite
    # To use PostgreSQL instead, uncomment and configure the following:
    # SHERLOG_DB_TYPE=postgresql
    # POSTGRES_USER=your_db_user
    # POSTGRES_PASSWORD=your_db_password
    # POSTGRES_DB=sherlog_canvas_db
    # DATABASE_URL=postgresql://your_db_user:your_db_password@your_db_host:5432/sherlog_canvas_db
    ```
    By default, the Docker setup uses a SQLite database stored in `./data/sherlog.db` (persisted via a Docker volume). If you prefer to use an external PostgreSQL database, set `SHERLOG_DB_TYPE=postgresql` and configure the relevant `DATABASE_URL` or other PostgreSQL variables in your `.env` file.

3.  **Run the startup script**:
    ```bash
    ./start.sh
    ```
    This script will:
    *   Build the backend Docker image (if not already built).
    *   Start the backend API server.
    *   Start common MCP servers like `mcp-grafana` as defined in `docker-compose.yml`.
    *   If `SHERLOG_DB_TYPE` is explicitly set to `postgresql` in your `.env` file (and you haven't provided an external `DATABASE_URL`), it will also start a PostgreSQL container and the `pg-mcp` server.
    *   By default (with `SHERLOG_DB_TYPE=sqlite`), a PostgreSQL container and `pg-mcp` will not be started.

4.  **Access the application**:
    Open your web browser and navigate to `http://localhost:3000` (or the configured frontend port).

5.  **Stopping the application**:
    To stop all services, run:
    ```bash
    ./stop.sh
    ```
    Or, from the `sherlog-canvas` directory:
    ```bash
    docker-compose down
    ```

### Configuring Data Connections

Once Sherlog Canvas is running, you can configure connections to your data sources:

1.  **Access Sherlog Canvas**: Open the application in your browser (e.g., `http://localhost:3000`).
2.  **Navigate to Data Connections**: Find the "Data Connections" or "Settings" section in the UI.
3.  **Add a New Connection**:
    *   Click "Add Connection" or a similar button.
    *   Select the type of data source you want to connect to (e.g., Grafana, PostgreSQL, Prometheus, Loki, S3).
4.  **Provide Connection Details**
5.  **Save Connection**:
    Sherlog Canvas will store these connection details (by default in `./data/connections.json` or as configured by `SHERLOG_CONNECTION_STORAGE_TYPE`). When a connection is added or used, Sherlog Canvas will typically ensure the relevant MCP server is running (if managed by Sherlog, e.g., via Docker) or attempt to connect to an existing one.

This setup allows the AI agents within Sherlog Canvas to query and interact with your configured data sources.

## MCP Servers

Sherlog Canvas uses MCP servers for data source integration.

### Setting Up Data Connections

1. Start Sherlog Canvas with `./start.sh`
2. Navigate to the "Data Connections" tab in the UI
3. Click "Add Connection" and select the connection type
4. Provide the connection details



## Core Concepts

Sherlog Canvas operates on a few key concepts:

### Cells

A **Cell** is the fundamental unit of work in a Sherlog Canvas notebook. Each cell contains a specific piece of code or query, a type (e.g., `sql`, `python`, `logql`, `promql`, `markdown`), and its output. Cells can be created manually by the user or automatically by the AI agent based on an investigation query.

### Dependency Graph

Sherlog Canvas maintains a **Dependency Graph** to manage the relationships between cells. When a cell is modified, the system automatically identifies and re-executes any dependent cells downstream in the graph. This reactive nature ensures that the notebook always reflects the latest state of the investigation based on the current inputs and code. Dependencies are typically established when one cell references the output or variables defined in another cell (e.g., a Python cell using the results of an SQL query cell).

### Tool Use (AI Agents)

When you provide an investigation query (e.g., "Find the source of the 5xx errors in the payment service"), the AI agent system analyzes the request and determines which **Tools** are needed to answer it. Each tool corresponds to a specific data source or analysis capability (e.g., querying Prometheus, searching Loki logs, executing SQL against a database). The AI agent then generates the necessary cells, populating them with the appropriate queries or code to use these tools. The results are then displayed in the respective cell outputs.

### Example Investigation Flow

Let's walk through a simple example:

1.  **User Query**: "Show me the average request latency for the 'checkout' service over the last hour."
2.  **AI Agent Analysis**: The agent determines that this requires querying Prometheus metrics.
3.  **Tool Selection**: The agent selects the `prometheus_query` tool.
4.  **Cell Generation**: The agent creates a new cell of type `promql` with a query like:
    ```promql
    avg(rate(http_request_duration_seconds_sum{service="checkout"}[1h])) / avg(rate(http_request_duration_seconds_count{service="checkout"}[1h]))
    ```
5.  **Execution**: The cell is executed via the Prometheus MCP server.
6.  **Output**: The result (the average latency) is displayed in the cell's output panel.
7.  **User Interaction**: Now, suppose the user wants to see the P99 latency instead. They can manually edit the `promql` cell:
    ```promql
    histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{service="checkout"}[1h])) by (le))
    ```
8.  **Reactivity**: The cell automatically re-executes, showing the updated P99 latency. If another cell depended on the output of this cell (e.g., a Python cell plotting the latency), it would also automatically re-execute due to the dependency graph.

This reactive, AI-assisted workflow allows users to fluidly investigate issues, leveraging automated data gathering and analysis while retaining full control to manually explore and refine the investigation.

## Configuration

Configuration is managed through environment variables with the `SHERLOG_` prefix:

| Variable | Description | Default |
| --- | --- | --- |
| `SHERLOG_API_HOST` | Host to bind the API server | `0.0.0.0` |
| `SHERLOG_API_PORT` | Port for the API server | `8000` |
| `SHERLOG_DEBUG` | Enable debug mode | `false` |
| `SHERLOG_CORS_ORIGINS` | CORS origins (comma-separated) | `*` |
| `SHERLOG_AUTH_ENABLED` | Enable authentication | `false` |
| `SHERLOG_OPENROUTER_API_KEY` | OpenRouter API key (enables AI features) | *(none)* |
| `SHERLOG_HOST_FS_ROOT` | Host path to mount read-only for `filesystem` cells | *(unset)* |
| `SHERLOG_LOGFIRE_TOKEN` | LogFire token for logging | |
| `SHERLOG_ENVIRONMENT` | Environment (development, production) | `development` |
| `SHERLOG_CONNECTION_STORAGE_TYPE` | Storage type for connections (file, env, db, none) | `file` |
| `SHERLOG_CONNECTION_FILE_PATH` | Path to connection storage file | `./data/connections.json` |
| `SHERLOG_DB_HOST` | Database host | `localhost` |
| `SHERLOG_DB_PORT` | Database port | `5432` |
| `SHERLOG_DB_NAME` | Database name | `sherlog` |
| `SHERLOG_DB_USER` | Database user | `sherlog` |
| `SHERLOG_DB_PASSWORD` | Database password | `sherlog` |
| `SHERLOG_DB_TYPE` | Database type (sqlite, postgresql) | `sqlite` |
| `SHERLOG_DB_FILE` | SQLite database file path | `./data/sherlog.db` |
| `SHERLOG_PYTHON_CELL_TIMEOUT` | Timeout for Python cell execution (seconds) | `30` |
| `SHERLOG_PYTHON_CELL_MAX_MEMORY` | Max memory for Python cell execution (MB) | `1024` |
| `SHERLOG_DEFAULT_QUERY_TIMEOUT` | Default timeout for database queries (seconds) | `30` |