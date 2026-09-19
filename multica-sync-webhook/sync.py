#!/usr/bin/env python3
"""Converge Multica entities from a Gitea push webhook.

Reads a Gitea push payload (file path, argv JSON string, or stdin), fetches each
changed file at the pushed commit via the Gitea API, and drives the matching
Multica entity (agent / skill / squad / autopilot) to the repo content via the
Multica REST API.

Convergence is name-driven and safe: live entities are only overwritten when
their current content still equals the repo's pre-push version; anything else
is BLOCKed for a human instead of silently clobbered.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

MAIN_REF = "refs/heads/main"
ENTITY_DIRS = ("agents/", "skills/", "squads/", "autopilots/")
AUTOPILOT_ID_RE = re.compile(r"^(.*)-([0-9a-fA-F]{8})$")

GITEA_DEFAULT_BASE = "https://gitea.tsic.top/api/v1"
GITEA_DEFAULT_REPO = "tsic/multica-agent"
MULTICA_DEFAULT_BASE = "https://multica.tsic.top"


class SyncError(Exception):
    """Fatal setup/payload error; aborts the whole run."""


class HttpError(Exception):
    """Non-2xx response from Gitea or Multica."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


@dataclass(frozen=True)
class Config:
    gitea_token: str
    gitea_base: str
    gitea_repo: str
    multica_token: str
    multica_base: str
    workspace_id: str
    agent_runtime_id: str
    squad_leader_id: str
    autopilot_agent_id: str
    autopilot_mode: str

    @classmethod
    def from_env(cls) -> "Config":
        def required(name: str) -> str:
            value = os.environ.get(name, "").strip()
            if not value:
                raise SyncError(f"missing required env var {name}")
            return value

        return cls(
            gitea_token=required("GITEA_TOKEN"),
            gitea_base=os.environ.get("GITEA_BASE_URL", GITEA_DEFAULT_BASE).rstrip("/"),
            gitea_repo=os.environ.get("GITEA_REPO", GITEA_DEFAULT_REPO),
            multica_token=required("MULTICA_API_TOKEN"),
            multica_base=os.environ.get(
                "MULTICA_API_BASE_URL", MULTICA_DEFAULT_BASE
            ).rstrip("/"),
            workspace_id=required("MULTICA_WORKSPACE_ID"),
            agent_runtime_id=os.environ.get("MULTICA_RUNTIME_ID", "").strip(),
            squad_leader_id=os.environ.get("MULTICA_SQUAD_LEADER_ID", "").strip(),
            autopilot_agent_id=os.environ.get("MULTICA_AUTOPILOT_AGENT_ID", "").strip(),
            autopilot_mode=(
                os.environ.get("MULTICA_AUTOPILOT_MODE", "run_only").strip()
                or "run_only"
            ),
        )


def request(
    method: str,
    url: str,
    *,
    token: Optional[str] = None,
    json_body: Optional[dict] = None,
    timeout: int = 60,
) -> bytes:
    headers = {}
    data: Optional[bytes] = None
    if token:
        headers["Authorization"] = token
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise HttpError(exc.code, exc.read().decode("utf-8", "replace")) from None


class Gitea:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    def raw(self, path: str, ref: str) -> Optional[str]:
        """File content at `ref`, or None when absent there (404)."""
        quoted_path = urllib.parse.quote(path, safe="/")
        quoted_ref = urllib.parse.quote(ref, safe="")
        url = f"{self._cfg.gitea_base}/repos/{self._cfg.gitea_repo}/raw/{quoted_path}?ref={quoted_ref}"
        try:
            return request("GET", url, token=f"token {self._cfg.gitea_token}").decode(
                "utf-8"
            )
        except HttpError as exc:
            if exc.status == 404:
                return None
            raise


