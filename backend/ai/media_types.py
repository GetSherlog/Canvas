"""
Shared media types to avoid circular imports between investigation_system and media_analysis_workflow
"""
from typing import NamedTuple

class MediaUrl(NamedTuple):
    url: str
    type: str  # "video" or "image" 