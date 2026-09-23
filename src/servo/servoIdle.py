#!/usr/bin/env python3
"""Compatibility entry point for the calm idle routine."""

try:
    from .slowIdle import main
except ImportError:
    from slowIdle import main


if __name__ == "__main__":
    main()
