"""Regenerate img/dark.svg and img/light.svg with live GitHub stats.

Runs daily via GitHub Actions. Stdlib only, no dependencies.
"""
from __future__ import annotations

import calendar
import html
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

USER = "9Ashwin"
JOINED = date(2023, 9, 3)
JOINED_YEAR = 2023
W = 56
IMG_DIR = Path("img")

ART = r"""+===+**+*++=:..-++*+=+++*+++=-:..:.......::..
+==++++**++-....:==+-==-==+=-:....:::::::---+
******++++=::.....:..:.......::...:====+++++=
=+*###****=::::.:.::::.....::...::-==+++++==+
-=+##@**%%#:::.:.:-==:.....-=-..:.:+++++++++*
===+#*+#@#*:.:::::.....:-:. .....::=*********
====++#*+==::-::::.....:-:.....::::-+====++**
=====++=*%*-:::-::...::=++-::..:::.-+++++====
===++=+#*+=-::::::...-*++++-.:::::.:-==++*#**
===**+++=+=-:::.....:-=====::::::..-*++====##
=+**++++++++:........:-=+--:::::::-=+%##*+-=#
++++++++++=:.....:::..::::::::::::-**+#####++
=--:--====:........::::::::::::::::=#*#%###%*
.......::.............:::...........:-=*#####
   .    .....................::...    .-+####
.....................::::::::::...     .-+%%*
..................::::::---::::.......  .:--:
......... ...:..:-=-:::-=-:::::::........::::
...........:-::-+*==============-::..::::----
.......:::-====+******+=++++++===-:::--------
:...::-+=-=+#*++*#####***++++++=-:-------====
::::-=+***++*#**#######**+++*+==-----=---====
--====*###****####*#######*+===---==---======"""

assert max(len(line) for line in ART.strip("\n").split("\n")) <= 46

TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("ACCESS_TOKEN") or ""
PRIV_TOKEN = os.environ.get("ACCESS_TOKEN") or TOKEN


def repo_scope() -> str:
    return "" if os.environ.get("ACCESS_TOKEN") else ", privacy: PUBLIC"


def gh(url: str, payload: dict | None = None, token: str | None = None, retries: int = 3):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode() if payload else None,
                headers={
                    "Authorization": f"Bearer {token or TOKEN}",
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last_err)


def graphql(query: str, variables: dict | None = None, token: str | None = None):
    _, resp = gh("https://api.github.com/graphql", {"query": query, "variables": variables or {}}, token)
    if resp.get("errors"):
        raise RuntimeError(resp["errors"])
    return resp["data"]


def age(b: date, t: date) -> tuple[int, int, int]:
    years = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    months = (t.month - b.month - (t.day < b.day)) % 12
    if t.day >= b.day:
        days = t.day - b.day
    else:
        pm_year, pm = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
        days = calendar.monthrange(pm_year, pm)[1] - b.day + t.day
    return years, months, days


def fetch_stats() -> dict:
    yr_aliases = "\n".join(
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y + 1}-01-01T00:00:00Z")'
        " { totalCommitContributions restrictedContributionsCount }"
        for y in range(JOINED_YEAR, datetime.now(timezone.utc).year + 1)
    )
    contrib = graphql(f'query {{ user(login: "{USER}") {{ {yr_aliases} }} }}')["user"]
    commits = sum(v["totalCommitContributions"] + v["restrictedContributionsCount"] for v in contrib.values())

    scope = repo_scope()
    u = graphql(
        f"""
    query {{
      user(login: "{USER}") {{
        id
        followers {{ totalCount }}
        repositories(first: 100, ownerAffiliations: OWNER{scope}) {{
          totalCount
          nodes {{ name stargazerCount isFork }}
        }}
        repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) {{
          totalCount
        }}
      }}
    }}""",
        token=PRIV_TOKEN,
    )["user"]

    _, rest_user = gh(f"https://api.github.com/users/{USER}", token=TOKEN)
    public_repos = rest_user.get("public_repos", u["repositories"]["totalCount"])

    nodes = [n for n in u["repositories"]["nodes"] if not n["isFork"]]
    stats = {
        "followers": u["followers"]["totalCount"],
        "repos": public_repos,
        "contributed": u["repositoriesContributedTo"]["totalCount"],
        "stars": sum(n["stargazerCount"] for n in nodes),
        "commits": commits,
    }
    stats.update(loc([n["name"] for n in nodes], u["id"]))
    return stats


LOC_QUERY = """
query($owner: String!, $name: String!, $id: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: 100, author: {id: $id}, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { additions deletions }
      }
    } } }
  }
}"""


def loc_repo(name: str, user_id: str) -> tuple[int, int]:
    add = rem = 0
    cursor = None
    while True:
        ref = graphql(
            LOC_QUERY,
            {"owner": USER, "name": name, "id": user_id, "cursor": cursor},
            token=PRIV_TOKEN,
        )["repository"]["defaultBranchRef"]
        if ref is None:
            break
        h = ref["target"]["history"]
        add += sum(n["additions"] for n in h["nodes"])
        rem += sum(n["deletions"] for n in h["nodes"])
        if not h["pageInfo"]["hasNextPage"]:
            break
        cursor = h["pageInfo"]["endCursor"]
    return add, rem


