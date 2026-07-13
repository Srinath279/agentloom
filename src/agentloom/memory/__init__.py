"""Planned: agent memory — persistent state across workflow runs.

Intended shape: read/write activities backed by a store (vector DB or
key-value), keyed by agent + session, so workflows stay deterministic while
memory I/O happens in activities. See docs/roadmap.md.
"""
