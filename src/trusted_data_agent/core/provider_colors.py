# src/trusted_data_agent/core/provider_colors.py
"""
Provider and profile type color mapping for visual identification throughout the UI.
- Profile types (Genie, RAG, etc.) get priority color assignment for consistency
- Provider colors are used as fallback for standard profiles
"""

# Profile type color schemes (take priority over provider colors)
# These ensure consistent visual identification of profile classes
# CORRECTED IFOC COLOR MAPPING: Ideate=Green, Focus=Blue, Optimize=Purple, Coordinate=Orange
PROFILE_TYPE_COLORS = {
    "llm_only": {
        "primary": "#4ade80",     # Green (Ideate - conversation/brainstorming)
        "secondary": "#86efac",   # Lighter green
        "name": "Conversation Focused (LLM)"
    },
    "rag_focused": {
        "primary": "#3b82f6",     # Blue (Focus - knowledge retrieval)
        "secondary": "#93c5fd",   # Lighter blue
        "name": "Knowledge Focused (RAG)"
    },
    "tool_enabled": {
        "primary": "#9333ea",     # Purple (Optimize - efficiency/execution)
        "secondary": "#a855f7",   # Lighter purple
        "name": "Efficiency Focused (Tool)"
    },
    "genie": {
        "primary": "#F15F22",     # Orange (Coordinate - multi-profile orchestration, Teradata brand)
        "secondary": "#f97316",   # Lighter orange
        "name": "Genie (Multi-Profile)"
    }
}

# Provider color schemes: primary color and lighter variant for gradients
PROVIDER_COLORS = {
    "google": {
        "primary": "#4285f4",     # Google Blue
        "secondary": "#669df6",   # Lighter blue
        "name": "Google"
    },
    "anthropic": {
        "primary": "#8b5cf6",     # Purple
        "secondary": "#a78bfa",   # Lighter purple
        "name": "Anthropic"
    },
    "openai": {
        "primary": "#10a37f",     # OpenAI Green
        "secondary": "#1ec99b",   # Lighter green
        "name": "OpenAI"
    },
    "amazon_bedrock": {
        "primary": "#ff9900",     # AWS Orange
        "secondary": "#ffb84d",   # Lighter orange
        "name": "Amazon Bedrock"
    },
    "azure": {
        "primary": "#00bfff",     # Azure Cyan
        "secondary": "#4dd2ff",   # Lighter cyan
        "name": "Azure"
    },
    "friendli": {
        "primary": "#ec4899",     # Pink
        "secondary": "#f472b6",   # Lighter pink
        "name": "Friendli"
    },
    "ollama": {
        "primary": "#64748b",     # Slate gray
        "secondary": "#94a3b8",   # Lighter gray
        "name": "Ollama"
    }
}

def get_provider_color(provider: str) -> dict:
    """
    Get color scheme for a provider.
    
    Args:
        provider: Provider name (case-insensitive)
        
    Returns:
        Dictionary with 'primary', 'secondary', and 'name' keys
        Returns a default gray scheme if provider not found
    """
    provider_lower = provider.lower() if provider else ""
    
    return PROVIDER_COLORS.get(provider_lower, {
        "primary": "#6b7280",     # Default gray
        "secondary": "#9ca3af",   # Lighter gray
        "name": provider or "Unknown"
    })

def get_provider_from_llm_config(llm_config: dict) -> str:
    """
    Extract provider name from LLM configuration.

    Args:
        llm_config: LLM configuration dictionary

    Returns:
        Provider name in lowercase
    """
    return (llm_config.get("provider") or "").lower()

def get_profile_colors(profile_type: str, provider: str = None) -> dict:
    """
    Get color scheme for a profile based on type.

    CORRECTED IFOC color mapping:
    - llm_only (Ideate) = Green #4ade80
    - rag_focused (Focus) = Blue #3b82f6
    - tool_enabled (Optimize) = Purple #9333ea
    - genie (Coordinate) = Orange #F15F22 (Teradata brand)

    Args:
        profile_type: Profile type ("genie", "rag_focused", "llm_only", "tool_enabled")
        provider: Optional provider name (no longer used for coloring, kept for compatibility)

    Returns:
        Dictionary with 'primary', 'secondary', and 'name' keys
    """
    # All profile types have explicit colors
    if profile_type and profile_type in PROFILE_TYPE_COLORS:
        type_colors = PROFILE_TYPE_COLORS[profile_type]
        if type_colors is not None:
            return type_colors

    # Fallback to provider color (legacy, should not be reached)
    if provider:
        return get_provider_color(provider)

    # Priority 3: Default gray
    return {
        "primary": "#6b7280",
        "secondary": "#9ca3af",
        "name": "Unknown"
    }
