"""Loop prevention package.

Public entry points are :class:`LoopGuard` and :class:`Decision`.
"""
from tgmgmt.loop_guard.middleware import Decision, LoopGuard, Verdict

__all__ = ["Decision", "LoopGuard", "Verdict"]
