"""Streamlit Cloud standalone entry point."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bot.dashboard.app import main
main()
