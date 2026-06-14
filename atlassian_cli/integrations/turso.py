from __future__ import annotations

from typing import Optional

import requests


def _to_arg(value) -> dict:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    return {"type": "text", "value": str(value)}


def _from_value(cell: dict):
    t = cell["type"]
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    return cell.get("value")


class TursoCursor:
    def __init__(self, cols: list[str], rows: list[tuple]):
        self.description = [(col,) for col in cols]
        self._rows = rows
        self._idx = 0

    def fetchall(self) -> list[tuple]:
        return self._rows

    def fetchone(self) -> Optional[tuple]:
        if self._idx < len(self._rows):
            row = self._rows[self._idx]
            self._idx += 1
            return row
        return None


class TursoHttpClient:
    """Thin HTTP client for Turso that mimics the sqlite3 connection interface."""

    def __init__(self, url: str, auth_token: str):
        self._url = url.replace("libsql://", "https://") + "/v2/pipeline"
        self._headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }

    def execute(self, sql: str, params: tuple = ()) -> TursoCursor:
        args = [_to_arg(p) for p in params]
        payload = {
            "requests": [
                {"type": "execute", "stmt": {"sql": sql, "args": args}},
                {"type": "close"},
            ]
        }
        resp = requests.post(self._url, json=payload, headers=self._headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result = data["results"][0]
        if result["type"] == "error":
            raise RuntimeError(result.get("error", {}).get("message", "Turso error"))
        execute_result = result["response"]["result"]
        cols = [c["name"] for c in execute_result.get("cols", [])]
        rows = [
            tuple(_from_value(cell) for cell in row)
            for row in execute_result.get("rows", [])
        ]
        return TursoCursor(cols, rows)

    def commit(self) -> None:
        pass  # HTTP API auto-commits each request
