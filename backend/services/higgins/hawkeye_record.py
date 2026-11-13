"""Compatibility reads for the single retained Hawkeye investigation record.

New writes use Hawkeye names. Historical FlyBy records remain readable without
copying evidence or maintaining a second investigative authority.
"""
from services.higgins import repository as repo


def read(case: dict) -> dict:
    value = case.get("tc_hawkeye_ciphertext") or case.get("tc_flyby_ciphertext")
    return repo.dec_json(value) if value else {}


def routing(case: dict) -> dict:
    routes = case.get("routing") or {}
    return routes.get("tc_hawkeye") or routes.get("tc_flyby") or {}
