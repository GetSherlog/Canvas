"""
Media Analysis Workflow using Agno
Converts the media URL extraction, analysis, and code correlation process into a structured workflow.
"""
import logging
import re
import asyncio
from typing import Iterator, List, Optional, Dict, Any
from datetime import datetime

from agno.workflow import Workflow, RunResponse, RunEvent
from agno.agent import Agent
from agno.models.openrouter import OpenRouter
from agno.storage.sqlite import SqliteStorage
from pydantic import BaseModel, Field

from backend.ai.media_describer_agent import MediaDescriberAgent, MediaUrl as MediaDescriberUrl, UrlType
from backend.config import get_settings
from backend.ai.media_types import MediaUrl

logger = logging.getLogger("ai.media_workflow")

class MediaUrlList(BaseModel):
    media_urls: List[MediaUrl] = Field(default=[], description="List of extracted media URLs")
    extraction_notes: str = Field(..., description="Notes about the extraction process")

class MediaAnalysisResult(BaseModel):
    hypothesis: str = Field(..., description="Analysis hypothesis about the bug or issue")
    timeline_events: List[Dict[str, Any]] = Field(default=[], description="Timeline of events from media analysis")
    summary: str = Field(..., description="Summary of media analysis findings")

class CodeCorrelationResult(BaseModel):
    correlation_summary: str = Field(..., description="Summary of how media evidence correlates with code")
    recommended_investigations: List[str] = Field(default=[], description="Specific areas to investigate in code")
    potential_root_causes: List[str] = Field(default=[], description="Potential root causes identified")

