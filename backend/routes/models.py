from fastapi import APIRouter, HTTPException
from typing import List, Dict
from pydantic import BaseModel
from backend.config import get_settings

router = APIRouter(tags=["models"])

class ModelConfig(BaseModel):
    model_id: str

AVAILABLE_MODELS = [
    {
        "id": "anthropic/claude-3.7-sonnet",
        "name": "Claude 3.7 Sonnet",
        "provider": "Anthropic",
        "description": "Anthropic's Claude 3.7 Sonnet model"
    },
    {
        "id": "google/gemini-2.5-pro-preview-03-25",
        "name": "Gemini 2.5 Pro",
        "provider": "Google",
        "description": "Google's Gemini 2.5 Pro model"
    },
    {
        "id": "openai/gpt-4.1",
        "name": "GPT-4.1",
        "provider": "OpenAI",
        "description": "OpenAI's GPT-4.1 model"
    }
]

@router.get("/", response_model=List[Dict[str, str]])
async def list_models():
    """
    List all available models that can be used with the system.
    Returns a list of models with their IDs, names, providers, and descriptions.
    """
    return AVAILABLE_MODELS

@router.get("/current", response_model=Dict[str, str])
async def get_current_model():
    """
    Get the currently selected model.
    """
    settings = get_settings()
    current_model = next((model for model in AVAILABLE_MODELS if model["id"] == settings.ai_model), None)
    if not current_model:
        raise HTTPException(status_code=404, detail="No model currently selected")
    return current_model

@router.post("/current", response_model=Dict[str, str])
async def set_current_model(model_config: ModelConfig):
    """
    Set the current model to be used by the system.
    """
    # Validate that the model exists
    if not any(model["id"] == model_config.model_id for model in AVAILABLE_MODELS):
        raise HTTPException(status_code=400, detail="Invalid model ID")
    
    # Update the environment variable
    settings = get_settings()
    settings.ai_model = model_config.model_id
    
    # Return the selected model details
    selected_model = next(model for model in AVAILABLE_MODELS if model["id"] == model_config.model_id)
    return selected_model 