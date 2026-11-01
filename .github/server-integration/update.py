#!/usr/bin/env python3
"""Prepare a server snapshot without changing any source branch or published history."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile

REPOSITORY = "NoltoxGit/zEssentials-forked"
TARGET = "integration/server"
MANAGEMENT = Path(".github/server-integration")
WORKFLOW = Path(".github/workflows/server-integration.yml")
ROOT = Path.cwd()
GIT_ENV = os.environ.copy()
for key, value in {
    "GIT_AUTHOR_NAME": "github-actions[bot]",
    "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
    "GIT_COMMITTER_NAME": "github-actions[bot]",
    "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
}.items():
    GIT_ENV.setdefault(key, value)


def git(*args, cwd=ROOT, check=True, input=None):
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=GIT_ENV, input=input,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        raise RuntimeError(f"git {args[0]} failed:\n{result.stdout}{result.stderr}")
    return result



def resolve_reviewed_conflict(worktree, path, rules):
    relevant = [rule for rule in rules if rule["path"] == path]
    if not relevant:
        return False
    file = worktree / path
    if not file.is_file():
        return False
    original = file.read_text(encoding="utf-8")
    pattern = re.compile(r"^<<<<<<<[^\n]*\n(.*?)^=======\n(.*?)^>>>>>>>[^\n]*(?:\n|$)", re.M | re.S)
    matches = list(pattern.finditer(original))
    if not matches:
        return False
    result = original
    for match in reversed(matches):
        sides = [match.group(1).splitlines(), match.group(2).splitlines()]
        rule = next((rule for rule in relevant if sides == rule["sides"] or sides[::-1] == rule["sides"]), None)
        if rule is None:
            return False
        result = result[:match.start()] + "\n".join(rule["result"]) + "\n" + result[match.end():]
    file.write_text(result, encoding="utf-8")
    git("add", "--", path, cwd=worktree)
    return True


def output(**values):
    lines = "".join(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n"
                    for key, value in values.items())
    print(lines, end="")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(lines)


def main():
    if os.environ.get("GITHUB_REPOSITORY", REPOSITORY) != REPOSITORY:
        raise RuntimeError("This automation only runs in the NoltoxGit fork.")

    git("fetch", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")
    published = git("rev-parse", f"refs/remotes/origin/{TARGET}").stdout.strip()
    if git("rev-parse", "HEAD").stdout.strip() != published:
        raise RuntimeError("The integration branch changed; rerun using its latest commit.")

    base = git("rev-parse", "refs/remotes/origin/develop").stdout.strip()
    branches = []
    refs = git("for-each-ref", "--sort=refname", "--format=%(refname:strip=3)\t%(objectname)\t%(symref)",
               "refs/remotes/origin/").stdout
    for line in refs.splitlines():
        name, sha, symbolic = line.split("\t")
        if not symbolic and name not in {"main", "develop", TARGET}:
            branches.append({"name": name, "sha": sha})
    state = {"base": {"name": "develop", "sha": base}, "branches": branches}
    state_path = ROOT / MANAGEMENT / "branches.json"
    previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
    force = os.environ.get("INTEGRATION_REBUILD", "false") == "true"
    if previous == state and not force:
        output(changed=False, build=False, commit=published, worktree="")
        return

    # A normal fast-forward publication retains history even after a source branch is rebased or deleted.
    # Only the tree is rebuilt; no force push is needed.
    worktree = Path(tempfile.mkdtemp(prefix="zessentials-server-", dir=os.environ.get("RUNNER_TEMP")))
    git("worktree", "add", "--detach", str(worktree), base)
    rules = json.loads((ROOT / MANAGEMENT / "resolutions.json").read_text(encoding="utf-8"))

    for branch in branches:
        print(f"Integrating {branch['name']} ({branch['sha'][:8]})", flush=True)
        result = git("merge", "--no-ff", "-m", f"🔀 Integrate {branch['name']}", branch["sha"],
                     cwd=worktree, check=False)
        if result.returncode:
            conflicts = git("diff", "--name-only", "--diff-filter=U", cwd=worktree).stdout.splitlines()
            for path in conflicts:
                resolve_reviewed_conflict(worktree, path, rules)
            conflicts = git("diff", "--name-only", "--diff-filter=U", cwd=worktree).stdout.strip()
            merging = git("rev-parse", "--quiet", "--verify", "MERGE_HEAD", cwd=worktree, check=False)
            if conflicts or merging.returncode:
                raise RuntimeError(f"Cannot integrate {branch['name']}. Conflicts: {conflicts or 'see Git output'}\n"
                                   f"{result.stdout}{result.stderr}\nThe published server branch was kept.")
            # Only exact, reviewed conflict contents can be resolved automatically.
            git("commit", "--no-edit", cwd=worktree)

    # These files belong to the fork's integration branch, not to any upstream contribution.
    shutil.copytree(ROOT / MANAGEMENT, worktree / MANAGEMENT, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / WORKFLOW, worktree / WORKFLOW)
    (worktree / MANAGEMENT / "branches.json").write_text(
        json.dumps(state, indent=2) + "\n", encoding="utf-8")
    git("add", "--all", cwd=worktree)
    tree = git("write-tree", cwd=worktree).stdout.strip()
    old_tree = git("rev-parse", f"{published}^{{tree}}").stdout.strip()
    changed = tree != old_tree
    commit = published
    if changed:
        parents = list(dict.fromkeys([published, base] + [branch["sha"] for branch in branches]))
        args = ["commit-tree", tree]
        for parent in parents:
            args += ["-p", parent]
        message = "🔀 Update server integration\n\n- Combine develop with the current fork branches.\n\n"
        message += "\n".join(f"- {branch['name']}: {branch['sha']}" for branch in branches)
        message += "\n\nServer-Integration-Managed: true\n"
        commit = git(*args, input=message).stdout.strip()
    output(changed=changed, build=changed or force, commit=commit, worktree=worktree)


if __name__ == "__main__":
    main()
