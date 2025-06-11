"""
Query Result Module

This module defines the base QueryResult class and its specialized subclasses for different types of queries.
"""

from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


class QueryResult(BaseModel):
    """
    Base class for query results
    
    Attributes:
        data: The primary result data
        query: The original query string
        error: Optional error message if query failed
        metadata: Additional metadata about the query result
    """
    data: Any = None
    query: str
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class MarkdownQueryResult(QueryResult):
    """Result containing markdown content."""
    query: str = "markdown generation"
    data: str = "" # Default empty string


class ToolCallRecord(BaseModel):
    """Represents a single recorded tool call with its result."""
    tool_call_id: str
    tool_name: str
    tool_args: Dict[str, Any]
    tool_result: Any # Result can be diverse


class GithubQueryResult(QueryResult):
    """
    Result from a GitHub agent tool execution.
    Stores the original tool call info and the result.
    """
    query: str = "github tool execution" # Placeholder query
    data: Any = None # Tool results can be varied
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None


class SummarizationQueryResult(BaseModel):
    """Data model for summarization results."""
    query: str = Field(..., description="The original query or context for the summary.")
    data: str = Field(..., description="The summarized text content in Markdown.")
    error: Optional[str] = Field(None, description="Any error message if summarization failed.")


# --- Investigation Report Models ---

class CodeReference(BaseModel):
    """Reference to a specific piece of code."""
    file_path: str = Field(..., description="Relative or absolute path to the code file.")
    line_number: Optional[int] = Field(None, description="Specific line number, if applicable.")
    code_snippet: Optional[str] = Field(None, description="A small relevant snippet of the code.")
    url: Optional[str] = Field(None, description="Direct URL to the code line/file (e.g., on GitHub).")
    component_name: Optional[str] = Field(None, description="Name of the class, function, or component.")

class Finding(BaseModel):
    """A specific finding or analysis point in the investigation."""
    summary: str = Field(..., description="Concise summary of the finding.")
    details: Optional[str] = Field(None, description="More detailed explanation or context.")
    code_reference: Optional[CodeReference] = Field(None, description="Code reference directly related to this finding.")
    supporting_quotes: Optional[List[str]] = Field(None, description="Direct quotes (e.g., from comments, docs) supporting the finding.")

class RelatedItem(BaseModel):
    """Reference to a related entity like an issue, PR, or commit."""
    type: Literal["Pull Request", "Issue", "Commit", "Discussion", "Documentation", "Other"] = Field(..., description="The type of related item.")
    identifier: str = Field(..., description="Unique identifier (e.g., '#9550', 'PR #8971', commit hash).")
    url: str = Field(..., description="URL to the related item.")
    relevance: Optional[str] = Field(None, description="Brief explanation of why this item is relevant.")
    status: Optional[str] = Field(None, description="Current status if applicable (e.g., 'Open', 'Closed', 'Merged').")


class InvestigationReport(BaseModel):
    """Structured report for an investigation query, designed for rich frontend rendering."""
    query: str = Field(..., description="The original investigation request.")
    title: str = Field(..., description="Overall title for the investigation report (e.g., 'Analysis of Issue #9550').")
    status: Optional[str] = Field(None, description="Overall status of the subject being investigated (e.g., 'Open', 'Closed', 'Acknowledged').")
    status_reason: Optional[str] = Field(None, description="Reason for the status (e.g., 'Acknowledged by maintainer', 'Fix merged in PR #ABC').")
    estimated_severity: Optional[Literal["Critical", "High", "Medium", "Low", "Unknown"]] = Field(None, description="Estimated severity of the issue.")
    
    issue_summary: Finding = Field(..., description="High-level summary of the core issue.")
    root_cause: Finding = Field(..., description="Analysis of the likely root cause.")
    root_cause_confidence: Optional[Literal["Low", "Medium", "High"]] = Field(None, description="Confidence level in the root cause analysis.")
    
    key_components: List[CodeReference] = Field([], description="List of main code files/classes involved.")
    related_items: List[RelatedItem] = Field([], description="Links to related PRs, issues, discussions, etc.")
    
    proposed_fix: Optional[Finding] = Field(None, description="Details of a potential or implemented solution.")
    proposed_fix_confidence: Optional[Literal["Low", "Medium", "High"]] = Field(None, description="Confidence level in the proposed fix.")
    
    affected_context: Optional[Finding] = Field(None, description="Information on affected versions, devices, environments, etc.")
    
    suggested_next_steps: List[str] = Field([], description="Actionable suggestions for the user.")
    tags: List[str] = Field([], description="Relevant keywords or tags for categorization.")

    error: Optional[str] = Field(None, description="Any error encountered during the investigation or report generation process.")