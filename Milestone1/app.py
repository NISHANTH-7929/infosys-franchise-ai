"""
Infosys Springboard - Milestone 1 Runner
Executes src/app.py directly using runpy to ensure full Streamlit state rerun compatibility.
"""
import runpy
from pathlib import Path

target = Path(__file__).resolve().parent / "src" / "app.py"
runpy.run_path(str(target), run_name="__main__")
