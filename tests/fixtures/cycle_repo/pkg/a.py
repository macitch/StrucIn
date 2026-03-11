"""Module A."""
from . import b

def run(flag: bool) -> int:
    if flag:
        return 1
    return 0
