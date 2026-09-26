"""PyInstaller / `python run_capture.py` entry point."""
import sys

from capture_tool.app.main import main

if __name__ == "__main__":
    sys.exit(main())
