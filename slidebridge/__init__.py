"""Small, dependency-free helpers for inspecting and repairing PPTX files."""

from .core import SlideBridgeError, repair, scan

__all__ = ["SlideBridgeError", "scan", "repair"]
