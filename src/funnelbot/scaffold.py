from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

DATA = Path(__file__).parent / "data"
MARK = re.compile(r"\s*#manager\s*$")

ENV_TEMPLATE = """# Secrets for funnelbot. Never publish this file.
BOT_TOKEN={token}
ADMIN_ID={admin}
MANAGER_CHAT={manager}
# PROVIDER_TOKEN=
# YOOKASSA_SHOP_ID=
# YOOKASSA_SECRET_KEY=
# CRYPTO_PAY_TOKEN=
"""

GUIDE_TEXT = "This is a sample product file. Replace it with your own material and update the path in funnel.yaml.\n"
GITIGNORE = ".env\n*.db\n*.db-wal\n*.db-shm\n"


def render_template(language: str, manager: bool, sample: bool = False) -> str:
    kind = "funnel" if sample else "funnel.start"
    name = f"{kind}.ru.yaml" if language == "ru" else f"{kind}.en.yaml"
    lines: List[str] = []
    for line in (DATA / name).read_text(encoding="utf-8").splitlines():
        if MARK.search(line):
            if not manager:
                continue
            line = MARK.sub("", line)
        lines.append(line)
    return "\n".join(lines) + "\n"


def create_project(folder: Path, language: str = "ru", token: str = "", admin: str = "",
                   manager: str = "", sample: bool = False) -> List[str]:
    folder = Path(folder)
    funnel = folder / "funnel.yaml"
    if funnel.exists():
        raise FileExistsError(f"{funnel} already exists, nothing was changed")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "files").mkdir(exist_ok=True)
    funnel.write_text(render_template(language, bool(manager), sample), encoding="utf-8")
    created = ["funnel.yaml"]
    env = folder / ".env"
    if not env.exists():
        env.write_text(ENV_TEMPLATE.format(token=token, admin=admin, manager=manager), encoding="utf-8")
        created.append(".env")
    guide = folder / "files" / "guide.txt"
    if sample and not guide.exists():
        guide.write_text(GUIDE_TEXT, encoding="utf-8")
        created.append("files/guide.txt")
    ignore = folder / ".gitignore"
    if not ignore.exists():
        ignore.write_text(GITIGNORE, encoding="utf-8")
        created.append(".gitignore")
    return created


def service_unit(python: str, funnel: Path, db: Optional[Path], user: str = "") -> str:
    command = f"{python} -m funnelbot run --funnel {funnel}"
    if db:
        command += f" --db {db}"
    lines = [
        "[Unit]",
        "Description=funnelbot Telegram sales funnel",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        f"WorkingDirectory={funnel.parent}",
        f"ExecStart={command}",
        "Restart=always",
        "RestartSec=5",
    ]
    if user:
        lines.append(f"User={user}")
    lines += ["", "[Install]", "WantedBy=multi-user.target", ""]
    return "\n".join(lines)
