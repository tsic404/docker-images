#!/usr/bin/env python3
"""Converge Multica entities from a Gitea push webhook (v3).

Each repo file mirrors one API endpoint's request body, verbatim: yaml field
names are API json field names, the filename selects the route. The script is a
generic router — adding an API field means adding one line to a repo yaml, no
script change.

Layout (one directory per entity, name = directory name):

    agents/<name>/{agent.md,agent.yaml,env.yaml,skills.yaml}
    skills/<name>/{SKILL.md,skill.yaml,references/...}
    squads/<name>/{squad.md,squad.yaml,members.yaml}
    autopilots/<name>/{autopilot.md,autopilot.yaml,triggers.yaml}

Content files map to the entity content field; yaml files are sent verbatim to
the route below. Matching is case-sensitive then case-insensitive (single hit ->
rename, multiple hits -> BLOCK). Set MULTICA_SYNC_FORCE=1 to skip the drift guard.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

MAIN_REF = "refs/heads/main"
KIND_PREFIX = {
    "agent": "agents/",
    "skill": "skills/",
    "squad": "squads/",
    "autopilot": "autopilots/",
}
CONTENT_FILE = {
    "agent": "agent.md",
    "skill": "SKILL.md",
    "squad": "squad.md",
    "autopilot": "autopilot.md",
}
CONTENT_FIELD = {
    "agent": "instructions",
    "skill": "content",
    "squad": "instructions",
    "autopilot": "description",
}
# filename -> role within an entity directory (everything else is unknown/attachment)
ROLE = {
    "agent": {"agent.yaml": "attr", "env.yaml": "env", "skills.yaml": "skills"},
    "skill": {"skill.yaml": "attr"},
    "squad": {"squad.yaml": "attr", "members.yaml": "members"},
    "autopilot": {"autopilot.yaml": "attr", "triggers.yaml": "triggers"},
}
# fields that are read-only or matched-only and must not be written back
STRIP_FIELDS = (
    "id",
    "id_prefix",
    "created_at",
    "updated_at",
    "archived_at",
    "archived_by",
    "has_custom_env",
    "custom_env_key_count",
    "member_count",
    "member_preview",
    "skills",
    "triggers",
)

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
    force: bool

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
            force=os.environ.get("MULTICA_SYNC_FORCE", "").strip().lower()
            in ("1", "true", "yes", "on"),
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

    def _url(self, path: str) -> str:
        return f"{self._cfg.multica_base}{path}?{urllib.parse.urlencode({'workspace_id': self._cfg.workspace_id})}"

    def _get(self, path: str) -> Any:
        return json.loads(
            request("GET", self._url(path), token=f"Bearer {self._cfg.multica_token}")
        )

    def _send(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        data = request(
            method,
            self._url(path),
            token=f"Bearer {self._cfg.multica_token}",
            json_body=body,
        )
        return json.loads(data) if data else None

    # lists
    def list_agents(self, include_archived: bool = False) -> list:
        q = {"include_archived": "true"} if include_archived else {}
        path = f"/api/agents?{urllib.parse.urlencode({'workspace_id': self._cfg.workspace_id, **q})}"
        return json.loads(
            request(
                "GET",
                self._cfg.multica_base + path,
                token=f"Bearer {self._cfg.multica_token}",
            )
        )

    def list_squads(self) -> list:
        return self._get("/api/squads")

    def list_skills(self) -> list:
        return self._get("/api/skills")

    def list_autopilots(self) -> list:
        return self._get("/api/autopilots").get("autopilots", [])

    # agents
    def create_agent(self, body: dict) -> dict:
        return self._send("POST", "/api/agents", body)

    def update_agent(self, agent_id: str, body: dict) -> None:
        self._send("PUT", f"/api/agents/{agent_id}", body)

    def archive_agent(self, agent_id: str) -> None:
        self._send("POST", f"/api/agents/{agent_id}/archive")

    def restore_agent(self, agent_id: str) -> None:
        self._send("POST", f"/api/agents/{agent_id}/restore")

    def put_agent_env(self, agent_id: str, body: dict) -> None:
        self._send("PUT", f"/api/agents/{agent_id}/env", body)

    def set_agent_skills(self, agent_id: str, skill_ids: list) -> None:
        self._send("PUT", f"/api/agents/{agent_id}/skills", {"skill_ids": skill_ids})

    # skills
    def get_skill(self, skill_id: str) -> dict:
        return self._get(f"/api/skills/{skill_id}")

    def create_skill(self, body: dict) -> dict:
        return self._send("POST", "/api/skills", body)

    def update_skill(self, skill_id: str, body: dict) -> None:
        self._send("PUT", f"/api/skills/{skill_id}", body)

    def delete_skill(self, skill_id: str) -> None:
        self._send("DELETE", f"/api/skills/{skill_id}")

    def upsert_skill_file(self, skill_id: str, path: str, content: str) -> None:
        self._send(
            "PUT", f"/api/skills/{skill_id}/files", {"path": path, "content": content}
        )

    def delete_skill_file(self, skill_id: str, file_id: str) -> None:
        self._send("DELETE", f"/api/skills/{skill_id}/files/{file_id}")

    # squads
    def create_squad(self, body: dict) -> dict:
        return self._send("POST", "/api/squads", body)

    def update_squad(self, squad_id: str, body: dict) -> None:
        self._send("PUT", f"/api/squads/{squad_id}", body)

    def list_squad_members(self, squad_id: str) -> list:
        return self._get(f"/api/squads/{squad_id}/members")

    def add_squad_member(
        self, squad_id: str, member_id: str, member_type: str, role: str
    ) -> None:
        self._send(
            "POST",
            f"/api/squads/{squad_id}/members",
            {"member_id": member_id, "member_type": member_type, "role": role},
        )

    def remove_squad_member(
        self, squad_id: str, member_id: str, member_type: str
    ) -> None:
        self._send(
            "DELETE",
            f"/api/squads/{squad_id}/members",
            {"member_id": member_id, "member_type": member_type},
        )

    def set_squad_member_role(
        self, squad_id: str, member_id: str, member_type: str, role: str
    ) -> None:
        self._send(
            "PATCH",
            f"/api/squads/{squad_id}/members/role",
            {"member_id": member_id, "member_type": member_type, "role": role},
        )

    # autopilots
    def create_autopilot(self, body: dict) -> dict:
        return self._send("POST", "/api/autopilots", body)

    def update_autopilot(self, autopilot_id: str, body: dict) -> None:
        self._send("PATCH", f"/api/autopilots/{autopilot_id}", body)

    def get_autopilot(self, autopilot_id: str) -> dict:
        # full shape: {"autopilot": {...}, "collaborators": [...], "triggers": [...]}
        return self._get(f"/api/autopilots/{autopilot_id}")

    def add_autopilot_trigger(self, autopilot_id: str, body: dict) -> None:
        self._send("POST", f"/api/autopilots/{autopilot_id}/triggers", body)

    def update_autopilot_trigger(
        self, autopilot_id: str, trigger_id: str, body: dict
    ) -> None:
        self._send(
            "PATCH", f"/api/autopilots/{autopilot_id}/triggers/{trigger_id}", body
        )

    def delete_autopilot_trigger(self, autopilot_id: str, trigger_id: str) -> None:
        self._send("DELETE", f"/api/autopilots/{autopilot_id}/triggers/{trigger_id}")


class Report:
    _ORDER = ("update", "create", "archive", "skip", "block", "fail", "rename")

    def __init__(self) -> None:
        self.counts = {key: 0 for key in self._ORDER}
        self.lines: list[str] = []

    def record(
        self, status: str, kind: str, name: str, file: str, detail: str = ""
    ) -> None:
        self.counts[status] += 1
        suffix = f" {detail}" if detail else ""
        self.lines.append(f"{status.upper()} {kind}/{name}/{file}{suffix}")

    def record_rename(self, kind: str, old: str, new: str) -> None:
        self.counts["rename"] += 1
        self.lines.append(f"RENAME {kind}/{old} -> {new}")

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


def touched_paths(payload: dict) -> tuple[set[str], set[str], set[str]]:
    added: set[str] = set()
    modified: set[str] = set()
    removed: set[str] = set()
    for commit in payload.get("commits") or []:
        added.update(commit.get("added") or [])
        modified.update(commit.get("modified") or [])
        removed.update(commit.get("removed") or [])
    added -= removed
    modified -= removed
    removed -= added
    removed -= modified
    return added, modified, removed


def _is_entity_path(path: str) -> bool:
    return path.startswith(tuple(KIND_PREFIX.values()))


@dataclass
class ChangeRef:
    kind: str
    name: str
    file: str  # filename within the entity dir (e.g. "agent.md", "references/a.md")


def classify_path(path: str) -> Optional[ChangeRef]:
    for kind, prefix in KIND_PREFIX.items():
        if not path.startswith(prefix):
            continue
        parts = path[len(prefix) :].split("/")
        if len(parts) < 2 or not parts[0]:
            return None
        return ChangeRef(kind, parts[0], "/".join(parts[1:]))
    return None


def file_role(kind: str, file: str) -> Optional[str]:
    if file == CONTENT_FILE[kind]:
        return "content"
    role = ROLE.get(kind, {}).get(file)
    if role:
        return role
    if kind == "skill":
        return "attachment"  # everything else under skills/<n>/ is an attachment
    return None


@dataclass
class EntityChanges:
    kind: str
    name: str
    files: dict = field(default_factory=dict)  # file -> "added"|"modified"|"removed"


def collect_changes(added, modified, removed) -> dict[tuple[str, str], EntityChanges]:
    result: dict[tuple[str, str], EntityChanges] = {}
    for path in added:
        _apply(result, classify_path(path), "added")
    for path in modified:
        _apply(result, classify_path(path), "modified")
    for path in removed:
        _apply(result, classify_path(path), "removed")
    return result


def _apply(result, ref: Optional[ChangeRef], action: str) -> None:
    if ref is None:
        return
    key = (ref.kind, ref.name)
    e = result.setdefault(key, EntityChanges(ref.kind, ref.name))
    e.files[ref.file] = action


def file_path(kind: str, name: str, file: str) -> str:
    return f"{KIND_PREFIX[kind]}{name}/{file}"


def load_yaml(
    gitea: Gitea, kind: str, name: str, file: str, ref: str
) -> Optional[dict]:
    raw = gitea.raw(file_path(kind, name, file), ref)
    if raw is None:
        return None
    if not raw.strip():
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _canonical(name: str) -> str:
    return re.sub(r"[\W_]+", "", name.lower())


def resolve_live_name(live_by_name: dict, live_by_lower: dict, name: str):
    if name in live_by_name:
        return live_by_name[name], "exact"
    candidates = live_by_lower.get(name.lower(), [])
    if len(candidates) == 1:
        return candidates[0], "casefold"
    if len(candidates) > 1:
        return None, "ambiguous"
    return None, "none"


def resolve_action(
    live_content: Optional[str],
    new_content: str,
    old_content: Optional[str],
    force: bool = False,
) -> str:
    if live_content is None:
        return "create"
    if live_content == new_content:
        return "skip"
    if force or old_content is None:
        return "update"
    if live_content != old_content:
        return "block"
    return "update"


def _find_file(files: list, path: str) -> Optional[dict]:
    for file in files:
        if file.get("path") == path:
            return file
    return None


def detect_renames(gitea: Gitea, changes, before: str, after: str) -> dict[tuple, str]:
    removed_by_kind: dict[str, list[str]] = {}
    added_by_kind: dict[str, list[str]] = {}
    for (kind, name), e in changes.items():
        if e.files.get(CONTENT_FILE[kind]) == "removed":
            removed_by_kind.setdefault(kind, []).append(name)
        elif e.files.get(CONTENT_FILE[kind]) == "added":
            added_by_kind.setdefault(kind, []).append(name)
    renames: dict[tuple, str] = {}
    for kind, removed_names in removed_by_kind.items():
        added_names = added_by_kind.get(kind, [])
        used: set[str] = set()
        # 1) content-identical (pure git mv).
        for old in removed_names:
            old_content = gitea.raw(file_path(kind, old, CONTENT_FILE[kind]), before)
            if old_content is None:
                continue
            for new in added_names:
                if new in used:
                    continue
                new_content = gitea.raw(file_path(kind, new, CONTENT_FILE[kind]), after)
                if new_content is not None and new_content == old_content:
                    renames[(kind, old)] = new
                    used.add(new)
                    break
        # 2) config-identical (git mv + content edit). Pairing requires a
        #    positive identity signal: the entity's config file is byte-identical
        #    across the move, so a pure delete+add of unrelated dirs never pairs.
        attr = _attr_filename(kind)
        if attr is None:
            continue
        remaining_old = [o for o in removed_names if (kind, o) not in renames]
        remaining_new = [n for n in added_names if n not in used]
        for old in remaining_old:
            old_cfg = gitea.raw(file_path(kind, old, attr), before)
            if old_cfg is None:
                continue
            for new in remaining_new:
                if new in used:
                    continue
                new_cfg = gitea.raw(file_path(kind, new, attr), after)
                if new_cfg is not None and new_cfg == old_cfg:
                    renames[(kind, old)] = new
                    used.add(new)
                    break
    return renames


def strip_fields(body: dict) -> dict:
    return {k: v for k, v in body.items() if k not in STRIP_FIELDS}


def run_sync(cfg, gitea, multica, added, modified, removed, before, after) -> Report:
    report = Report()

    agents_by_name = {a["name"]: a for a in multica.list_agents(include_archived=True)}
    squads_by_name = {s["name"]: s for s in multica.list_squads()}
    skills_by_name = {s["name"]: s for s in multica.list_skills()}
    autopilots = multica.list_autopilots()

    def lower_index(by_name: dict) -> dict:
        idx: dict[str, list] = {}
        for v in by_name.values():
            idx.setdefault(v["name"].lower(), []).append(v)
        return idx

    agents_by_lower = lower_index(agents_by_name)
    squads_by_lower = lower_index(squads_by_name)

    changes = collect_changes(added, modified, removed)
    renames = detect_renames(gitea, changes, before, after)
    rename_sources = set(renames.keys())
    rename_targets: dict[tuple, str] = {}
    for (kind, old), new in renames.items():
        rename_targets[(kind, new)] = old

    for kind, name in sorted(changes):
        e = changes[(kind, name)]
        if (kind, name) in rename_sources:
            continue
        try:
            if (kind, name) in rename_targets:
                _sync_rename(
                    cfg,
                    gitea,
                    multica,
                    kind,
                    rename_targets[(kind, name)],
                    name,
                    e,
                    before,
                    after,
                    agents_by_name,
                    squads_by_name,
                    skills_by_name,
                    autopilots,
                    report,
                )
            else:
                _sync_entity(
                    cfg,
                    gitea,
                    multica,
                    kind,
                    name,
                    e,
                    before,
                    after,
                    agents_by_name,
                    agents_by_lower,
                    squads_by_name,
                    squads_by_lower,
                    skills_by_name,
                    autopilots,
                    report,
                )
        except HttpError as exc:
            report.record("fail", kind, name, "", str(exc))

    return report


def _resolve_live(
    kind,
    name,
    agents_by_name,
    agents_by_lower,
    squads_by_name,
    squads_by_lower,
    skills_by_name,
    autopilots,
    attr,
):
    if kind == "agent":
        return resolve_live_name(agents_by_name, agents_by_lower, name)
    if kind == "squad":
        return resolve_live_name(squads_by_name, squads_by_lower, name)
    if kind == "skill":
        return (skills_by_name.get(name), "exact" if name in skills_by_name else "none")
    if kind == "autopilot":
        return _resolve_autopilot(autopilots, name, attr), "exact"


def _resolve_autopilot(autopilots: list, name: str, attr: dict) -> Optional[dict]:
    id_prefix = str((attr or {}).get("id_prefix", "")).strip()
    if id_prefix:
        for ap in autopilots:
            if ap["id"].startswith(id_prefix):
                return ap
    target = (attr or {}).get("title") or name
    exact = [ap for ap in autopilots if ap["title"] == target]
    if len(exact) == 1:
        return exact[0]
    lower = target.lower()
    ci = [ap for ap in autopilots if ap["title"].lower() == lower]
    return ci[0] if len(ci) == 1 else None


def _sync_entity(
    cfg,
    gitea,
    multica,
    kind,
    name,
    e,
    before,
    after,
    agents_by_name,
    agents_by_lower,
    squads_by_name,
    squads_by_lower,
    skills_by_name,
    autopilots,
    report,
):
    content_file = CONTENT_FILE[kind]
    content_action = e.files.get(content_file)

    # whole-dir removal (content file removed) -> archive/delete/report
    if content_action == "removed":
        _remove_entity(
            kind, name, agents_by_name, squads_by_name, skills_by_name, multica, report
        )
        return

    attr_file = _attr_filename(kind)
    attr = load_yaml(gitea, kind, name, attr_file, after) if attr_file else {}

    current, status = _resolve_live(
        kind,
        name,
        agents_by_name,
        agents_by_lower,
        squads_by_name,
        squads_by_lower,
        skills_by_name,
        autopilots,
        attr,
    )
    if status == "ambiguous":
        report.record("block", kind, name, "", "name collision")
        return
    pending_rename = name if status == "casefold" else None

    if current is None:
        _create_entity(
            cfg,
            gitea,
            multica,
            kind,
            name,
            e,
            after,
            skills_by_name,
            agents_by_name,
            report,
        )
        return

    if kind == "agent" and current.get("archived_at"):
        multica.restore_agent(current["id"])
        report.record("update", "agent", name, "", "restored")

    if pending_rename:
        _rename_name(kind, current, pending_rename, multica, report)

    # per-file sync
    for file in sorted(e.files):
        if file == content_file:
            continue  # handled below
        action = e.files[file]
        _sync_file(
            cfg,
            gitea,
            multica,
            kind,
            name,
            file,
            action,
            current,
            before,
            after,
            skills_by_name,
            agents_by_name,
            report,
        )

    # content file (drift-guarded)
    if content_action in ("added", "modified"):
        _sync_content(
            cfg,
            gitea,
            multica,
            kind,
            name,
            content_file,
            current,
            before,
            after,
            report,
        )


def _attr_filename(kind: str) -> Optional[str]:
    return {
        "agent": "agent.yaml",
        "skill": "skill.yaml",
        "squad": "squad.yaml",
        "autopilot": "autopilot.yaml",
    }.get(kind)


def _rename_name(kind, current, new_name, multica, report):
    if kind == "agent":
        multica.update_agent(current["id"], {"name": new_name})
    elif kind == "skill":
        multica.update_skill(current["id"], {"name": new_name})
    elif kind == "squad":
        multica.update_squad(current["id"], {"name": new_name})
    elif kind == "autopilot":
        multica.update_autopilot(current["id"], {"title": new_name})
    report.record_rename(
        kind, current.get("name") or current.get("title", "?"), new_name
    )


def _remove_entity(
    kind, name, agents_by_name, squads_by_name, skills_by_name, multica, report
):
    if kind == "agent":
        current = agents_by_name.get(name)
        if current is None:
            report.record("skip", "agent", name, "", "already absent")
        elif current.get("archived_at"):
            report.record("skip", "agent", name, "", "already archived")
        else:
            multica.archive_agent(current["id"])
            report.record("archive", "agent", name, "")
    elif kind == "skill":
        if name in skills_by_name:
            multica.delete_skill(skills_by_name[name]["id"])
            report.record("archive", "skill", name, "")
        else:
            report.record("skip", "skill", name, "", "already absent")
    else:
        report.record("fail", kind, name, "", "no archive endpoint; manual removal")


def _sync_content(
    cfg, gitea, multica, kind, name, file, current, before, after, report
):
    new_content = gitea.raw(file_path(kind, name, file), after)
    if new_content is None:
        return
    field = CONTENT_FIELD[kind]
    live = current.get(field) if current else None
    decision = resolve_action(
        live, new_content, gitea.raw(file_path(kind, name, file), before), cfg.force
    )
    if decision == "update":
        body = {field: new_content}
        if kind == "agent":
            multica.update_agent(current["id"], body)
        elif kind == "skill":
            multica.update_skill(current["id"], body)
        elif kind == "squad":
            multica.update_squad(current["id"], body)
        else:
            multica.update_autopilot(current["id"], body)
        report.record("update", kind, name, file)
    elif decision == "block":
        report.record("block", kind, name, file, "live drifted")
    else:
        report.record("skip", kind, name, file)


def _sync_file(
    cfg,
    gitea,
    multica,
    kind,
    name,
    file,
    action,
    current,
    before,
    after,
    skills_by_name,
    agents_by_name,
    report,
):
    role = file_role(kind, file)
    if role is None:
        return
    if action == "removed":
        if role == "attachment" and kind == "skill":
            existing = _find_file(current.get("files", []) if current else [], file)
            if existing:
                multica.delete_skill_file(current["id"], existing["id"])
                report.record("update", "skill", name, file, "deleted")
        return

    if role == "content":
        return  # handled in _sync_content

    content = gitea.raw(file_path(kind, name, file), after)
    if content is None:
        return

    if role == "attr":
        body = strip_fields(load_yaml(gitea, kind, name, file, after) or {})
        if not body:
            return
        if kind == "agent":
            multica.update_agent(current["id"], body)
        elif kind == "skill":
            multica.update_skill(current["id"], body)
        elif kind == "squad":
            multica.update_squad(current["id"], body)
        else:
            multica.update_autopilot(current["id"], body)
        report.record("update", kind, name, file)
    elif role == "env":
        body = load_yaml(gitea, kind, name, file, after) or {}
        multica.put_agent_env(current["id"], body)
        report.record("update", kind, name, file)
    elif role == "skills":
        _sync_skills(
            multica,
            current["id"],
            load_yaml(gitea, kind, name, file, after),
            skills_by_name,
        )
        report.record("update", kind, name, file)
    elif role == "members":
        _apply_squad_members(
            multica,
            current["id"],
            load_yaml(gitea, kind, name, file, after),
            agents_by_name,
        )
        report.record("update", kind, name, file)
    elif role == "triggers":
        _apply_triggers(
            multica, current["id"], gitea.raw(file_path(kind, name, file), after)
        )
        report.record("update", kind, name, file)
    elif role == "attachment":
        _sync_attachment(multica, current, file, content)
        report.record("update", "skill", name, file)


def _sync_skills(multica, agent_id, yaml_data, skills_by_name):
    if not isinstance(yaml_data, dict):
        return
    names = yaml_data.get("skill_ids") or yaml_data.get("names") or []
    ids = [skills_by_name[n]["id"] for n in names if n in skills_by_name]
    multica.set_agent_skills(agent_id, ids)


def _apply_squad_members(multica, squad_id, yaml_data, agents_by_name) -> bool:
    entries = yaml_data
    if isinstance(yaml_data, dict):
        entries = yaml_data.get("members") or []
    if not isinstance(entries, list):
        return False
    desired: dict[tuple, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("agent") or entry.get("member") or entry.get("name")
        agent = agents_by_name.get(name) if name else None
        if agent is None:
            continue
        desired[(entry.get("member_type", "agent"), agent["id"])] = entry.get(
            "role", "member"
        )
    current = {
        (m.get("member_type"), m.get("member_id")): m.get("role")
        for m in multica.list_squad_members(squad_id)
    }
    changed = False
    for key, role in desired.items():
        if key not in current:
            multica.add_squad_member(squad_id, key[1], key[0], role)
            changed = True
        elif current[key] != role:
            multica.set_squad_member_role(squad_id, key[1], key[0], role)
            changed = True
    for key in current:
        if key not in desired:
            multica.remove_squad_member(squad_id, key[1], key[0])
            changed = True
    return changed


TRIGGER_FIELDS = (
    "kind",
    "cron_expression",
    "timezone",
    "label",
    "provider",
    "event_filters",
)


def _trigger_body(trigger: dict) -> dict:
    return {k: trigger[k] for k in TRIGGER_FIELDS if trigger.get(k) is not None}


def _trigger_key(trigger: dict) -> tuple:
    return (
        trigger.get("kind"),
        trigger.get("cron_expression") or "",
        trigger.get("label") or "",
    )


def _apply_triggers(multica, autopilot_id, raw: str) -> bool:
    """Full convergence of an autopilot's triggers: add missing, remove extra,
    update changed. Returns True when anything changed."""
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return False
    triggers = data.get("triggers") if isinstance(data, dict) else data
    if not isinstance(triggers, list):
        return False
    desired = [
        t
        for t in triggers
        if isinstance(t, dict) and t.get("kind") and t.get("enabled") is not False
    ]
    live = multica.get_autopilot(autopilot_id).get("triggers", [])
    changed = False
    matched: set[int] = set()
    for want in desired:
        body = _trigger_body(want)
        found = None
        for index, have in enumerate(live):
            if index in matched:
                continue
            if _trigger_key(have) == _trigger_key(want):
                found = (index, have)
                break
        if found is None:
            multica.add_autopilot_trigger(autopilot_id, body)
            changed = True
            continue
        index, have = found
        matched.add(index)
        diff = {k: v for k, v in body.items() if have.get(k) != v}
        if diff:
            multica.update_autopilot_trigger(autopilot_id, have["id"], diff)
            changed = True
    for index, have in enumerate(live):
        if index not in matched:
            multica.delete_autopilot_trigger(autopilot_id, have["id"])
            changed = True
    return changed


def _sync_attachment(multica, current, file, content):
    existing = _find_file(current.get("files", []) if current else [], file)
    if existing and existing.get("content") == content:
        return
    multica.upsert_skill_file(current["id"], file, content)


def _create_entity(
    cfg, gitea, multica, kind, name, e, after, skills_by_name, agents_by_name, report
):
    content_file = CONTENT_FILE[kind]
    content = gitea.raw(file_path(kind, name, content_file), after)
    attr_file = _attr_filename(kind)
    attr = load_yaml(gitea, kind, name, attr_file, after) if attr_file else {}
    attr = strip_fields(attr or {})

    created = None
    if kind == "agent":
        body = {"name": name, "instructions": content or "", **attr}
        if not body.get("runtime_id"):
            body["runtime_id"] = cfg.agent_runtime_id
        if not body.get("runtime_id"):
            report.record("fail", "agent", name, "", "runtime_id missing")
            return
        created = multica.create_agent(body)
    elif kind == "skill":
        body = {"name": name, "content": content or "", **attr}
        created = multica.create_skill(body)
    elif kind == "squad":
        body = {"name": name, "instructions": content or "", **attr}
        if not body.get("leader_id"):
            body["leader_id"] = cfg.squad_leader_id
        if not body.get("leader_id"):
            report.record("fail", "squad", name, "", "leader_id missing")
            return
        created = multica.create_squad(body)
    elif kind == "autopilot":
        body = {
            "title": attr.get("title") or name,
            "description": content or "",
            **attr,
        }
        if not body.get("assignee_id"):
            body["assignee_id"] = cfg.autopilot_agent_id
        if not body.get("assignee_id"):
            report.record("fail", "autopilot", name, "", "assignee_id missing")
            return
        created = multica.create_autopilot(body)

    report.record("create", kind, name, "")

    # sub-resources
    for file in sorted(e.files):
        role = file_role(kind, file)
        if role in ("env", "skills", "members", "triggers", "attachment"):
            current = _fetch_created(multica, kind, name, created)
            if role == "attachment" and current:
                att = gitea.raw(file_path(kind, name, file), after)
                if att is not None:
                    _sync_attachment(multica, current, file, att)
            else:
                _sync_file(
                    cfg,
                    gitea,
                    multica,
                    kind,
                    name,
                    file,
                    e.files[file],
                    current,
                    after,
                    after,
                    skills_by_name,
                    agents_by_name,
                    report,
                )


def _fetch_created(multica, kind, name, created):
    if kind == "agent":
        for a in multica.list_agents(include_archived=True):
            if a["name"] == name:
                return a
    elif kind == "skill":
        return multica.get_skill(created["id"])
    elif kind == "squad":
        for s in multica.list_squads():
            if s["name"] == name:
                return s
    return created


def _fold_rename_files(
    cfg,
    gitea,
    multica,
    kind,
    old,
    new,
    e,
    current,
    before,
    after,
    skills_by_name,
    agents_by_name,
    report,
) -> None:
    """After a rename, converge the entity's changed files.

    The rename caller already ran the drift guard against the old name's content;
    here the content file (if changed) and every other changed file are applied
    through the per-file flow.
    """
    content_file = CONTENT_FILE[kind]
    for file in sorted(e.files):
        if file == content_file:
            field = CONTENT_FIELD[kind]
            new_content = gitea.raw(file_path(kind, new, file), after)
            if new_content is not None and new_content != current.get(field):
                body = {field: new_content}
                if kind == "agent":
                    multica.update_agent(current["id"], body)
                elif kind == "skill":
                    multica.update_skill(current["id"], body)
                elif kind == "squad":
                    multica.update_squad(current["id"], body)
                else:
                    multica.update_autopilot(current["id"], body)
                report.record("update", kind, new, file)
            continue
        _sync_file(
            cfg,
            gitea,
            multica,
            kind,
            new,
            file,
            e.files[file],
            current,
            after,
            after,
            skills_by_name,
            agents_by_name,
            report,
        )


def _sync_rename(
    cfg,
    gitea,
    multica,
    kind,
    old,
    new,
    e,
    before,
    after,
    agents_by_name,
    squads_by_name,
    skills_by_name,
    autopilots,
    report,
):
    current = None
    if kind == "agent":
        current = agents_by_name.get(old)
        if current is None:
            _sync_entity(
                cfg,
                gitea,
                multica,
                kind,
                new,
                e,
                before,
                after,
                agents_by_name,
                _lower(agents_by_name),
                squads_by_name,
                _lower(squads_by_name),
                skills_by_name,
                autopilots,
                report,
            )
            return
        if not cfg.force:
            old_content = gitea.raw(file_path(kind, old, CONTENT_FILE[kind]), before)
            if old_content is not None and current.get("instructions") != old_content:
                report.record("block", "agent", new, "", "live drifted")
                return
        multica.update_agent(current["id"], {"name": new})
        report.record_rename("agent", old, new)
        _fold_rename_files(
            cfg,
            gitea,
            multica,
            kind,
            old,
            new,
            e,
            current,
            before,
            after,
            skills_by_name,
            agents_by_name,
            report,
        )
    elif kind == "skill":
        current = skills_by_name.get(old)
        if current is None:
            _sync_entity(
                cfg,
                gitea,
                multica,
                kind,
                new,
                e,
                before,
                after,
                agents_by_name,
                _lower(agents_by_name),
                squads_by_name,
                _lower(squads_by_name),
                skills_by_name,
                autopilots,
                report,
            )
            return
        multica.update_skill(current["id"], {"name": new})
        report.record_rename("skill", old, new)
        _fold_rename_files(
            cfg,
            gitea,
            multica,
            kind,
            old,
            new,
            e,
            current,
            before,
            after,
            skills_by_name,
            agents_by_name,
            report,
        )
    elif kind == "squad":
        current = squads_by_name.get(old)
        if current is None:
            _sync_entity(
                cfg,
                gitea,
                multica,
                kind,
                new,
                e,
                before,
                after,
                agents_by_name,
                _lower(agents_by_name),
                squads_by_name,
                _lower(squads_by_name),
                skills_by_name,
                autopilots,
                report,
            )
            return
        multica.update_squad(current["id"], {"name": new})
        report.record_rename("squad", old, new)
        _fold_rename_files(
            cfg,
            gitea,
            multica,
            kind,
            old,
            new,
            e,
            current,
            before,
            after,
            skills_by_name,
            agents_by_name,
            report,
        )
    elif kind == "autopilot":
        attr = load_yaml(gitea, kind, new, _attr_filename(kind), after) or {}
        current = _resolve_autopilot(autopilots, new, attr)
        if current is None:
            _sync_entity(
                cfg,
                gitea,
                multica,
                kind,
                new,
                e,
                before,
                after,
                agents_by_name,
                _lower(agents_by_name),
                squads_by_name,
                _lower(squads_by_name),
                skills_by_name,
                autopilots,
                report,
            )
            return
        title = attr.get("title") or new
        if title != current.get("title"):
            multica.update_autopilot(current["id"], {"title": title})
        report.record_rename("autopilot", old, new)
        _fold_rename_files(
            cfg,
            gitea,
            multica,
            kind,
            old,
            new,
            e,
            current,
            before,
            after,
            skills_by_name,
            agents_by_name,
            report,
        )


def _lower(by_name: dict) -> dict:
    idx: dict[str, list] = {}
    for v in by_name.values():
        idx.setdefault(v["name"].lower(), []).append(v)
    return idx


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
        added, modified, removed = touched_paths(payload)
        added = {p for p in added if _is_entity_path(p)}
        modified = {p for p in modified if _is_entity_path(p)}
        removed = {p for p in removed if _is_entity_path(p)}
        if not added and not modified and not removed:
            print("SKIP no changed entity files")
            return 0
        report = run_sync(
            cfg, Gitea(cfg), Multica(cfg), added, modified, removed, before, after
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