class Multica:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    def _url(self, path: str, extra: Optional[dict] = None) -> str:
        query = {"workspace_id": self._cfg.workspace_id}
        if extra:
            query.update(extra)
        return f"{self._cfg.multica_base}{path}?{urllib.parse.urlencode(query)}"

    def _get(self, path: str, extra: Optional[dict] = None) -> Any:
        data = request(
            "GET", self._url(path, extra), token=f"Bearer {self._cfg.multica_token}"
        )
        return json.loads(data)

    def _send(self, method: str, path: str, body: Optional[dict] = None) -> None:
        data = request(
            method,
            self._url(path),
            token=f"Bearer {self._cfg.multica_token}",
            json_body=body,
        )
        if data:
            json.loads(data)

    def list_agents(self) -> list:
        return self._get("/api/agents")

    def list_squads(self) -> list:
        return self._get("/api/squads")

    def list_autopilots(self) -> list:
        return self._get("/api/autopilots").get("autopilots", [])

    def list_skills(self) -> list:
        return self._get("/api/skills")

    def create_agent(self, name: str, instructions: str, runtime_id: str) -> None:
        self._send(
            "POST",
            "/api/agents",
            {"name": name, "instructions": instructions, "runtime_id": runtime_id},
        )

    def update_agent(self, agent_id: str, instructions: str) -> None:
        self._send("PUT", f"/api/agents/{agent_id}", {"instructions": instructions})

    def archive_agent(self, agent_id: str) -> None:
        self._send("POST", f"/api/agents/{agent_id}/archive")

    def get_skill(self, skill_id: str) -> dict:
        return self._get(f"/api/skills/{skill_id}")

    def create_skill(self, name: str, content: str) -> None:
        self._send("POST", "/api/skills", {"name": name, "content": content})

    def update_skill(self, skill_id: str, content: str) -> None:
        self._send("PUT", f"/api/skills/{skill_id}", {"content": content})

    def delete_skill(self, skill_id: str) -> None:
        self._send("DELETE", f"/api/skills/{skill_id}")

    def upsert_skill_file(self, skill_id: str, path: str, content: str) -> None:
        self._send(
            "PUT", f"/api/skills/{skill_id}/files", {"path": path, "content": content}
        )

    def delete_skill_file(self, skill_id: str, file_id: str) -> None:
        self._send("DELETE", f"/api/skills/{skill_id}/files/{file_id}")

    def create_squad(self, name: str, instructions: str, leader_id: str) -> None:
        self._send(
            "POST",
            "/api/squads",
            {"name": name, "instructions": instructions, "leader_id": leader_id},
        )

    def update_squad(self, squad_id: str, instructions: str) -> None:
        self._send("PUT", f"/api/squads/{squad_id}", {"instructions": instructions})

    def create_autopilot(
        self, title: str, description: str, execution_mode: str, agent_id: str
    ) -> None:
        self._send(
            "POST",
            "/api/autopilots/create",
            {
                "title": title,
                "description": description,
                "execution_mode": execution_mode,
                "assignee_type": "agent",
                "assignee_id": agent_id,
            },
        )

    def update_autopilot(self, autopilot_id: str, description: str) -> None:
        self._send(
            "PATCH", f"/api/autopilots/{autopilot_id}", {"description": description}
        )


class Report:
    _ORDER = ("update", "create", "archive", "skip", "block", "fail")

    def __init__(self) -> None:
        self.counts = {key: 0 for key in self._ORDER}
        self.lines: list[str] = []

    def record(self, status: str, kind: str, name: str, detail: str = "") -> None:
        self.counts[status] += 1
        suffix = f" {detail}" if detail else ""
        self.lines.append(f"{status.upper()} {kind}/{name}{suffix}")

    def summary(self) -> str:
        parts = " ".join(f"{key}={self.counts[key]}" for key in self._ORDER)
        return f"== done: {parts} =="


def load_payload(args: list[str]) -> dict:
    if len(args) > 1:
        raise SyncError(
            "expected at most one argument: a payload file path or a JSON string"
        )
    if len(args) == 1:
        candidate = args[0]
        if os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8") as fh:
                raw = fh.read()
        else:
            raw = candidate
    else:
        raw = sys.stdin.read()
    if not raw or not raw.strip():
        raise SyncError("empty webhook payload")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SyncError(f"invalid payload JSON: {exc}") from None


def touched_paths(payload: dict) -> tuple[set[str], set[str]]:
    """Return (present, removed) file paths netted across the push commits."""
    present: set[str] = set()
    removed: set[str] = set()
    for commit in payload.get("commits") or []:
        present.update(commit.get("added") or [])
        present.update(commit.get("modified") or [])
        removed.update(commit.get("removed") or [])
    removed -= present
    return present, removed


