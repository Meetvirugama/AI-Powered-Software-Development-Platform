"""Authentication route contract placeholder.

Yug implements the OAuth and JWT endpoints on Day 2.  Keeping this router
available now makes the public API layout stable for frontend mocks.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["authentication"])
