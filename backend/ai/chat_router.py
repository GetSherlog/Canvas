"""
Chat Router - Routes queries to appropriate handlers based on complexity
"""
import logging
from typing import Any, Optional, Dict
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from agno.agent import Agent
from agno.models.openrouter import OpenRouter
from pydantic import BaseModel

from backend.config import get_settings
from backend.ai.investigation_system import InvestigationSystem
from backend.ai.chat_tools import NotebookCellTools
from backend.ai.notebook_context_tools import create_notebook_context_tools

logger = logging.getLogger("ai.chat_router")


class QueryClassification(BaseModel):
    """Classification result for a query"""
    classification: str  # "simple" or "complex"
    reasoning: str
    confidence: float


class ChatRouter:
    """Routes queries to appropriate handlers based on complexity"""
    
    def __init__(self, notebook_id: str, notebook_manager):
        self.notebook_id = notebook_id
        self.notebook_manager = notebook_manager
        self.settings = get_settings()
        
        # Initialize tools
        cell_tools = NotebookCellTools(notebook_manager)
        context_tools = create_notebook_context_tools(notebook_id, notebook_manager)
        
        # Get raw functions for Agno with notebook_id
        cell_raw_tools = cell_tools.get_raw_tools(notebook_id=notebook_id)
        
        # Combine all notebook tools (raw functions)
        self.notebook_tools = cell_raw_tools + context_tools
        
        # Simple chat agent for basic queries
        self.simple_agent = Agent(
            name="Notebook Assistant",
            role="Helpful assistant for simple queries and basic explanations",
            model=OpenRouter(
                id="openai/gpt-4o-mini",  # Fast, cheap model for simple queries
                api_key=self.settings.openrouter_api_key
            ),
            tools=context_tools,  # Only context tools, no cell creation
            instructions=[
                "Answer questions concisely and helpfully",
                "Use list_cells to understand notebook context when needed",
                "Keep responses brief and to the point",
                "For complex investigations, inform the user that you'll need to investigate further"
            ],
            add_datetime_to_instructions=True,
            markdown=True,
            show_tool_calls=True
        )
        
        # Cell creation agent
        self.cell_creation_agent = Agent(
            name="Cell Creator",
            role="Specialized agent for creating and managing notebook cells",
            model=OpenRouter(
                id="openai/gpt-4o-mini",  # Fast model for cell operations
                api_key=self.settings.openrouter_api_key
            ),
            tools=self.notebook_tools,  # Full notebook tools including cell creation
            instructions=[
                "Create cells based on user requests",
                "When creating markdown cells, provide clear documentation",
                "When creating code cells, ensure the code is well-structured",
                "Use appropriate cell types (markdown, python, sql, etc.)",
                "Position cells appropriately in the notebook",
                "Always confirm cell creation with details about what was created"
            ],
            add_datetime_to_instructions=True,
            markdown=True,
            show_tool_calls=True
        )
        
        # Query router agent
        self.router_agent = Agent(
            name="Query Router",
            role="Classify user queries as simple, complex, or cell_creation to determine appropriate handling",
            model=OpenRouter(
                id="openai/gpt-4o-mini",  # Fast routing decisions
                api_key=self.settings.openrouter_api_key
            ),
            instructions=[
                "Classify queries into 'simple', 'complex', or 'cell_creation' categories",
                "Simple queries include:",
                "  - Questions about the notebook itself (what is this notebook for?)",
                "  - Basic explanations or definitions",
                "  - General questions that don't require investigation",
                "  - Status checks or simple information requests",
                "  - Requests for basic documentation or summaries",
                "Cell creation queries include:",
                "  - Explicit requests to create/add cells (create a cell, add a markdown cell)",
                "  - Requests to document something in the notebook",
                "  - Commands to add code, markdown, or other cell types",
                "  - Requests to add analysis or visualization cells",
                "Complex queries include:",
                "  - ANY mention of logs, log files, or log analysis",
                "  - Bug investigations requiring code analysis",
                "  - Error analysis or debugging requests",
                "  - Pattern detection or anomaly analysis",
                "  - Multi-source data correlation",
                "  - Performance analysis or optimization requests",
                "  - Security vulnerability assessments",
                "  - Requests explicitly asking for investigation or analysis",
                "  - Questions involving specific file paths or code locations",
                "  - Requests to analyze system behavior or failures",
                "IMPORTANT: If the query mentions 'log', 'logs', 'error', 'bug', 'issue', 'problem', 'analyze', 'investigate', or similar terms, classify as 'complex'",
                "IMPORTANT: If the query mentions 'create', 'add', 'make', or 'insert' along with 'cell', classify as 'cell_creation'",
                "Respond with JSON format: {\"classification\": \"<one of: simple, complex, cell_creation>\", \"reasoning\": \"<brief explanation>\", \"confidence\": <0.0-1.0>}",
                "Example responses:",
                "  - {\"classification\": \"cell_creation\", \"reasoning\": \"User wants to create a markdown cell\", \"confidence\": 0.95}",
                "  - {\"classification\": \"simple\", \"reasoning\": \"Basic question about notebook purpose\", \"confidence\": 0.9}",
                "  - {\"classification\": \"complex\", \"reasoning\": \"Requires log analysis\", \"confidence\": 0.85}"
            ],
            add_datetime_to_instructions=False,
            markdown=False
        )
        
        # Investigation system for complex queries
        self.investigation_system = InvestigationSystem(notebook_id, notebook_manager)
        
        logger.info(f"ChatRouter initialized for notebook {notebook_id}")
    
    async def classify_query(self, query: str) -> QueryClassification:
        """Determine if query needs investigation team"""
        try:
            # Add context to help router make better decisions
            routing_prompt = f"""
Classify this user query into one of three categories: 'simple', 'complex', or 'cell_creation'.

Query: "{query}"

Classification rules:
1. 'cell_creation' - Use this for ANY request to create, add, make, or insert cells (markdown, python, sql, etc.)
   Examples: "create a markdown cell", "add a cell", "make a new python cell", "insert documentation cell"
   
2. 'complex' - Use this for log analysis, debugging, investigation, or multi-step analysis requests
   Examples: "analyze the logs", "debug this error", "investigate the issue", "find the bug"
   
3. 'simple' - Use this for basic questions, explanations, or status checks
   Examples: "what is this notebook for?", "explain X", "how does Y work?"

IMPORTANT: The query "{query}" should be classified based on the PRIMARY intent.

Respond ONLY with valid JSON in this exact format:
{{"classification": "<one of: simple, complex, cell_creation>", "reasoning": "<brief explanation>", "confidence": <0.0-1.0>}}
"""
            
            # Get classification from router using async (non-streaming)
            response = await self.router_agent.arun(routing_prompt, stream=False)
            
            # Parse the response
            import json
            try:
                # Extract content from response
                if hasattr(response, 'content'):
                    content = response.content
                else:
                    content = str(response)
                
                content = content.strip()
                
                # Log the router response
                logger.info(f"Router agent classification response: {content}")
                
                # Try to parse JSON from the response
                # Look for JSON in the content
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    classification_data = json.loads(json_match.group())
                else:
                    logger.info("Router agent did not return valid JSON, using fallback keyword-based classification")
                    # Fallback parsing - check the original query, not the response
                    query_lower = query.lower()
                    
                    if any(word in query_lower for word in ["create", "add", "make", "insert"]) and "cell" in query_lower:
                        classification = "cell_creation"
                        logger.info(f"Query '{query}' classified as 'cell_creation' based on keywords")
                    elif any(word in query_lower for word in ["log", "logs", "error", "bug", "issue", "problem", "analyze", "investigate"]):
                        classification = "complex"
                        logger.info(f"Query '{query}' classified as 'complex' based on keywords")
                    else:
                        classification = "simple"
                        logger.info(f"Query '{query}' classified as 'simple' (default)")
                    
                    classification_data = {
                        "classification": classification,
                        "reasoning": "Fallback parsing based on keywords",
                        "confidence": 0.7
                    }
                
                return QueryClassification(**classification_data)
                
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to parse router response, defaulting to simple: {e}")
                logger.warning(f"Query was: {query}")
                # Default to simple for better user experience
                return QueryClassification(
                    classification="simple",
                    reasoning="Failed to parse, defaulting to simple",
                    confidence=0.5
                )
                
        except Exception as e:
            logger.error(f"Error in query classification: {e}")
            # Default to simple on error
            return QueryClassification(
                classification="simple",
                reasoning=f"Error in classification: {str(e)}",
                confidence=0.3
            )
    
    async def handle_message(
        self,
        prompt: str,
        session_id: str,
        message_history: Optional[list[Any]] = None,
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """Route and handle the message based on query complexity"""
        
        logger.info(f"Routing message in session {session_id}: '{prompt}'")
        
        # Classify the query
        classification = await self.classify_query(prompt)
        logger.info(f"Query classified as: {classification.classification} (confidence: {classification.confidence})")
        
        # Yield routing decision
        yield "status", {
            "role": "status",
            "content": f"Query classified as {classification.classification}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "routing": {
                "classification": classification.classification,
                "reasoning": classification.reasoning,
                "confidence": classification.confidence
            }
        }
        
        if classification.classification == "simple":
            # Handle with simple agent
            logger.info("Using simple agent for query")
            
            # Stream simple agent response using async
            response_iterator = await self.simple_agent.arun(
                prompt,
                stream=True
            )
            
            has_content = False
            async for response in response_iterator:
                if hasattr(response, 'content') and response.content:
                    has_content = True
                    yield "assistant", {
                        "role": "assistant",
                        "content": response.content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "agent": "simple"
                    }
            
            # If no content was generated, provide a default response
            if not has_content:
                yield "assistant", {
                    "role": "assistant",
                    "content": "I'll help you with that.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "agent": "simple"
                }
            
            # Send completion
            yield "complete", {
                "role": "status",
                "content": "Response completed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "handled_by": "simple_agent"
            }
            
        elif classification.classification == "cell_creation":
            # Handle with cell creation agent
            logger.info("Using cell creation agent for query")
            
            # Stream cell creation agent response using async
            response_iterator = await self.cell_creation_agent.arun(
                prompt,
                stream=True
            )
            
            has_content = False
            async for response in response_iterator:
                if hasattr(response, 'content') and response.content:
                    has_content = True
                    yield "assistant", {
                        "role": "assistant",
                        "content": response.content,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "agent": "cell_creator"
                    }
            
            # If no content was generated, provide a default response
            if not has_content:
                yield "assistant", {
                    "role": "assistant",
                    "content": "I'll create that cell for you.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "agent": "cell_creator"
                }
            
            # Send completion
            yield "complete", {
                "role": "status",
                "content": "Cell creation completed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "handled_by": "cell_creation_agent"
            }
            
        else:
            # Use investigation system for complex queries
            logger.info("Using investigation system for complex query")
            
            # Yield status that we're starting investigation
            yield "status", {
                "role": "status",
                "content": "Starting investigation with Investigation Team",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "team": "investigation"
            }
            
            # Stream investigation results
            async for result in self.investigation_system.investigate(
                query=prompt,
                investigation_type="general",
                notebook_context=""  # TODO: Add context if needed
            ):
                # Map investigation results to chat format
                if result["type"] == "status":
                    yield "status", {
                        "role": "status",
                        "content": result.get("message", ""),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "team": result.get("team", "investigation")
                    }
                
                elif result["type"] == "investigation_progress":
                    # Only yield if there's actual content
                    content = result.get("content", "")
                    if content:  # Skip empty content
                        yield "assistant", {
                            "role": "assistant",
                            "content": content,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "agent": result.get("team", "investigation")
                        }
                
                elif result["type"] == "final_report":
                    yield "assistant", {
                        "role": "assistant",
                        "content": result.get("content", ""),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "agent": "reporter",
                        "is_final": True
                    }
                
                elif result["type"] == "error":
                    yield "error", {
                        "role": "error",
                        "content": result.get("message", "Investigation error"),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
            
            # Send completion
            yield "complete", {
                "role": "status",
                "content": "Investigation completed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "handled_by": "investigation_system"
            }