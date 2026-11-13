#!/usr/bin/env python3
"""检查 GitHub 主分支的插件版本，在 macOS 空闲时交给 Codex 安装。"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

REPO = "MR-Yellowbots/codex-title-kit"
MARKETPLACE = "yellowbots-title-kit"
PLUGIN = "codex-title-kit"
PLUGIN_ID = f"{PLUGIN}@{MARKETPLACE}"
DEFAULT_IDLE_SECONDS = 600


def run(args, *, env=None, timeout=90):
    return subprocess.check_output(args, text=True, env=env, timeout=timeout).strip()


def version_key(version):
    if not isinstance(version, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("插件版本须为正式的 X.Y.Z 版本")
    return tuple(map(int, version.split(".")))


def remote_version(gh):
    path = f"repos/{REPO}/contents/.codex-plugin/plugin.json?ref=main"
    manifest = json.loads(run([gh, "api", path, "-H", "Accept: application/vnd.github.raw+json"]))
    if manifest["name"] != PLUGIN:
        raise ValueError("远端插件身份不匹配")
    return manifest["version"]


def installed_version(codex):
    data = json.loads(run([codex, "plugin", "list", "-m", MARKETPLACE, "--json"]))
    for plugin in data["installed"]:
        if plugin["pluginId"] == PLUGIN_ID and plugin.get("enabled"):
            source = plugin.get("marketplaceSource", {})
            if source.get("sourceType") != "git":
                raise ValueError("自动更新要求使用 Git 市场安装")
            remote = source.get("source", "").removesuffix(".git").rstrip("/")
            if remote.casefold() not in {REPO.casefold(), f"https://github.com/{REPO}".casefold()}:
                raise ValueError("已安装插件的 Git 来源与发布仓库不匹配")
            return plugin["version"]
    raise ValueError("找不到已启用的 Git 版插件")


def idle_seconds():
    out = run(["/usr/sbin/ioreg", "-r", "-c", "IOHIDSystem", "-d", "1"], timeout=10)
    result = re.search(r'"HIDIdleTime"\s*=\s*([0-9]+)', out)
    return int(result[1]) / 1e9 if result else 0


def notify(message):
    run(["/usr/bin/osascript", "-e",
         f'display notification {json.dumps(message, ensure_ascii=False)} with title "Codex Title Kit"'],
        timeout=10)


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def install_update(codex, gh, target, minimum_idle):
    # 仅给本次 Codex 子进程提供 gh 的 Git 凭据助手，不修改用户 Git 配置。
    env = os.environ.copy()
    env.update(GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="credential.https://github.com.helper",
               GIT_CONFIG_VALUE_0="", GIT_CONFIG_KEY_1="credential.https://github.com.helper",
               GIT_CONFIG_VALUE_1=f"!{shlex.quote(gh)} auth git-credential", GIT_TERMINAL_PROMPT="0")
    run([codex, "plugin", "marketplace", "upgrade", MARKETPLACE, "--json"], env=env)
    if remote_version(gh) != target:
        return "release_changed"
    if idle_seconds() < minimum_idle:
        return "waiting_for_idle"
    run([codex, "plugin", "add", PLUGIN_ID, "--json"], env=env)
    if installed_version(codex) != target:
        raise RuntimeError("安装版本与检查到的版本不一致")
    return "updated"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", required=True)
    parser.add_argument("--gh", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--idle-seconds", type=int, default=DEFAULT_IDLE_SECONDS)
    parser.add_argument("--check", action="store_true", help="只检查版本，不通知或安装")
    args = parser.parse_args()
    current, target = installed_version(args.codex), remote_version(args.gh)
    if version_key(target) <= version_key(current):
        status = "current"
    elif args.check:
        status = "available"
    else:
        state = json.loads(args.state.read_text()) if args.state.exists() else {}
        if state.get("notified") != target:
            notify(f"发现 {target} 版，将在电脑空闲时安装。")
            state["notified"] = target
            save_state(args.state, state)
        if idle_seconds() < args.idle_seconds:
            status = "waiting_for_idle"
        else:
            status = install_update(args.codex, args.gh, target, args.idle_seconds)
            if status == "updated":
                notify(f"已安装 {target} 版。若 Codex 要求重新信任 Hook，请在 /hooks 中确认。")
    print(json.dumps({"status": status, "installed": target if status == "updated" else current,
                      "release": target}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"更新检查失败（{type(error).__name__}）", file=sys.stderr)
        sys.exit(1)
