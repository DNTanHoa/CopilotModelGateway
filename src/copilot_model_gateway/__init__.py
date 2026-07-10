"""Copilot Model Gateway package."""

from . import ollama_bridge as _ollama_bridge
from .visual_studio_bridge import start_ollama_bridge_thread as _start_visual_studio_bridge

__version__ = "0.3.0"

# The CLI imports this symbol from ollama_bridge. Replace it during package
# initialization so Visual Studio receives both Ollama-native and OpenAI-style
# chat endpoints on the same localhost port.
_ollama_bridge.start_ollama_bridge_thread = _start_visual_studio_bridge
