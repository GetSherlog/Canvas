"""
Investigation System using MCP Integration
Simplified investigation system that orchestrates AI agents with MCP tools.
"""
import logging
import os
from typing import Any, Dict, List, Optional, AsyncGenerator, Union, Callable, TYPE_CHECKING

from agno.agent import Agent
from agno.team import Team
from agno.models.openrouter import OpenRouter
from agno.tools.mcp import MCPTools
from agno.tools.reasoning import ReasoningTools
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from mcp import StdioServerParameters

from backend.config import get_settings
from backend.services.connection_manager import ConnectionManager, get_connection_manager
from backend.services.connection_handlers.registry import get_handler

# Import media analysis components
from backend.ai.media_describer_agent import MediaDescriberAgent
from backend.ai.media_analysis_workflow import MediaAnalysisWorkflow

# Use TYPE_CHECKING to avoid circular import
if TYPE_CHECKING:
    from backend.services.notebook_manager import NotebookManager

# Simple media URL detection and analysis
import re

logger = logging.getLogger("ai.investigation")

class InvestigationSystem:
    """
    Investigation system that orchestrates AI agents with MCP tools.
    Provides comprehensive investigation capabilities including media analysis with reasoning tools.
    """
    
    def __init__(self, notebook_id: str, notebook_manager: "NotebookManager", connection_manager: Optional[ConnectionManager] = None):
        self.settings = get_settings()
        self.notebook_id = notebook_id
        self.notebook_manager = notebook_manager
        self.connection_manager = connection_manager or get_connection_manager()
        
        # Create persistent memory for this notebook
        self.memory = Memory(
            db=SqliteMemoryDb(
                table_name=f"investigation_{notebook_id.replace('-', '_')}", 
                db_file="data/investigation_memory.db"
            )
        )
        
        # Initialize media analysis workflow
        self.media_workflow = MediaAnalysisWorkflow(notebook_id=notebook_id)
        
        # Initialize media analysis - only MediaDescriberAgent (which uses direct HTTP)
        self.media_describer = MediaDescriberAgent()
        
        logger.info(f"InvestigationSystem initialized for notebook {notebook_id} with media analysis workflow and reasoning tools")
    
    def _create_reasoning_tools(self) -> ReasoningTools:
        """Create reasoning tools for agents to use systematic thinking"""
        return ReasoningTools(
            add_instructions=True,  # Add reasoning instructions to agents
        )
    
    async def _create_mcp_tools_from_connection(self, connection_type: str) -> Optional[MCPTools]:
        """Create MCPTools from existing connection configuration"""
        try:
            default_conn = await self.connection_manager.get_default_connection(connection_type)
            if not default_conn or not default_conn.config:
                logger.warning(f"No default {connection_type} connection found")
                return None

            handler = get_handler(connection_type)
            stdio_params = handler.get_stdio_params(default_conn.config)
            
            # Create StdioServerParameters for MCP Tools
            server_params = StdioServerParameters(
                command=stdio_params.command,
                args=stdio_params.args,
                env=stdio_params.env
            )
            
            logger.info(f"Created MCP tools for {connection_type}: {stdio_params.command} {stdio_params.args}")
            return MCPTools(server_params=server_params)
            
        except Exception as e:
            logger.error(f"Failed to create MCP tools for {connection_type}: {e}", exc_info=True)
            return None
    
    async def _create_hardcoded_mcp_tools(self) -> Dict[str, Optional[MCPTools]]:
        """Create MCP tools for services that use hardcoded configurations"""
        tools = {}
        
        # Python MCP (Data Science server)
        try:
            python_params = StdioServerParameters(
                command='/root/.local/bin/uv',
                args=[
                    '--directory',
                    '/opt/mcp-server-data-exploration',
                    'run',
                    'mcp-server-ds'
                ],
                env=os.environ.copy()
            )
            tools['python'] = MCPTools(server_params=python_params)
            logger.info("Created Python MCP tools for data science server")
        except Exception as e:
            logger.error(f"Failed to create Python MCP tools: {e}")
            tools['python'] = None
        
        # LogAI MCP (Docker-based)
        try:
            env_copy = os.environ.copy()
            docker_args = [
                "run", "--rm", "-i",
                "--volume=/var/run/docker.sock:/var/run/docker.sock"
            ]
            
            host_fs_root = os.environ.get("SHERLOG_HOST_FS_ROOT")
            if host_fs_root:
                docker_args.extend(["-v", f"{host_fs_root}:{host_fs_root}:ro"])
            
            docker_args.append("ghcr.io/navneet-mkr/logai-mcp:0.1.3")
            
            logai_params = StdioServerParameters(
                command="docker",
                args=docker_args,
                env=env_copy
            )
            tools['logai'] = MCPTools(server_params=logai_params)
            logger.info("Created LogAI MCP tools")
        except Exception as e:
            logger.error(f"Failed to create LogAI MCP tools: {e}")
            tools['logai'] = None
        
        return tools
    
    async def _create_notebook_tools(self) -> List[Callable]:
        """Create notebook-specific tools for investigation agents"""
        
        def add_markdown_cell(content: str, title: str = "Analysis") -> str:
            """Add a markdown cell to the notebook"""
            try:
                logger.info(f"Adding markdown cell: {title}")
                # TODO: Integrate with actual notebook_manager
                # cell_id = await self.notebook_manager.create_cell(...)
                return f"Added markdown cell: {title}"
            except Exception as e:
                logger.error(f"Failed to add markdown cell: {e}")
                return f"Error adding cell: {e}"
        
        def add_code_cell(code: str, language: str = "python") -> str:
            """Add a code cell to the notebook"""
            try:
                logger.info(f"Adding {language} code cell")
                # TODO: Integrate with actual notebook_manager
                return f"Added {language} code cell"
            except Exception as e:
                logger.error(f"Failed to add code cell: {e}")
                return f"Error adding code cell: {e}"
        
        def get_notebook_context() -> str:
            """Get current notebook context"""
            try:
                logger.info("Retrieving notebook context")
                # TODO: Use actual notebook context logic
                return "Current notebook context retrieved"
            except Exception as e:
                logger.error(f"Failed to get notebook context: {e}")
                return "No context available"
        
        return [add_markdown_cell, add_code_cell, get_notebook_context]
    
    def _create_media_workflow_tool(self) -> Callable:
        """Create a tool that runs the media analysis workflow"""
        
        def run_media_analysis_workflow(query: str, notebook_context: str = "") -> str:
            """Run the complete media analysis workflow on the provided query"""
            try:
                logger.info(f"Running media analysis workflow for query: {query[:100]}...")
                
                # Run the workflow and collect all responses
                workflow_iterator = self.media_workflow.run(
                    query=query,
                    notebook_context=notebook_context,
                    use_cache=True
                )
                
                # Collect all responses from the workflow
                responses = []
                for response in workflow_iterator:
                    if hasattr(response, 'content') and response.content:
                        responses.append(response.content)
                
                if responses:
                    # Return the final response (usually the comprehensive report)
                    return responses[-1]
                else:
                    return "Media analysis workflow completed but no results were generated"
                    
            except Exception as e:
                logger.error(f"Media analysis workflow failed: {e}")
                return f"Error running media analysis workflow: {e}"
        
        return run_media_analysis_workflow

    async def initialize_agents(self) -> Dict[str, Agent]:
        """Initialize specialized agents using existing MCP infrastructure with reasoning capabilities"""
        
        # Get MCP tools from existing connections
        github_mcp = await self._create_mcp_tools_from_connection("github")
        filesystem_mcp = await self._create_mcp_tools_from_connection("filesystem") 
        qdrant_mcp = await self._create_mcp_tools_from_connection("git_repo")  # Qdrant via git_repo
        
        # Get hardcoded MCP tools
        hardcoded_tools = await self._create_hardcoded_mcp_tools()
        python_mcp = hardcoded_tools.get('python')
        logai_mcp = hardcoded_tools.get('logai')
        
        # Get notebook tools, media workflow tool, and reasoning tools
        notebook_tools = await self._create_notebook_tools()
        media_workflow_tool = self._create_media_workflow_tool()
        reasoning_tools = self._create_reasoning_tools()
        
        agents = {}
        
        # GitHub Research Agent
        if github_mcp:
            agent_tools: List[Any] = []
            agent_tools.append(reasoning_tools)  # Add reasoning first
            agent_tools.append(github_mcp)
            agent_tools.extend(notebook_tools)
            
            agents['github'] = Agent(
                name="GitHub Researcher",
                role="Expert at searching and analyzing GitHub repositories, issues, and code with systematic reasoning",
                model=OpenRouter(
                    id="openai/gpt-4.1",  # Updated to GPT 4.1
                    api_key=self.settings.openrouter_api_key
                ),
                tools=agent_tools,
                instructions=[
                    "Use reasoning tools to think through complex problems systematically",
                    "Search for relevant repositories, issues, and code examples",
                    "Analyze code quality, patterns, and potential issues", 
                    "Look for similar problems and their solutions",
                    "Provide actionable insights with specific examples",
                    "Create notebook cells with your findings"
                ],
                add_datetime_to_instructions=True,
                markdown=True,
                show_tool_calls=True
            )
            logger.info("Created GitHub research agent with reasoning tools and GPT 4.1")
        
        # Filesystem Analysis Agent  
        if filesystem_mcp:
            agent_tools: List[Any] = []
            agent_tools.append(reasoning_tools)  # Add reasoning first
            agent_tools.append(filesystem_mcp)
            agent_tools.extend(notebook_tools)
            
            agents['filesystem'] = Agent(
                name="Filesystem Analyzer",
                role="Expert at analyzing local files, directories, and code structures with methodical reasoning", 
                model=OpenRouter(
                    id="openai/gpt-4.1",  # Updated to GPT 4.1
                    api_key=self.settings.openrouter_api_key
                ),
                tools=agent_tools,
                instructions=[
                    "Apply systematic reasoning to file and code analysis",
                    "Analyze file structures and code organization",
                    "Identify potential issues in configuration files",
                    "Examine log files for errors and patterns",
                    "Suggest improvements to project structure",
                    "Document findings in notebook cells"
                ],
                add_datetime_to_instructions=True,
                markdown=True,
                show_tool_calls=True
            )
            logger.info("Created filesystem analysis agent with reasoning tools and GPT 4.1")
        
        # Code Search Agent (Qdrant)
        if qdrant_mcp:
            agent_tools: List[Any] = []
            agent_tools.append(reasoning_tools)  # Add reasoning first
            agent_tools.append(qdrant_mcp)
            agent_tools.extend(notebook_tools)
            
            agents['code_search'] = Agent(
                name="Code Search Specialist", 
                role="Expert at semantic code search and analysis using vector databases with logical reasoning",
                model=OpenRouter(
                    id="openai/gpt-4.1",  # Updated to GPT 4.1
                    api_key=self.settings.openrouter_api_key
                ),
                tools=agent_tools,
                instructions=[
                    "Use reasoning tools to approach code search systematically",
                    "Perform semantic searches across codebases",
                    "Find relevant code patterns and examples",
                    "Analyze code similarity and relationships", 
                    "Provide context-aware code recommendations",
                    "Create detailed analysis in notebook cells"
                ],
                add_datetime_to_instructions=True,
                markdown=True,
                show_tool_calls=True
            )
            logger.info("Created code search agent with reasoning tools and GPT 4.1")
        
        # Python Data Analysis Agent
        if python_mcp:
            agent_tools: List[Any] = []
            agent_tools.append(reasoning_tools)  # Add reasoning first
            agent_tools.append(python_mcp)
            agent_tools.extend(notebook_tools)
            
            agents['python'] = Agent(
                name="Python Data Analyst",
                role="Expert at executing Python code and analyzing data with systematic reasoning",
                model=OpenRouter(
                    id="openai/gpt-4.1",  # Updated to GPT 4.1
                    api_key=self.settings.openrouter_api_key
                ), 
                tools=agent_tools,
                instructions=[
                    "Apply reasoning tools to break down complex data analysis tasks",
                    "Execute Python code for data analysis and exploration",
                    "Create visualizations and statistical summaries",
                    "Debug and troubleshoot Python code issues",
                    "Suggest optimizations and best practices",
                    "Document results in notebook cells"
                ],
                add_datetime_to_instructions=True,
                markdown=True,
                show_tool_calls=True
            )
            logger.info("Created Python analysis agent with reasoning tools and GPT 4.1")
        
        # Log Analysis Agent
        if logai_mcp:
            agent_tools: List[Any] = []
            agent_tools.append(reasoning_tools)  # Add reasoning first
            agent_tools.append(logai_mcp)
            agent_tools.extend(notebook_tools)
            
            agents['logai'] = Agent(
                name="Log Analysis Specialist",
                role="Expert at analyzing software logs for patterns and anomalies with methodical reasoning", 
                model=OpenRouter(
                    id="openai/gpt-4.1",  # Updated to GPT 4.1
                    api_key=self.settings.openrouter_api_key
                ),
                tools=agent_tools,
                instructions=[
                    "Use reasoning tools to systematically analyze log patterns",
                    "Analyze log files for errors, patterns, and anomalies",
                    "Perform log clustering and classification",
                    "Detect unusual patterns or potential issues",
                    "Provide insights on system health and performance",
                    "Create detailed log analysis reports"
                ],
                add_datetime_to_instructions=True,
                markdown=True,
                show_tool_calls=True
            )
            logger.info("Created log analysis agent with reasoning tools and GPT 4.1")
        
        # Media Analysis Agent - uses the workflow tool
        agent_tools_media: List[Any] = [reasoning_tools, media_workflow_tool]  # Add reasoning first
        agent_tools_media.extend(notebook_tools)
        if github_mcp:
            agent_tools_media.append(github_mcp)
        if filesystem_mcp:
            agent_tools_media.append(filesystem_mcp)
            
        agents['media'] = Agent(
            name="Visual Bug Investigator",
            role="Expert at analyzing screenshots, videos, and visual evidence to identify bugs with systematic reasoning",
            model=OpenRouter(
                id="openai/gpt-4.1",  # Updated to GPT 4.1
                api_key=self.settings.openrouter_api_key
            ),
            tools=agent_tools_media,
            instructions=[
                "Apply reasoning tools to systematically analyze visual evidence",
                "Use the media analysis workflow to process visual evidence from user queries",
                "The workflow will extract media URLs, analyze visual content, and correlate with code",
                "Provide additional context from GitHub and filesystem tools when needed",
                "Generate comprehensive bug investigation reports based on visual evidence",
                "Focus on actionable recommendations for developers"
            ],
            add_datetime_to_instructions=True,
            markdown=True,
            show_tool_calls=True
        )
        logger.info("Created media analysis agent with reasoning tools, workflow integration, and GPT 4.1")
        
        # Web Research Agent (using built-in tools)
        agent_tools_web: List[Any] = [reasoning_tools]  # Add reasoning first
        agent_tools_web.extend(notebook_tools)
        agents['web'] = Agent(
            name="Web Researcher",
            role="Expert at finding information, documentation, and solutions online with systematic reasoning",
            model=OpenRouter(
                id="openai/gpt-4.1",  # Updated to GPT 4.1
                api_key=self.settings.openrouter_api_key
            ),
            tools=agent_tools_web,
            instructions=[
                "Use reasoning tools to approach research systematically",
                "Search for relevant documentation and tutorials",
                "Find solutions to technical problems", 
                "Research best practices and industry standards",
                "Always cite sources and verify information",
                "Summarize findings in notebook cells"
            ],
            add_datetime_to_instructions=True,
            markdown=True,
            show_tool_calls=True
        )
        logger.info("Created web research agent with reasoning tools and GPT 4.1")
        
        # Report Generator Agent
        agent_tools_reporter: List[Any] = [reasoning_tools]  # Add reasoning first
        agent_tools_reporter.extend(notebook_tools)
        agents['reporter'] = Agent(
            name="Investigation Reporter",
            role="Expert at synthesizing findings into comprehensive, actionable reports with logical reasoning",
            model=OpenRouter(
                id="openai/gpt-4.1",  # Updated to GPT 4.1
                api_key=self.settings.openrouter_api_key
            ),
            tools=agent_tools_reporter,
            instructions=[
                "Use reasoning tools to systematically organize and synthesize findings",
                "Synthesize all investigation findings into clear, structured reports",
                "Provide executive summary with key insights",
                "Include specific recommendations with priority levels", 
                "Format output as professional markdown",
                "Always include sources and evidence",
                "Create comprehensive notebook documentation"
            ],
            add_datetime_to_instructions=True,
            markdown=True,
            show_tool_calls=True
        )
        logger.info("Created investigation reporter agent with reasoning tools and GPT 4.1")
        
        logger.info(f"Initialized {len(agents)} agents with reasoning capabilities: {list(agents.keys())}")
        return agents
    
    async def create_teams(self, agents: Dict[str, Agent]) -> Dict[str, Team]:
        """Create specialized teams for different investigation types with Claude Sonnet 4 coordinators"""
        
        teams = {}
        
        # Main Investigation Team (Coordinate Mode) - Claude Sonnet 4 coordinator
        available_agents = [agent for agent in agents.values() if agent is not None]
        if available_agents:
            # Convert to the expected Union type for Team members
            from typing import cast
            team_members: List[Union[Agent, Team]] = cast(List[Union[Agent, Team]], available_agents)
            
            teams['investigation'] = Team(
                name="Investigation Team",
                mode="coordinate",  # Leader coordinates task distribution
                model=OpenRouter(
                    id="anthropic/claude-sonnet-4",  # Updated to Claude Sonnet 4
                    api_key=self.settings.openrouter_api_key
                ),
                members=team_members,
                instructions=[
                    "Use systematic reasoning to coordinate thorough investigations",
                    "Delegate tasks to appropriate agents based on investigation needs",
                    "Ensure comprehensive coverage of all relevant aspects",
                    "Coordinate findings and avoid duplication of effort",
                    "Synthesize results into actionable insights with logical flow"
                ],
                success_criteria="Complete investigation with actionable insights from all relevant sources using systematic reasoning",
                enable_agentic_context=True,
                share_member_interactions=True,
                memory=self.memory,
                show_tool_calls=True,
                markdown=True
            )
            logger.info(f"Created investigation team with Claude Sonnet 4 coordinator and {len(available_agents)} GPT 4.1 agents")
        
        # Code Review Team (Collaborate Mode) - Claude Sonnet 4 coordinator
        code_agents_raw = [agents.get(key) for key in ['github', 'filesystem', 'code_search', 'python'] if agents.get(key)]
        if code_agents_raw:
            # Filter out None values and ensure proper typing
            filtered_agents = [agent for agent in code_agents_raw if agent is not None]
            code_agents: List[Union[Agent, Team]] = cast(List[Union[Agent, Team]], filtered_agents)
            
            teams['code_review'] = Team(
                name="Code Review Team",
                mode="collaborate",  # Agents discuss and reach consensus
                model=OpenRouter(
                    id="anthropic/claude-sonnet-4",  # Updated to Claude Sonnet 4
                    api_key=self.settings.openrouter_api_key
                ),
                members=code_agents,
                instructions=[
                    "Facilitate collaborative code review with systematic reasoning",
                    "Guide team discussions to reach consensus on recommendations", 
                    "Focus on actionable improvements with logical justification",
                    "Consider both static analysis and dynamic testing approaches",
                    "Ensure all perspectives are heard and synthesized effectively"
                ],
                success_criteria="Team reaches consensus on code quality assessment and recommendations through systematic analysis",
                enable_agentic_context=True,
                memory=self.memory,
                show_tool_calls=True,
                markdown=True
            )
            logger.info(f"Created code review team with Claude Sonnet 4 coordinator and {len(filtered_agents)} GPT 4.1 agents")
        
        # Log Analysis Team - Claude Sonnet 4 coordinator
        log_agents_raw = [agents.get(key) for key in ['logai', 'filesystem', 'python'] if agents.get(key)]
        if log_agents_raw:
            # Filter out None values and ensure proper typing
            filtered_log_agents = [agent for agent in log_agents_raw if agent is not None]
            log_agents: List[Union[Agent, Team]] = cast(List[Union[Agent, Team]], filtered_log_agents)
            
            teams['log_analysis'] = Team(
                name="Log Analysis Team",
                mode="coordinate",
                model=OpenRouter(
                    id="anthropic/claude-sonnet-4",  # Updated to Claude Sonnet 4
                    api_key=self.settings.openrouter_api_key
                ),
                members=log_agents,
                instructions=[
                    "Coordinate comprehensive log analysis with systematic reasoning",
                    "Direct statistical and ML approaches for anomaly detection",
                    "Correlate findings across different log sources methodically",
                    "Provide actionable recommendations for system health with clear logic"
                ],
                success_criteria="Complete log analysis with identified issues and recommendations through systematic investigation", 
                enable_agentic_context=True,
                memory=self.memory,
                show_tool_calls=True,
                markdown=True
            )
            logger.info(f"Created log analysis team with Claude Sonnet 4 coordinator and {len(filtered_log_agents)} GPT 4.1 agents")
        
        # Media Analysis Team - Claude Sonnet 4 coordinator
        media_agents_raw = [agents.get(key) for key in ['media', 'github', 'filesystem', 'code_search'] if agents.get(key)]
        if media_agents_raw:
            # Filter out None values and ensure proper typing
            filtered_media_agents = [agent for agent in media_agents_raw if agent is not None]
            media_agents: List[Union[Agent, Team]] = cast(List[Union[Agent, Team]], filtered_media_agents)
            
            teams['media_analysis'] = Team(
                name="Visual Bug Investigation Team",
                mode="coordinate",
                model=OpenRouter(
                    id="anthropic/claude-sonnet-4",  # Updated to Claude Sonnet 4
                    api_key=self.settings.openrouter_api_key
                ),
                members=media_agents,
                instructions=[
                    "Coordinate systematic analysis of visual evidence for bug investigation",
                    "Extract and correlate media content with relevant code using logical reasoning",
                    "Generate detailed timelines of user interactions and system responses", 
                    "Identify root causes based on visual evidence through systematic investigation",
                    "Provide specific code recommendations and fixes with clear justification"
                ],
                success_criteria="Complete visual bug analysis with code-level recommendations through systematic reasoning",
                enable_agentic_context=True,
                memory=self.memory,
                show_tool_calls=True,
                markdown=True
            )
            logger.info(f"Created media analysis team with Claude Sonnet 4 coordinator and {len(filtered_media_agents)} GPT 4.1 agents")
        
        logger.info(f"Created {len(teams)} teams with Claude Sonnet 4 coordinators: {list(teams.keys())}")
        return teams
    
    async def investigate(
        self,
        query: str,
        investigation_type: str = "general", 
        notebook_context: str = ""
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Main investigation method with direct media workflow integration
        """
        try:
            # Check if this is a media analysis request
            media_url_pattern = r'https?://[^\s<>"]+(?:\.[a-zA-Z0-9]+)*(?:/[^\s<>"]*)?'
            urls = re.findall(media_url_pattern, query)
            has_media_urls = any(
                any(ext in url.lower() for ext in ['.mp4', '.mov', '.avi', '.webm', '.jpg', '.jpeg', '.png', '.gif', '.bmp', 'video', 'image', 'screenshot', 'github.com/user-attachments'])
                for url in urls
            )
            
            if has_media_urls or investigation_type == "media_analysis":
                logger.info("Detected media content, running media analysis workflow")
                
                # Yield initial status
                yield {
                    "type": "status",
                    "status": "starting",
                    "message": "Starting media analysis workflow",
                    "workflow": "MediaAnalysisWorkflow"
                }
                
                # Run the media analysis workflow directly
                workflow_iterator = self.media_workflow.run(
                    query=query,
                    notebook_context=notebook_context,
                    use_cache=True
                )
                
                # Stream the workflow responses
                for response in workflow_iterator:
                    if hasattr(response, 'content') and response.content:
                        yield {
                            "type": "workflow_progress",
                            "content": response.content,
                            "workflow": "MediaAnalysisWorkflow"
                        }
                
                # Yield completion
                yield {
                    "type": "status",
                    "status": "completed",
                    "message": "Media analysis workflow completed",
                    "final": True
                }
                return
            
            # For non-media investigations, use the existing team-based approach
            # Initialize agents and teams
            agents = await self.initialize_agents()
            teams = await self.create_teams(agents)
            
            # Prepare full context
            full_context = f"""
Investigation Query: {query}

Investigation Type: {investigation_type}

Existing Notebook Context: {notebook_context}

Notebook ID: {self.notebook_id}

Please conduct a thorough investigation and provide actionable insights.
"""
            
            # Select appropriate team based on investigation type
            team_map = {
                "code_review": "code_review",
                "log_analysis": "log_analysis", 
                "media_analysis": "media_analysis",
                "general": "investigation"
            }
            
            team_key = team_map.get(investigation_type, "investigation")
            team = teams.get(team_key)
            
            if not team:
                raise ValueError(f"No team available for investigation type: {investigation_type}")
            
            logger.info(f"Starting {investigation_type} investigation with {team.name}")
            
            # Yield initial status
            yield {
                "type": "status",
                "status": "starting",
                "message": f"Starting investigation with {team.name}",
                "team": team.name,
                "agents": len(team.members)
            }
            
            # Run the investigation - Handle non-async iterator properly
            response_iterator = team.run(
                full_context,
                stream=True,
                stream_intermediate_steps=True
            )
            
            # Process the streaming response (using regular iteration, not async)
            final_response = None
            for response in response_iterator:
                final_response = response
                # Stream intermediate results if available
                yield {
                    "type": "investigation_progress",
                    "content": response.content if hasattr(response, 'content') else str(response),
                    "team": team.name
                }
            
            # Generate final report if we have a reporter
            if 'reporter' in agents and agents['reporter']:
                logger.info("Generating final comprehensive report")
                yield {
                    "type": "status", 
                    "status": "generating_report",
                    "message": "Generating comprehensive report"
                }
                
                # Get the final result content
                final_content = final_response.content if final_response and hasattr(final_response, 'content') else "Investigation completed"
                
                report_context = f"""
Original Query: {query}
Investigation Type: {investigation_type}
Investigation Findings: {final_content}

Please generate a comprehensive investigation report with:
1. Executive Summary
2. Key Findings
3. Actionable Recommendations  
4. Next Steps
5. Risk Assessment (if applicable)
"""
                
                # Handle regular iterator from reporter (not async)
                report_iterator = agents['reporter'].run(report_context, stream=True)
                report_response = None
                for response in report_iterator:
                    report_response = response
                
                yield {
                    "type": "final_report",
                    "content": report_response.content if report_response and hasattr(report_response, 'content') else "Report generation completed",
                    "final": True
                }
            
        except Exception as e:
            logger.error(f"Investigation failed: {e}", exc_info=True)
            yield {
                "type": "error",
                "error": str(e),
                "message": "Investigation failed"
            } 