def loc(repo_names: list[str], user_id: str) -> dict:
    add = rem = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(loc_repo, name, user_id): name for name in repo_names}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                a, r = fut.result()
                add += a
                rem += r
            except Exception as e:
                print(f"loc {name}: {e}")
    return {"loc_add": add, "loc_del": rem, "loc": add - rem}


PALETTES = {
    "dark": {
        "bg": "#0d1117",
        "border": "#30363d",
        "art": "#8b949e",
        "h": "#58a6ff",
        "k": "#ffa657",
        "v": "#c9d1d9",
        "d": "#484f58",
        "g": "#3fb950",
        "r": "#f85149",
    },
    "light": {
        "bg": "#ffffff",
        "border": "#d0d7de",
        "art": "#57606a",
        "h": "#0969da",
        "k": "#953800",
        "v": "#24292f",
        "d": "#afb8c1",
        "g": "#1a7f37",
        "r": "#cf222e",
    },
}


def kv(key: str, val: str, width: int = W) -> list[tuple[str, str]]:
    dots = "." * max(width - len(key) - len(str(val)) - 3, 1)
    return [(f"{key}: ", "k"), (dots + " ", "d"), (str(val), "v")]


def kv2(k1: str, v1: str, k2: str, v2: str) -> list[tuple[str, str]]:
    left = kv(k1, v1, 30)
    return left + [(" | ", "d")] + kv(k2, v2, 23)


def rule(title: str = "") -> list[tuple[str, str]]:
    label = f"─ {title} " if title else ""
    return [(label, "h"), ("─" * (W - len(label)), "d")]


def info_lines(s: dict) -> list[list[tuple[str, str]]]:
    y, m, d = age(JOINED, date.today())
    n = lambda x: f"{x:,}"
    handle = USER.lower()
    return [
        [(f"{handle}@github ", "h"), ("─" * (W - len(handle) - 8), "d")],
        [],
        kv("OS", "macOS, Linux"),
        kv("Uptime", f"{y} years, {m} months, {d} days"),
        kv("Host", "Ashwin"),
        kv("Kernel", "building agent CLIs"),
        kv("IDE", "Cursor"),
        [],
        kv("Languages.Programming", "TypeScript, Go, Python, Rust"),
        kv("Languages.Real", "Chinese, English"),
        kv("Currently", "flow-one · sticker-cli · ShuaDouyin · x-cli · im-toolbox"),
        [],
        rule("Contact"),
        kv("Site", "github.com/9Ashwin"),
        kv("X", "@NarcissusWWWWWW"),
        [],
        rule("GitHub Stats"),
        kv2("Repos", f"{s['repos']} {{Contributed: {s['contributed']}}}", "Stars", n(s["stars"])),
        kv2("Commits", n(s["commits"]), "Followers", n(s["followers"])),
        [
            ("Lines of Code: ", "k"),
            (n(s["loc"]), "v"),
            (" ( ", "d"),
            (n(s["loc_add"]) + "++", "g"),
            (", ", "d"),
            (n(s["loc_del"]) + "--", "r"),
            (" )", "d"),
        ],
    ]


def art_layout() -> tuple[list[str], float, float]:
    lines = ART.strip("\n").split("\n")
    n_lines = len(lines)
    y_top = 40 + (500 - 40 - n_lines * 15) / 2
    left = min((i for line in lines for i, ch in enumerate(line) if ch != " "), default=0)
    right = max((i for line in lines for i, ch in enumerate(line) if ch != " "), default=0)
    width_chars = max(len(line) for line in lines)
    char_shift = (width_chars / 2) - ((left + right) / 2)
    x_base = 10 + char_shift * 7.9
    return lines, y_top, x_base


def render(mode: str, stats: dict) -> str:
    p = PALETTES[mode]
    art_lines, y_top, x_base = art_layout()
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="840" height="500" viewBox="0 0 840 500" '
        f'font-family="Consolas, Menlo, monospace" font-size="13px">',
        f'<rect x="0.5" y="0.5" width="839" height="499" rx="10" fill="{p["bg"]}" stroke="{p["border"]}"/>',
    ]
    for i, line in enumerate(art_lines):
        y = y_top + i * 15
        out.append(
            f'<text x="{x_base:.1f}" y="{y:.1f}" fill="{p["art"]}" xml:space="preserve">{html.escape(line)}</text>'
        )
    for i, segs in enumerate(info_lines(stats)):
        if not segs:
            continue
        spans = "".join(f'<tspan fill="{p[c]}">{html.escape(t)}</tspan>' for t, c in segs)
        out.append(f'<text x="390" y="{45 + i * 21}" xml:space="preserve">{spans}</text>')
    out.append("</svg>")
    return "\n".join(out)


def selfcheck() -> None:
    assert age(JOINED, date(2026, 11, 5)) == (3, 2, 2)
    assert age(date(2000, 3, 31), date(2026, 4, 1)) == (26, 0, 1)
    assert len("".join(t for t, _ in kv("OS", "macOS, Linux"))) == W
    _, _, x = art_layout()
    assert x >= 10


if __name__ == "__main__":
    selfcheck()
    stats = fetch_stats()
    print("stats:", stats)
    IMG_DIR.mkdir(exist_ok=True)
    for mode, fname in (("dark", "dark.svg"), ("light", "light.svg")):
        path = IMG_DIR / fname
        path.write_text(render(mode, stats), encoding="utf-8")
        print(f"wrote {path}")
