import os
import requests

from typing import Any, TypeVar
from functools import cache


T = TypeVar("T")


class PhabricatorClient:
    """Phabricator API HTTP client.

    See https://phabricator.wikimedia.org/conduit for the API capability and details.

    """

    def __init__(self):
        self.base_url = os.environ["PHABRICATOR_URL"].rstrip("/")
        self.token = os.environ["PHABRICATOR_TOKEN"]
        self.session = requests.Session()
        self.timeout = 5

        if not self.base_url or not self.token:
            raise ValueError(
                "PHABRICATOR_URL and PHABRICATOR_TOKEN must be set in your envionment"
            )

    def _first(self, result_set: list[T]) -> T:
        if result_set:
            return result_set[0]

    def _make_request(
        self,
        path: str,
        params: dict[str, Any] = None,
        headers: dict[str, str] = None,
    ) -> dict[str, Any]:
        """Helper method to make API requests"""
        headers = headers or {}
        headers |= {
            "Content-Type": "application/x-www-form-urlencoded",
        }
        params = params or {}
        data = {}
        data["api.token"] = self.token
        data["output"] = "json"
        data |= params

        try:
            response = self.session.post(
                f"{self.base_url}/api/{path}",
                headers=headers,
                data=data,
                timeout=self.timeout,
            )

            response.raise_for_status()
            resp_json = response.json()
            if resp_json["error_code"]:
                raise Exception(f"API request failed: {resp_json}")
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"API request failed: {str(e)}")

    def create_or_edit_task(
        self, params: dict[str, Any], task_id: int | None = None
    ) -> dict[str, Any]:
        """Create or edit (if a task_id is provided) a Maniphest task."""
        raw_params = {}
        for i, (key, value) in enumerate(params.items()):
            raw_params[f"transactions[{i}][type]"] = key
            if isinstance(value, list):
                for j, subvalue in enumerate(value):
                    raw_params[f"transactions[{i}][value][{j}]"] = subvalue
            else:
                raw_params[f"transactions[{i}][value]"] = value
        if task_id:
            raw_params["objectIdentifier"] = task_id
        return self._make_request("maniphest.edit", params=raw_params)

    def show_task(self, task_id: int) -> dict[str, Any]:
        """Show a Maniphest task"""
        return self._make_request(
            "maniphest.search",
            params={
                "constraints[ids][0]": task_id,
                "attachments[subscribers]": "true",
                "attachments[projects]": "true",
                "attachments[columns]": "true",
            },
        )["result"]["data"][0]

    def find_subtasks(self, parent_id: int) -> list[dict[str, Any]]:
        """Return details of all Maniphest subtasks of the provided task id"""
        return self._make_request(
            "maniphest.search", params={"constraints[parentIDs][0]": parent_id}
        )["result"]["data"]

    def find_parent_task(self, subtask_id: int) -> dict[str, Any] | None:
        """Return details of the parent Maniphest task for the provided task id"""
        return self._first(
            self._make_request(
                "maniphest.search", params={"constraints[subtaskIDs][0]": subtask_id}
            )["result"]["data"]
        )

    def move_task_to_column(self, task_id: int, column_phid: str) -> dict[str, Any]:
        """Move the argument task to column of associated column id"""
        return self.create_or_edit_task(task_id=task_id, params={"column": column_phid})

    def mark_task_as_resolved(self, task_id: int) -> dict[str, Any]:
        """Set the status of the argument task to Resolved"""
        return self.create_or_edit_task(task_id=task_id, params={"status": "resolved"})

    @cache
    def show_user(self, phid: str) -> dict[str, Any] | None:
        """Show details of a Maniphest user"""
        user = self._make_request(
            "user.search", params={"constraints[phids][0]": phid}
        )["result"]["data"]
        return self._first(user)

    def show_projects(self, phids: list[str]) -> dict[str, Any]:
        """Show details of the provided Maniphest projects"""
        params = {}
        for i, phid in enumerate(phids):
            params[f"constraints[phids][{i}]"] = phid
        return self._make_request("project.search", params=params)["result"]["data"]

    def current_user(self) -> dict[str, Any]:
        """Return details of the user associated with the phabricator API token"""
        return self._make_request("user.whoami")["result"]

    def find_user_by_username(self, username: str) -> dict[str, Any] | None:
        """Return user details of the user with the provided username"""
        user = self._make_request(
            "user.search", params={"constraints[usernames][0]": username}
        )["result"]["data"]
        return self._first(user)

    def assign_task_to_user(self, task_id: int, user_phid: int) -> dict[str, Any]:
        """Set the owner of the argument task to the argument user id"""
        return self.create_or_edit_task(task_id=task_id, params={"owner": user_phid})

    def list_project_columns(
        self,
        project_phid: str,
    ) -> list[dict[str, Any]]:
        """Return the details of each column in a given project"""
        return self._make_request(
            "project.column.search", params={"constraints[projects][0]": project_phid}
        )["result"]["data"]

    def get_project_current_milestone(self, project_phid: str) -> dict[str, Any] | None:
        """Return the first non hidden column associated with a subproject.

        We assume it to be associated with the current milestone.

        """
        columns = self.list_project_columns(project_phid)
        for column in columns:
            if column["fields"]["proxyPHID"] and not column["fields"]["isHidden"]:
                return column
