"""
Frappe REST API client for the Pick Note Print Service.

Communicates with a remote Frappe site to:
  - Test connectivity and authentication
  - Fetch available branches
  - Retrieve unprinted Pick Notes
  - Get rendered print format output for a Pick Note
  - Mark a Pick Note as printed
"""

import requests
from typing import Any, Optional


class FrappeClient:
    """
    A lightweight REST client for the Frappe Pick Note Print API.

    Uses token-based authentication (API token).
    """

    # Base path for all custom Pick Note print API methods
    API_BASE = "/api/method/amex.amex.utils.pick_note_print_api"

    def __init__(self, frappe_url: str, api_token: str) -> None:
        """
        Initialise the client.

        Args:
            frappe_url: Root URL of the Frappe site (e.g. "https://erp.example.com").
            api_token:  API token in the format "key:secret".
        """
        self.frappe_url = frappe_url.rstrip("/")
        self.api_token = api_token

        # Reusable session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {self.api_token}",
            "Accept": "application/json",
        })
        # Reasonable timeouts: (connect, read)
        self.timeout = (10, 30)

    # ------------------------------------------------------------------ #
    #  Helper
    # ------------------------------------------------------------------ #

    def _url(self, path: str) -> str:
        """Build an absolute URL from a relative API path."""
        return f"{self.frappe_url}{path}"

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        """
        Perform a GET request and return the parsed JSON response.

        Raises:
            ConnectionError: On network-level failures.
            ValueError:      On unexpected/non-JSON responses.
            RuntimeError:    On HTTP error status codes.
        """
        try:
            resp = self.session.get(
                self._url(path), params=params, timeout=self.timeout
            )
        except requests.ConnectionError as exc:
            raise ConnectionError(
                f"Cannot connect to {self.frappe_url}: {exc}"
            ) from exc
        except requests.Timeout as exc:
            raise ConnectionError(
                f"Request timed out for {path}: {exc}"
            ) from exc
        except requests.RequestException as exc:
            raise ConnectionError(
                f"Request failed for {path}: {exc}"
            ) from exc

        if resp.status_code != 200:
            # Try to extract Frappe's server-side error message
            try:
                detail = resp.json().get("exc", resp.text[:300])
            except Exception:
                detail = resp.text[:300]
            raise RuntimeError(
                f"HTTP {resp.status_code} from {path}: {detail}"
            )

        try:
            return resp.json()
        except ValueError as exc:
            raise ValueError(
                f"Non-JSON response from {path}: {resp.text[:200]}"
            ) from exc

    def _post(self, path: str, data: Optional[dict] = None) -> Any:
        """
        Perform a POST request and return the parsed JSON response.

        Raises the same exceptions as ``_get``.
        """
        try:
            resp = self.session.post(
                self._url(path), json=data, timeout=self.timeout
            )
        except requests.ConnectionError as exc:
            raise ConnectionError(
                f"Cannot connect to {self.frappe_url}: {exc}"
            ) from exc
        except requests.Timeout as exc:
            raise ConnectionError(
                f"Request timed out for {path}: {exc}"
            ) from exc
        except requests.RequestException as exc:
            raise ConnectionError(
                f"Request failed for {path}: {exc}"
            ) from exc

        if resp.status_code not in (200, 201):
            try:
                detail = resp.json().get("exc", resp.text[:300])
            except Exception:
                detail = resp.text[:300]
            raise RuntimeError(
                f"HTTP {resp.status_code} from {path}: {detail}"
            )

        try:
            return resp.json()
        except ValueError as exc:
            raise ValueError(
                f"Non-JSON response from {path}: {resp.text[:200]}"
            ) from exc

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def test_connection(self) -> dict:
        """
        Test connectivity and authentication against the Frappe site.

        Calls ``frappe.auth.get_logged_user`` which returns the
        currently authenticated user's email.

        Returns:
            dict: e.g. ``{"user": "admin@example.com"}``

        Raises:
            ConnectionError / RuntimeError on failure.
        """
        result = self._get("/api/method/frappe.auth.get_logged_user")
        user = result.get("message", "unknown")
        return {"user": user, "status": "connected"}

    def get_branches(self) -> list[dict]:
        """
        Retrieve the list of branches available for Pick Note filtering.

        Returns:
            list: A list of branch dicts as returned by the server.
        """
        result = self._get(f"{self.API_BASE}.get_branches")
        message = result.get("message", [])
        # Normalise — the API may return a list of strings or dicts
        if message and isinstance(message[0], str):
            return [{"name": b} for b in message]
        return message

    def get_unprinted_pick_notes(self, branch: str, limit: int = 5) -> list[dict]:
        """
        Fetch unprinted Pick Notes for the given branch.

        Args:
            branch: The branch name to filter on.
            limit:  Maximum number of Pick Notes to return.

        Returns:
            list: Pick Note records (dicts with at least a ``name`` key).
        """
        result = self._get(
            f"{self.API_BASE}.get_unprinted_pick_notes",
            params={"branch": branch, "limit": limit},
        )
        return result.get("message", [])

    def get_pick_note_data(self, pick_note_name: str) -> dict:
        """
        Fetch the full Pick Note document data including child items.

        Uses the standard Frappe REST resource API to get all fields.

        Args:
            pick_note_name: The ``name`` of the Pick Note document.

        Returns:
            dict: The full document data including child table items.
        """
        result = self._get(
            f"/api/resource/Pick Note/{pick_note_name}",
        )
        return result.get("data", {})

    def get_value(
        self, doctype: str, name: str, fieldname: str
    ) -> Any:
        """
        Fetch a single field value from a Frappe document.

        Args:
            doctype:   The DocType name (e.g. "User", "Warehouse").
            name:      The document name/ID.
            fieldname: The field to retrieve.

        Returns:
            The field value, or empty string on failure.
        """
        try:
            result = self._get(
                f"/api/resource/{doctype}/{name}",
                params={"fields": f'["{fieldname}"]'},
            )
            return result.get("data", {}).get(fieldname, "")
        except Exception:
            return ""

    def get_pick_note_print_raw(
        self, pick_note_name: str, print_format: Optional[str] = None
    ) -> str:
        """
        Get the rendered print output for a specific Pick Note.

        Args:
            pick_note_name: The ``name`` of the Pick Note document.
            print_format:   Optional Frappe print format name to use.

        Returns:
            str: The raw/rendered print content (may contain HTML).
        """
        params: dict[str, Any] = {"pick_note_name": pick_note_name}
        if print_format:
            params["print_format"] = print_format

        result = self._get(
            f"{self.API_BASE}.get_pick_note_print_raw",
            params=params,
        )
        return result.get("message", "")

    def get_print_formats(self) -> dict:
        """
        Fetch available Print Formats for the Pick Note doctype and
        determine the default print format from Property Setter.

        Returns:
            dict with keys:
                - formats: list of dicts with 'name' and 'raw_printing' keys
                - default: the default print format name (or empty string)
        """
        # 1. Get all Print Formats for Pick Note
        result = self._get(
            "/api/resource/Print Format",
            params={
                "filters": '[["doc_type","=","Pick Note"]]',
                "fields": '["name","raw_printing"]',
                "limit_page_length": 0,
            },
        )
        formats = result.get("data", [])

        # 2. Get the default print format from Property Setter
        default_format = ""
        try:
            ps_result = self._get(
                "/api/resource/Property Setter",
                params={
                    "filters": '["doc_type","=","Pick Note"],["property","=","default_print_format"]',
                    "fields": '["value"]',
                    "limit_page_length": 1,
                },
            )
            ps_data = ps_result.get("data", [])
            if ps_data:
                default_format = ps_data[0].get("value", "")
        except Exception:
            pass  # Property Setter may not exist yet

        return {
            "formats": formats,
            "default": default_format,
        }

    def mark_printed(self, pick_note_name: str) -> dict:
        """
        Mark a Pick Note as printed on the Frappe site.

        Args:
            pick_note_name: The ``name`` of the Pick Note to mark.

        Returns:
            dict: The server response message.
        """
        result = self._post(
            f"{self.API_BASE}.mark_pick_note_printed",
            data={"pick_note_name": pick_note_name},
        )
        return result.get("message", {"status": "ok"})
