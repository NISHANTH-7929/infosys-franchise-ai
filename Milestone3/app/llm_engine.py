"""Shim so the domain modules can ask the GPU LLM for a narrative. In the background worker process no LLM is loaded, so they use their template (the server writes the GPU executive brief on demand)."""
import gpu
def is_llm_loaded(): return gpu.llm_ready()
def generate_text(messages, max_new_tokens=160, temperature=0.1): return gpu.llm_text(messages, max_new_tokens=max_new_tokens, temperature=temperature)