class MediaAnalysisWorkflow(Workflow):
    """
    Workflow for analyzing media content (screenshots, videos) to investigate bugs.
    
    This workflow orchestrates:
    1. URL extraction from user queries
    2. Media content analysis using vision models
    3. Code correlation and hypothesis generation
    """
    
    description: str = "Analyze screenshots and videos to investigate software bugs and generate actionable insights"
    
    def __init__(self, notebook_id: str, **kwargs):
        # Initialize with SQLite storage for caching
        storage = SqliteStorage(
            table_name=f"media_analysis_workflow_{notebook_id.replace('-', '_')}",
            db_file="data/investigation_workflows.db"
        )
        
        # Get settings for API key
        self.settings = get_settings()
        
        # URL Extraction Agent
        self.url_extractor: Agent = Agent(
            name="Media URL Extractor",
            role="Expert at identifying and extracting media URLs from text",
            model=OpenRouter(
                id="openai/gpt-4o-mini",
                api_key=self.settings.openrouter_api_key
            ),
            description="Specialized in finding and categorizing media URLs in user queries and content",
            instructions=[
                "Extract all media URLs (images, videos, screenshots) from the provided text",
                "Classify each URL as 'video' or 'image' based on file extensions and context",
                "Look for GitHub user-attachments, direct image/video links, and embedded media",
                "Provide detailed notes about what was found and any extraction challenges",
                "Return empty list if no media URLs are found"
            ],
            response_model=MediaUrlList,
            add_datetime_to_instructions=True,
            markdown=True
        )
        
        # Media Analysis Agent  
        self.media_analyzer: Agent = Agent(
            name="Visual Bug Analyzer",
            role="Expert at analyzing visual content to identify software bugs and user experience issues",
            model=OpenRouter(
                id="anthropic/claude-3-5-sonnet-20241022",
                api_key=self.settings.openrouter_api_key
            ),
            description="Specialized in extracting actionable insights from screenshots and videos for bug investigation",
            instructions=[
                "Analyze provided media content to identify visual bugs, UI issues, and user experience problems",
                "Generate detailed timeline of events shown in the media",
                "Create hypothesis about what might be causing the observed issues",
                "Focus on actionable insights that can guide code investigation",
                "Look for patterns, anomalies, and specific UI elements that seem problematic"
            ],
            response_model=MediaAnalysisResult,
            add_datetime_to_instructions=True,
            markdown=True
        )
        
        # Code Correlation Agent
        self.code_correlator: Agent = Agent(
            name="Code Correlation Specialist", 
            role="Expert at connecting visual evidence with potential code issues",
            model=OpenRouter(
                id="anthropic/claude-3-5-sonnet-20241022",
                api_key=self.settings.openrouter_api_key
            ),
            description="Specialized in bridging the gap between visual bugs and underlying code problems",
            instructions=[
                "Correlate visual evidence from media analysis with potential code issues",
                "Suggest specific code areas, components, or patterns to investigate",
                "Generate hypothesis about root causes based on visual evidence",
                "Provide actionable recommendations for developers",
                "Consider common patterns: CSS issues, JavaScript errors, state management, API problems",
                "Prioritize investigations based on severity and likelihood"
            ],
            response_model=CodeCorrelationResult,
            add_datetime_to_instructions=True,
            markdown=True
        )
        
        super().__init__(
            session_id=f"media-analysis-{notebook_id}",
            storage=storage,
            **kwargs
        )
        
        # Initialize the media describer for actual vision analysis
        self.media_describer = MediaDescriberAgent()
        self.notebook_id = notebook_id
        
        logger.info(f"MediaAnalysisWorkflow initialized for notebook {notebook_id}")
    
    def get_cached_analysis(self, query: str) -> Optional[str]:
        """Check if we have a cached analysis for this query"""
        if "analyses" in self.session_state:
            for cached_analysis in self.session_state["analyses"]:
                if cached_analysis["query"] == query:
                    logger.info("Found cached media analysis")
                    return cached_analysis["result"]
        return None
    
    def cache_analysis(self, query: str, result: str):
        """Cache the analysis result"""
        if "analyses" not in self.session_state:
            self.session_state["analyses"] = []
        
        self.session_state["analyses"].append({
            "query": query,
            "result": result,
            "timestamp": datetime.now().isoformat()
        })
    
    async def perform_vision_analysis(self, media_urls: List[MediaUrl], original_query: str) -> MediaAnalysisResult:
        """Perform actual vision analysis using MediaDescriberAgent"""
        try:
            logger.info(f"Performing vision analysis on {len(media_urls)} media items")
            
            # Convert workflow MediaUrl objects to MediaDescriberAgent format
            media_objects = []
            for m in media_urls:
                url_type = UrlType.VIDEO if m.type.lower() == "video" else UrlType.IMAGE
                media_objects.append(MediaDescriberUrl(url=m.url, type=url_type))
            
            # Run the actual vision analysis
            timeline_payload = await self.media_describer.describe_media(original_query, media_objects)
            
            # Convert to our response model format
            timeline_events = []
            for event in timeline_payload.timeline_events:
                timeline_events.append({
                    "image_identifier": event.image_identifier,
                    "description": event.description,
                    "code_references": event.code_references or []
                })
            
            return MediaAnalysisResult(
                hypothesis=timeline_payload.hypothesis,
                timeline_events=timeline_events,
                summary=f"Analyzed {len(media_urls)} media items. Found {len(timeline_events)} significant events."
            )
            
        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            return MediaAnalysisResult(
                hypothesis="Vision analysis failed",
                timeline_events=[],
                summary=f"Error during analysis: {str(e)}"
            )
    
    def run(
        self, 
        query: str, 
        notebook_context: str = "",
        use_cache: bool = True
    ) -> Iterator[RunResponse]:
        """
        Main workflow execution method
        
        Args:
            query: User query containing media URLs and description of the issue
            notebook_context: Additional context from the notebook
            use_cache: Whether to use cached results
        """
        logger.info(f"Starting media analysis workflow for query: {query[:100]}...")
        
        # Check cache first
        if use_cache:
            cached_result = self.get_cached_analysis(query)
            if cached_result:
                yield RunResponse(
                    content=cached_result,
                    event=RunEvent.workflow_completed
                )
                return
        
        # Step 1: Extract media URLs
        logger.info("Step 1: Extracting media URLs from query")
        yield RunResponse(
            content="🔍 **Step 1:** Extracting media URLs from query..."
        )
        
        url_extraction_input = f"""
        User Query: {query}
        
        Additional Context: {notebook_context}
        
        Please extract all media URLs (images, videos, screenshots) from this content.
        """
        
        url_response = self.url_extractor.run(url_extraction_input)
        if not url_response or not url_response.content:
            yield RunResponse(
                content="❌ No media URLs found in the query",
                event=RunEvent.workflow_completed
            )
            return
        
        media_urls: MediaUrlList = url_response.content
        
        if not media_urls.media_urls:
            yield RunResponse(
                content=f"❌ No media URLs extracted. {media_urls.extraction_notes}",
                event=RunEvent.workflow_completed  
            )
            return
        
        yield RunResponse(
            content=f"✅ **Found {len(media_urls.media_urls)} media URLs:**\n" + 
                   "\n".join([f"- {url.url} ({url.type})" for url in media_urls.media_urls]) +
                   f"\n\n📝 {media_urls.extraction_notes}"
        )
        
        # Step 2: Analyze media content using vision models
        logger.info("Step 2: Analyzing media content with vision models")
        yield RunResponse(
            content="🔬 **Step 2:** Analyzing media content with vision models..."
        )
        
        # Perform actual vision analysis
        try:
            # Run async vision analysis in a new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                media_analysis = loop.run_until_complete(
                    self.perform_vision_analysis(media_urls.media_urls, query)
                )
            finally:
                loop.close()
                
        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            yield RunResponse(
                content=f"❌ Vision analysis failed: {str(e)}",
                event=RunEvent.workflow_completed
            )
            return
        
        yield RunResponse(
            content=f"✅ **Media Analysis Complete:**\n\n" +
                   f"**Hypothesis:** {media_analysis.hypothesis}\n\n" +
                   f"**Timeline Events:** {len(media_analysis.timeline_events)}\n\n" +
                   f"**Summary:** {media_analysis.summary}"
        )
        
        # Step 3: Correlate with code and generate recommendations
        logger.info("Step 3: Correlating media evidence with code")
        yield RunResponse(
            content="🔗 **Step 3:** Correlating visual evidence with potential code issues..."
        )
        
        correlation_input = f"""
        Original Query: {query}
        
        Media Analysis Results:
        - Hypothesis: {media_analysis.hypothesis}
        - Timeline Events: {len(media_analysis.timeline_events)} events found
        - Summary: {media_analysis.summary}
        
        Timeline Events Details:
        {chr(10).join([f"• {event['image_identifier']}: {event['description']}" for event in media_analysis.timeline_events])}
        
        Notebook Context: {notebook_context}
        
        Please correlate this visual evidence with potential code issues and provide actionable recommendations.
        """
        
        correlation_response = self.code_correlator.run(correlation_input)
        if not correlation_response or not correlation_response.content:
            yield RunResponse(
                content="❌ Failed to generate code correlation",
                event=RunEvent.workflow_completed
            )
            return
        
        code_correlation: CodeCorrelationResult = correlation_response.content
        
        # Generate final comprehensive report
        final_report = f"""# 🔍 Media Analysis Investigation Report

## 📊 Executive Summary
{media_analysis.hypothesis}

## 🎯 Media Evidence Analysis
**Analyzed {len(media_urls.media_urls)} media items:**
{chr(10).join([f"- {url.url} ({url.type})" for url in media_urls.media_urls])}

**Key Findings:**
{media_analysis.summary}

## ⏱️ Timeline of Events
{chr(10).join([f"{i+1}. **{event['image_identifier']}**: {event['description']}" for i, event in enumerate(media_analysis.timeline_events)])}

## 🧭 Code Correlation & Recommendations

### 🔗 How Visual Evidence Correlates with Code
{code_correlation.correlation_summary}

### 🎯 Recommended Investigations
{chr(10).join([f"- {rec}" for rec in code_correlation.recommended_investigations])}

### 🚨 Potential Root Causes  
{chr(10).join([f"- {cause}" for cause in code_correlation.potential_root_causes])}

## 🔄 Next Steps
1. Use the GitHub and filesystem tools to examine the recommended code areas
2. Look for the specific patterns identified in the analysis
3. Check recent commits that might have introduced these issues
4. Consider implementing monitoring for the identified problem areas

---
*Analysis completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
        
        # Cache the final result
        if use_cache:
            self.cache_analysis(query, final_report)
        
        yield RunResponse(
            content=final_report,
            event=RunEvent.workflow_completed
        ) 