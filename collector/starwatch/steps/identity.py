"""Resolve identity: find the subject's official accounts from the anchor and reject namesakes.

The logic lives in `collectors/identity.py` beside the Actor client it uses; this module is the
step's entry point for the pipeline.
"""

from ..collectors.identity import (
    CheckLookalikes,
    IdentityBoard,
    ResolveIdentity,
    identity_board,
)

__all__ = ["CheckLookalikes", "IdentityBoard", "ResolveIdentity", "identity_board"]