def _is_entity_path(path: str) -> bool:
    return path.startswith(ENTITY_DIRS)


def _md_stem(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    return base[:-3] if base.endswith(".md") and base != ".md" else ""


def split_autopilot_stem(stem: str) -> tuple[str, str]:
    """Split an autopilot filename stem into (title, id-prefix)."""
    match = AUTOPILOT_ID_RE.match(stem)
    if match:
        return match.group(1), match.group(2).lower()
    return stem, ""


def resolve_action(
    live_content: Optional[str], new_content: str, old_content: Optional[str]
) -> str:
    """Decide create/update/skip/block for one content field.

    old_content is None when the file has no pre-push version (new in this push);
    a differing live value with no baseline to verify against is blocked.
    """
    if live_content is None:
        return "create"
    if live_content == new_content:
        return "skip"
    if old_content is None or live_content != old_content:
        return "block"
    return "update"


def _files_by_name(present: set[str], removed: set[str], prefix: str) -> dict[str, str]:
    """Map directly-under-`prefix` *.md files to their net action."""
    out: dict[str, str] = {}
    for path in present:
        name = _md_stem(path)
        if path.startswith(prefix) and name and "/" not in path[len(prefix) :]:
            out[name] = "present"
    for path in removed:
        name = _md_stem(path)
        if path.startswith(prefix) and name and "/" not in path[len(prefix) :]:
            out[name] = "removed"
    return out


def _skill_changes(present: set[str], removed: set[str]) -> dict[str, dict]:
    """Group skill paths into {name: {"content": action|None, "files": {rel: action}}}."""
    changes: dict[str, dict] = {}
    for path in present | removed:
        if not path.startswith("skills/"):
            continue
        parts = path[len("skills/") :].split("/")
        if len(parts) < 2 or not parts[0]:
            continue
        name = parts[0]
        entry = changes.setdefault(name, {"content": None, "files": {}})
        action = "present" if path in present else "removed"
        if parts[1] == "SKILL.md" and len(parts) == 2:
            entry["content"] = action
        else:
            entry["files"]["/".join(parts[1:])] = action
    return changes


def _find_file(files: list, path: str) -> Optional[dict]:
    for file in files:
        if file.get("path") == path:
            return file
    return None


def _sync_agent(
    cfg: Config,
    gitea: Gitea,
    multica: Multica,
    live: dict,
    name: str,
    action: str,
    before: str,
    after: str,
    report: Report,
) -> None:
    if action == "removed":
        if name in live:
            multica.archive_agent(live[name]["id"])
            report.record("archive", "agent", name)
        else:
            report.record("skip", "agent", name, "already absent")
        return
    new_content = gitea.raw(f"agents/{name}.md", after)
    if new_content is None:  # listed as changed but absent at `after`: removal
        if name in live:
            multica.archive_agent(live[name]["id"])
            report.record("archive", "agent", name)
        else:
            report.record("skip", "agent", name, "already absent")
        return
    current = live.get(name)
    decision = resolve_action(
        current["instructions"] if current else None,
        new_content,
        gitea.raw(f"agents/{name}.md", before),
    )
    if decision == "create":
        if not cfg.agent_runtime_id:
            report.record("fail", "agent", name, "MULTICA_RUNTIME_ID not set")
            return
        multica.create_agent(name, new_content, cfg.agent_runtime_id)
        report.record("create", "agent", name)
    elif decision == "update":
        multica.update_agent(current["id"], new_content)
        report.record("update", "agent", name)
    elif decision == "block":
        report.record("block", "agent", name, "live drifted")
    else:
        report.record("skip", "agent", name)


def _sync_squad(
    cfg: Config,
    gitea: Gitea,
    multica: Multica,
    live: dict,
    name: str,
    action: str,
    before: str,
    after: str,
    report: Report,
) -> None:
    if action == "removed":
        # No archive path per spec: squads are reported, not auto-removed.
        report.record("fail", "squad", name, "no archive endpoint; manual removal")
        return
    new_content = gitea.raw(f"squads/{name}.md", after)
    if new_content is None:
        report.record("fail", "squad", name, "no archive endpoint; manual removal")
        return
    current = live.get(name)
    decision = resolve_action(
        current["instructions"] if current else None,
        new_content,
        gitea.raw(f"squads/{name}.md", before),
    )
    if decision == "create":
        if not cfg.squad_leader_id:
            report.record("fail", "squad", name, "MULTICA_SQUAD_LEADER_ID not set")
            return
        multica.create_squad(name, new_content, cfg.squad_leader_id)
        report.record("create", "squad", name)
    elif decision == "update":
        multica.update_squad(current["id"], new_content)
        report.record("update", "squad", name)
    elif decision == "block":
        report.record("block", "squad", name, "live drifted")
    else:
        report.record("skip", "squad", name)


def _sync_autopilot(
    cfg: Config,
    gitea: Gitea,
    multica: Multica,
    by_id_prefix: dict,
    by_title: dict,
    title: str,
    id8: str,
    stem: str,
    action: str,
    before: str,
    after: str,
    report: Report,
) -> None:
    current = by_id_prefix.get(id8) if id8 else by_title.get(title)
    if action == "removed":
        report.record("fail", "autopilot", title, "no archive endpoint; manual removal")
        return
    new_content = gitea.raw(f"autopilots/{stem}.md", after)
    if new_content is None:
        report.record("fail", "autopilot", title, "no archive endpoint; manual removal")
        return
    decision = resolve_action(
        current["description"] if current else None,
        new_content,
        gitea.raw(f"autopilots/{stem}.md", before),
    )
    if decision == "create":
        if not cfg.autopilot_agent_id:
            report.record(
                "fail", "autopilot", title, "MULTICA_AUTOPILOT_AGENT_ID not set"
            )
            return
        multica.create_autopilot(
            title, new_content, cfg.autopilot_mode, cfg.autopilot_agent_id
        )
        report.record("create", "autopilot", title)
    elif decision == "update":
        multica.update_autopilot(current["id"], new_content)
        report.record("update", "autopilot", title)
    elif decision == "block":
        report.record("block", "autopilot", title, "live drifted")
    else:
        report.record("skip", "autopilot", title)


def _sync_skill(
    cfg: Config,
    gitea: Gitea,
    multica: Multica,
    skills_by_name: dict,
    name: str,
    changes: dict,
    before: str,
    after: str,
    report: Report,
) -> None:
    content_action = changes["content"]
    file_actions = changes["files"]

    if content_action == "removed":
        skill_id = skills_by_name.get(name)
        if skill_id:
            multica.delete_skill(skill_id)
            report.record("archive", "skill", name)
        else:
            report.record("skip", "skill", name, "already absent")
        return

    live_skill = (
        multica.get_skill(skills_by_name[name]) if name in skills_by_name else None
    )
    status: Optional[str] = None

    if content_action == "present":
        new_content = gitea.raw(f"skills/{name}/SKILL.md", after)
        if new_content is None:
            # SKILL.md gone at `after` even though not listed removed: treat as removal.
            if live_skill:
                multica.delete_skill(live_skill["id"])
                report.record("archive", "skill", name)
            else:
                report.record("skip", "skill", name, "already absent")
            return
        decision = resolve_action(
            live_skill["content"] if live_skill else None,
            new_content,
            gitea.raw(f"skills/{name}/SKILL.md", before),
        )
        if decision == "block":
            report.record("block", "skill", name, "live drifted")
            return
        if decision == "create":
            multica.create_skill(name, new_content)
            live_skill = multica.get_skill(_resolve_skill_id(multica, name))
            status = "create"
        elif decision == "update":
            multica.update_skill(live_skill["id"], new_content)
            status = "update"
        # decision == "skip": content unchanged, fall through to attachments.
    elif live_skill is None:
        # Only attachments changed, but the skill is missing: create from current SKILL.md.
        new_content = gitea.raw(f"skills/{name}/SKILL.md", after)
        if new_content is None:
            report.record("fail", "skill", name, "SKILL.md missing at after")
            return
        multica.create_skill(name, new_content)
        live_skill = multica.get_skill(_resolve_skill_id(multica, name))
        status = "create"

    changed = status is not None
    live_files = live_skill["files"] if live_skill else []
    for rel, file_action in file_actions.items():
        if file_action == "removed":
            existing = _find_file(live_files, rel)
            if existing:
                multica.delete_skill_file(live_skill["id"], existing["id"])
                changed = True
            continue
        content = gitea.raw(f"skills/{name}/{rel}", after)
        if content is None:
            continue  # absent at `after`: nothing to write
        existing = _find_file(live_files, rel)
        if existing and existing.get("content") == content:
            continue
        multica.upsert_skill_file(live_skill["id"], rel, content)
        changed = True

    if status == "create":
        report.record("create", "skill", name)
    elif changed:
        report.record("update", "skill", name)
    else:
        report.record("skip", "skill", name)


def _resolve_skill_id(multica: Multica, name: str) -> str:
    for skill in multica.list_skills():
        if skill.get("name") == name:
            return skill["id"]
    raise SyncError(f"skill {name!r} not found after create")


def run_sync(
    cfg: Config,
    gitea: Gitea,
    multica: Multica,
    present: set[str],
    removed: set[str],
    before: str,
    after: str,
) -> Report:
    report = Report()

    agents_by_name = {a["name"]: a for a in multica.list_agents()}
    squads_by_name = {s["name"]: s for s in multica.list_squads()}
    skills_by_name = {s["name"]: s["id"] for s in multica.list_skills()}
    autopilots_by_id_prefix: dict[str, dict] = {}
    autopilots_by_title: dict[str, dict] = {}
    for ap in multica.list_autopilots():
        autopilots_by_title[ap["title"]] = ap
        autopilots_by_id_prefix.setdefault(ap["id"][:8].lower(), ap)

    agent_files = _files_by_name(present, removed, "agents/")
    for name in sorted(agent_files):
        try:
            _sync_agent(
                cfg,
                gitea,
                multica,
                agents_by_name,
                name,
                agent_files[name],
                before,
                after,
                report,
            )
        except HttpError as exc:
            report.record("fail", "agent", name, str(exc))

    squad_files = _files_by_name(present, removed, "squads/")
    for name in sorted(squad_files):
        try:
            _sync_squad(
                cfg,
                gitea,
                multica,
                squads_by_name,
                name,
                squad_files[name],
                before,
                after,
                report,
            )
        except HttpError as exc:
            report.record("fail", "squad", name, str(exc))

    skill_changes = _skill_changes(present, removed)
    for name in sorted(skill_changes):
        try:
            _sync_skill(
                cfg,
                gitea,
                multica,
                skills_by_name,
                name,
                skill_changes[name],
                before,
                after,
                report,
            )
        except HttpError as exc:
            report.record("fail", "skill", name, str(exc))

    autopilot_files = _files_by_name(present, removed, "autopilots/")
    for stem in sorted(autopilot_files):
        title, id8 = split_autopilot_stem(stem)
        try:
            _sync_autopilot(
                cfg,
                gitea,
                multica,
                autopilots_by_id_prefix,
                autopilots_by_title,
                title,
                id8,
                stem,
                autopilot_files[stem],
                before,
                after,
                report,
            )
        except HttpError as exc:
            report.record("fail", "autopilot", title, str(exc))

    return report


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        cfg = Config.from_env()
        payload = load_payload(argv)
        ref = payload.get("ref") or ""
        if ref and ref != MAIN_REF:
            print(f"SKIP ref={ref} (only {MAIN_REF} is synced)")
            return 0
        after = payload.get("after") or ""
        if not after:
            raise SyncError("payload missing 'after' commit sha")
        before = payload.get("before") or ""
        present, removed = touched_paths(payload)
        present = {p for p in present if _is_entity_path(p)}
        removed = {p for p in removed if _is_entity_path(p)}
        if not present and not removed:
            print("SKIP no changed entity files")
            return 0
        report = run_sync(
            cfg, Gitea(cfg), Multica(cfg), present, removed, before, after
        )
        for line in report.lines:
            print(line)
        print(report.summary())
        return 0
    except SyncError as exc:
        print(f"FAIL {exc}")
        return 1
    except Exception as exc:  # top-level safety net: never crash the webhook silently
        print(f"FAIL unexpected: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
