#!/usr/bin/env python3
"""Jira helper for the bug-reply-assistant skill. Standard library only.

Subcommands
  setup       --site S --email E            save credentials (token read from stdin or $JIRA_TOKEN)
  whoami                                    check that the credentials work
  context     KEY [--days N]                ticket + comments (QA / non-QA) + reply target + transitions, as JSON
  pending     [--days N] [--limit M]        overdue: last non-QA comment waited >= N business days;
                                            waiting: not overdue yet but addressed to QA
  post        KEY --body-file F [--attach FILE ...]   post a comment (wiki markup), embed media left-aligned at real size
  transition  KEY --to NAME                 move to the transition / status whose name matches NAME
  assign      KEY --account-id ID           assign (use "none" to unassign)
  relink      KEY --other KEY2 [--remove-blocks] [--add-relates]
  user        QUERY                         look up accountId by name / email
  log         --ticket K --type T [...]     append one line to the usage log
  stats       [--since YYYY-MM-DD]          summarise the usage log

Credentials: $JIRA_SITE / $JIRA_EMAIL / $JIRA_TOKEN (all three), else ~/.config/bug-reply-assistant/credentials.json.
QA group: $JIRA_QA_GROUP (default "qa"), the same group JQL membersOf("qa") uses.
"""
import argparse
import base64
import datetime as dt
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

CONF_DIR = Path(os.environ.get("BRA_CONFIG_DIR", Path.home() / ".config" / "bug-reply-assistant"))
CRED_FILE = CONF_DIR / "credentials.json"
QA_CACHE = CONF_DIR / "qa-members.json"
LOG_FILE = CONF_DIR / "usage-log.jsonl"
QA_GROUP = os.environ.get("JIRA_QA_GROUP", "qa")
DEFAULT_DAYS = 3


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- credentials / http

def load_creds():
    site = os.environ.get("JIRA_SITE")
    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_TOKEN")
    if CRED_FILE.exists():
        try:
            c = json.loads(CRED_FILE.read_text())
        except Exception:
            c = {}
        site = site or c.get("site")
        email = email or c.get("email")
        token = token or c.get("token")
    if not site or not email or not token:
        die("NO_CREDENTIALS: 没有 Jira 凭证。设置 JIRA_SITE / JIRA_EMAIL / JIRA_TOKEN，"
            "或运行 `jira.py setup --site <xxx.atlassian.net> --email <email>`（token 从 stdin 读）。", 2)
    return site.replace("https://", "").rstrip("/"), email, token


class Jira:
    def __init__(self):
        self.site, self.email, token = load_creds()
        self.base = f"https://{self.site}"
        self.auth = "Basic " + base64.b64encode(f"{self.email}:{token}".encode()).decode()

    def req(self, method, path, body=None, headers=None, raw=False, allow=(200, 201, 204)):
        url = path if path.startswith("http") else self.base + path
        h = {"Authorization": self.auth, "Accept": "application/json"}
        data = None
        if body is not None:
            if isinstance(body, (bytes, bytearray)):
                data = bytes(body)
            else:
                data = json.dumps(body).encode()
                h["Content-Type"] = "application/json"
        h.update(headers or {})
        r = urllib.request.Request(url, data=data, method=method, headers=h)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(r, timeout=120) as resp:
                    payload = resp.read()
                    if raw:
                        return resp.status, payload, resp.headers
                    return resp.status, (json.loads(payload) if payload else None)
            except urllib.error.HTTPError as e:
                text = e.read().decode(errors="replace")
                if e.code == 429 and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                if e.code in (401, 403):
                    die(f"AUTH_{e.code}: Jira 认证失败（{method} {path}）。token 可能已失效，"
                        "到 https://id.atlassian.com/manage-profile/security/api-tokens 重新生成后再 setup。\n"
                        + text[:300], 3)
                if e.code in allow:
                    return e.code, None
                die(f"HTTP {e.code} {method} {path}\n{text[:800]}", 1)
            except urllib.error.URLError as e:
                if attempt < 2:
                    time.sleep(2)
                    continue
                die(f"NETWORK: {e}", 1)

    def get(self, path, **params):
        if params:
            path += ("&" if "?" in path else "?") + urllib.parse.urlencode(params)
        return self.req("GET", path)[1]

    def media_uuid(self, attachment_id):
        """Attachment numeric id -> media UUID (from the 303 Location header)."""
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        r = urllib.request.Request(f"{self.base}/rest/api/3/attachment/content/{attachment_id}",
                                   headers={"Authorization": self.auth})
        try:
            opener.open(r, timeout=60)
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location", "")
            m = re.search(r"/file/([0-9a-f-]{36})/", loc)
            return m.group(1) if m else None
        return None


# ---------------------------------------------------------------- helpers

def adf_text(node, depth=0):
    """Rough ADF -> plain text, good enough for classifying comments."""
    if node is None:
        return ""
    if isinstance(node, list):
        return "".join(adf_text(n, depth) for n in node)
    t = node.get("type")
    a = node.get("attrs") or {}
    if t == "text":
        s = node.get("text", "")
        for m in node.get("marks", []) or []:
            if m.get("type") == "link":
                href = (m.get("attrs") or {}).get("href", "")
                if href and href != s:
                    s = f"{s} <{href}>"
        return s
    if t == "mention":
        txt = a.get("text") or a.get("id", "")
        return txt if txt.startswith("@") else "@" + txt
    if t == "hardBreak":
        return "\n"
    if t == "emoji":
        return a.get("text") or a.get("shortName", "")
    if t in ("inlineCard", "blockCard", "embedCard"):
        return a.get("url", "")
    if t == "media":
        return f"[media:{a.get('alt') or a.get('id', '')}]"
    if t == "status":
        return f"[{a.get('text', '')}]"
    if t == "date":
        try:
            return dt.datetime.utcfromtimestamp(int(a.get("timestamp", 0)) / 1000).strftime("%Y-%m-%d")
        except Exception:
            return ""
    inner = adf_text(node.get("content"), depth + 1)
    if t in ("paragraph", "heading", "codeBlock", "blockquote", "mediaSingle", "mediaGroup", "rule", "panel"):
        return inner.rstrip("\n") + "\n"
    if t == "listItem":
        return "- " + inner.strip("\n") + "\n"
    if t in ("tableCell", "tableHeader"):
        return inner.strip("\n") + " | "
    if t == "tableRow":
        return "| " + inner + "\n"
    return inner


def parse_time(s):
    s = re.sub(r"([+-]\d{2}):?(\d{2})$", r"\1\2", s)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def business_days_since(ts):
    """Weekdays strictly after the comment's (local) date, up to and including today."""
    if ts is None:
        return None
    start = ts.astimezone().date()
    today = dt.datetime.now().astimezone().date()
    n, d = 0, start
    while d < today:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def qa_members(j, refresh=False):
    if QA_CACHE.exists() and not refresh:
        try:
            c = json.loads(QA_CACHE.read_text())
            if c.get("group") == QA_GROUP and time.time() - c.get("ts", 0) < 86400:
                return c["members"]
        except Exception:
            pass
    members, start = {}, 0
    while True:
        r = j.get("/rest/api/3/group/member", groupname=QA_GROUP, startAt=start, maxResults=50,
                  includeInactiveUsers="true")
        for u in r.get("values", []):
            members[u["accountId"]] = u.get("displayName", "")
        if r.get("isLast", True) or not r.get("values"):
            break
        start += len(r["values"])
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    QA_CACHE.write_text(json.dumps({"group": QA_GROUP, "ts": time.time(), "members": members}, ensure_ascii=False))
    return members


def all_comments(j, key):
    out, start = [], 0
    while True:
        r = j.get(f"/rest/api/3/issue/{key}/comment", startAt=start, maxResults=100, orderBy="created")
        out += r.get("comments", [])
        start += len(r.get("comments", []))
        if start >= r.get("total", 0) or not r.get("comments"):
            break
    return out


def adf_mentions(node, out=None):
    out = [] if out is None else out
    if isinstance(node, list):
        for n in node:
            adf_mentions(n, out)
    elif isinstance(node, dict):
        if node.get("type") == "mention":
            a = node.get("attrs") or {}
            out.append({"name": (a.get("text") or "").lstrip("@"), "accountId": a.get("id")})
        adf_mentions(node.get("content"), out)
    return out


def analyse_comments(comments, qa):
    """Comments after QA's last comment are unanswered. The reply target is the LATEST unanswered
    comment that @-mentions a QA member (else the latest unanswered one): later comments supersede
    earlier ones (e.g. a design note, then "fixed in build 508, please review"). The wait is counted
    from the FIRST unanswered comment, i.e. how long QA has been silent."""
    rows = []
    for c in comments:
        acc = (c.get("author") or {}).get("accountId", "")
        rows.append({
            "id": c["id"],
            "author": (c.get("author") or {}).get("displayName", ""),
            "accountId": acc,
            "is_qa": acc in qa,
            "created": c.get("created", ""),
            "text": adf_text(c.get("body")).strip(),
            "mentions": adf_mentions(c.get("body")),
        })
    last_qa = max((i for i, r in enumerate(rows) if r["is_qa"]), default=-1)
    after = [i for i in range(last_qa + 1, len(rows)) if not rows[i]["is_qa"]]
    to_qa = [i for i in after if any(m.get("accountId") in qa for m in rows[i]["mentions"])]
    target = rows[(to_qa or after)[-1]] if after else None
    waiting = business_days_since(parse_time(rows[after[0]]["created"])) if after else None
    return rows, last_qa, after, target, waiting


PLAT_RE = {"android": re.compile(r"android", re.I), "ios": re.compile(r"\bios\b|iphone|ipad", re.I),
           "web": re.compile(r"\bweb\b|\bpc\b|\bsp\b|browser|chrome|safari", re.I)}


def platform_hints(*texts):
    blob = "\n".join(t or "" for t in texts)
    return [p for p, rx in PLAT_RE.items() if rx.search(blob)]


# ---------------------------------------------------------------- commands

def cmd_setup(a):
    token = os.environ.get("JIRA_TOKEN") or sys.stdin.readline().strip()
    if not token:
        die("没读到 token：用 `echo <token> | jira.py setup --email ...`，或先 export JIRA_TOKEN。")
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    CRED_FILE.write_text(json.dumps({"site": a.site, "email": a.email, "token": token}))
    os.chmod(CRED_FILE, 0o600)
    print(f"saved {CRED_FILE} (600)")
    cmd_whoami(a)


def cmd_whoami(a):
    j = Jira()
    me = j.get("/rest/api/3/myself")
    qa = qa_members(j, refresh=True)
    print(json.dumps({"site": j.site, "displayName": me.get("displayName"), "accountId": me.get("accountId"),
                      "in_qa_group": me.get("accountId") in qa, "qa_group": QA_GROUP, "qa_members": len(qa)},
                     ensure_ascii=False, indent=2))


def cmd_context(a):
    j = Jira()
    key = a.key.upper()
    qa = qa_members(j)
    f = j.get(f"/rest/api/3/issue/{key}", fields="summary,status,issuetype,priority,project,assignee,reporter,"
              "description,issuelinks,labels,components,fixVersions,attachment,created,updated")["fields"]
    comments = all_comments(j, key)
    rows, last_qa, after, target, waiting = analyse_comments(comments, qa)
    trans = j.get(f"/rest/api/3/issue/{key}/transitions").get("transitions", [])
    me = j.get("/rest/api/3/myself")["accountId"]
    handoff = handoff_event(j, key, me, qa, comments) if (f.get("assignee") or {}).get("accountId") == me else None
    desc = adf_text(f.get("description")).strip()

    def person(p):
        return {"name": p.get("displayName"), "accountId": p.get("accountId"),
                "is_qa": p.get("accountId") in qa} if p else None

    links = []
    for l in f.get("issuelinks", []):
        if "outwardIssue" in l:
            o, rel = l["outwardIssue"], l["type"].get("outward")
        else:
            o, rel = l["inwardIssue"], l["type"].get("inward")
        links.append({"id": l["id"], "type": l["type"]["name"], "relation": rel, "key": o["key"],
                      "summary": o["fields"].get("summary"), "status": o["fields"]["status"]["name"],
                      "issuetype": (o["fields"].get("issuetype") or {}).get("name")})
    shown = rows if a.all else rows[-a.max_comments:]
    out = {
        "key": key,
        "url": f"{j.base}/browse/{key}",
        "summary": f.get("summary"),
        "issuetype": (f.get("issuetype") or {}).get("name"),
        "status": (f.get("status") or {}).get("name"),
        "priority": (f.get("priority") or {}).get("name"),
        "project": (f.get("project") or {}).get("key"),
        "assignee": person(f.get("assignee")),
        "reporter": person(f.get("reporter")),
        "labels": f.get("labels", []),
        "components": [c["name"] for c in f.get("components", [])],
        "fixVersions": [{"name": v["name"], "releaseDate": v.get("releaseDate")} for v in f.get("fixVersions", [])],
        "platform_hints": platform_hints(f.get("summary"), desc[:2000]),
        "description": desc[:4000] + ("…(truncated)" if len(desc) > 4000 else ""),
        "links": links,
        "attachments": [{"filename": x["filename"], "created": x["created"]} for x in f.get("attachment", [])],
        "comment_count": len(rows),
        "comments": [dict(r, index=rows.index(r), text=r["text"][:2000]) for r in shown],
        "last_qa_comment_index": last_qa,
        "reply_target": dict(target, index=rows.index(target)) if target else None,
        "unanswered_comment_indexes": after,
        "unanswered_since": rows[after[0]]["created"][:10] if after else None,
        "waiting_business_days": waiting,
        "overdue": waiting is not None and waiting >= a.days,
        "overdue_threshold_days": a.days,
        "handoff": handoff,
        "transitions": [{"id": t["id"], "name": t["name"], "to": t["to"]["name"]} for t in trans],
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))


def handoff_event(j, key, me, qa, comments):
    """Latest non-QA status / assignee change on a ticket assigned to me, made after QA's last activity
    (last QA comment or last QA change). Catches "dev moved it to QA and assigned it to me, no comment"."""
    first = j.get(f"/rest/api/3/issue/{key}/changelog", maxResults=1)
    total = first.get("total", 0)
    if not total:
        return None
    hist = j.get(f"/rest/api/3/issue/{key}/changelog", startAt=max(0, total - 50), maxResults=50).get("values", [])
    qa_times = [parse_time(c.get("created", "")) for c in comments if (c.get("author") or {}).get("accountId") in qa]
    qa_times += [parse_time(h["created"]) for h in hist if (h.get("author") or {}).get("accountId") in qa]
    last_qa = max([t for t in qa_times if t], default=None)
    def changes_of(h):
        out = []
        for it in h.get("items", []):
            if it.get("field") == "assignee" and it.get("to") == me:
                out.append(f"assignee → {it.get('toString')}")
            elif it.get("field") == "status":
                out.append(f"{it.get('fromString')} → {it.get('toString')}")
        return out

    found = None
    for h in reversed(hist):
        who = (h.get("author") or {})
        t = parse_time(h["created"])
        if last_qa and t and t <= last_qa:
            break
        if who.get("accountId") in qa:
            continue
        ch = changes_of(h)
        if not ch:
            continue
        if found is None:
            found = {"by": who.get("displayName"), "byId": who.get("accountId"), "at": h["created"],
                     "t": t, "changes": ch}
        elif who.get("accountId") == found["byId"] and t and found["t"] - t <= dt.timedelta(minutes=10):
            # Same person, same hand-off (status + assignee are often two changelog entries).
            found["changes"] = ch + found["changes"]
            found["at"] = h["created"]
        else:
            break
    if found:
        found.pop("t"); found.pop("byId")
    return found


def cmd_pending(a):
    j = Jira()
    qa = qa_members(j)
    me = j.get("/rest/api/3/myself")["accountId"]
    jql = a.jql or ("(assignee = currentUser() OR reporter = currentUser() OR watcher = currentUser()) "
                    "AND statusCategory != Done AND updated >= -60d ORDER BY updated DESC")
    issues, token = [], None
    while len(issues) < a.limit:
        q = {"jql": jql, "maxResults": min(50, a.limit - len(issues)),
             "fields": ["summary", "status", "priority", "comment", "assignee"]}
        if token:
            q["nextPageToken"] = token
        _, r = j.req("POST", "/rest/api/3/search/jql", q)
        issues += r.get("issues", [])
        token = r.get("nextPageToken")
        if not token or r.get("isLast") or not r.get("issues"):
            break
    def examine(issue):
        f = issue["fields"]
        cm = (f.get("comment") or {})
        comments = cm.get("comments", [])
        if cm.get("total", 0) > len(comments):
            comments = all_comments(j, issue["key"])
        rows, _, after, target, _ = analyse_comments(comments, qa)
        assigned_to_me = ((f.get("assignee") or {}).get("accountId") == me)
        handoff = handoff_event(j, issue["key"], me, qa, comments) if assigned_to_me else None
        if not after and not handoff:
            return None
        starts = [parse_time(rows[after[0]]["created"])] if after else []
        if handoff:
            starts.append(parse_time(handoff["at"]))
        since = min(t for t in starts if t)
        waiting = business_days_since(since)
        mentions_qa = bool(target) and any(m["accountId"] in qa for m in target["mentions"])
        # Why this ticket is waiting on QA: a comment @-mentions QA, it was handed to me, or a dev
        # commented on a ticket that is in my name.
        reasons = []
        if mentions_qa:
            reasons.append("mentions_qa")
        if handoff:
            reasons.append("handed_to_you")
        if assigned_to_me and after and not mentions_qa:
            reasons.append("comment_on_your_ticket")
        h = {"key": issue["key"], "url": f"{j.base}/browse/{issue['key']}", "summary": f.get("summary"),
             "status": f["status"]["name"], "priority": (f.get("priority") or {}).get("name"),
             "waiting_business_days": waiting, "since": since.astimezone().strftime("%Y-%m-%d"),
             "for_qa": bool(reasons), "reasons": reasons, "mentions_qa": mentions_qa,
             "unanswered_count": len(after), "handoff": handoff}
        if target:
            h.update({"from": target["author"], "mentions": [m["name"] for m in target["mentions"]],
                      "excerpt": target["text"][:140].replace("\n", " ")})
        else:
            h.update({"from": handoff["by"], "mentions": [],
                      "excerpt": "（没有评论）" + "，".join(handoff["changes"])})
        return h

    # Per-ticket reads (comments, changelog) are independent: run them in parallel.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = [h for h in ex.map(examine, issues) if h]
    overdue, waiting_list = [], []
    for h in results:
        if h["waiting_business_days"] >= a.days:
            overdue.append(h)
        elif h["for_qa"]:
            waiting_list.append(h)
    # Tickets waiting on QA first, then the longest wait.
    overdue.sort(key=lambda h: (not h["for_qa"], -h["waiting_business_days"]))
    waiting_list.sort(key=lambda h: -h["waiting_business_days"])
    print(json.dumps({"threshold_days": a.days, "scanned": len(issues),
                      "overdue": overdue, "waiting": waiting_list},
                     ensure_ascii=False, indent=1))


def _probe(path):
    if not shutil.which("ffprobe"):
        return None
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate",
                        "-of", "json", str(path)], capture_output=True, text=True)
    try:
        return json.loads(p.stdout).get("streams", [])
    except Exception:
        return None


def prepare_file(src, tmp, taken):
    """Copy to a space-free, unique name; videos: strip audio, HEVC/VFR -> H.264 30fps (Jira can't preview HEVC)."""
    src = Path(src).expanduser()
    if not src.exists():
        die(f"附件不存在: {src}")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", src.stem).strip("_") or "file"
    ext = src.suffix.lower()
    is_video = ext in (".mp4", ".mov", ".m4v", ".webm")
    out_ext = ".mp4" if is_video else ext
    name, n = f"{stem}{out_ext}", 2
    while name.lower() in taken:
        name, n = f"{stem}-{n}{out_ext}", n + 1
    taken.add(name.lower())
    dst = Path(tmp) / name
    note = ""
    if is_video and shutil.which("ffmpeg"):
        streams = _probe(src) or []
        v = next((s for s in streams if s.get("codec_type") == "video"), {})
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        vfr = v.get("r_frame_rate") and v.get("r_frame_rate") != v.get("avg_frame_rate")
        if v.get("codec_name") == "hevc" or vfr:
            cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", "-vf",
                   "fps=30,scale=in_range=pc:out_range=tv,format=yuv420p", "-c:v", "libx264", "-profile:v", "main",
                   "-level", "4.0", "-crf", "20", "-r", "30", "-movflags", "+faststart", str(dst)]
            note = "转成 H.264 30fps、去音轨"
        else:
            cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", "-c:v", "copy", "-movflags", "+faststart",
                   str(dst)]
            note = "去音轨" if has_audio else "重新封装"
        if subprocess.run(cmd).returncode != 0:
            shutil.copy(src, dst)
            note = "ffmpeg 失败，原样上传"
    else:
        shutil.copy(src, dst)
    return dst, note


def dims(path):
    p = str(path)
    if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic") and shutil.which("sips"):
        o = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", p], capture_output=True, text=True).stdout
        w = re.search(r"pixelWidth: (\d+)", o)
        h = re.search(r"pixelHeight: (\d+)", o)
        if w and h:
            return int(w.group(1)), int(h.group(1))
    v = next((s for s in (_probe(p) or []) if s.get("codec_type") == "video"), None)
    if v and v.get("width"):
        return int(v["width"]), int(v["height"])
    return None


def upload(j, key, path):
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    _, r = j.req("POST", f"/rest/api/3/issue/{key}/attachments", body,
                 headers={"X-Atlassian-Token": "no-check", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    return r[0]


def cmd_post(a):
    j = Jira()
    key = a.key.upper()
    text = Path(a.body_file).expanduser().read_text().rstrip()
    existing = {x["filename"].lower() for x in
                j.get(f"/rest/api/3/issue/{key}", fields="attachment")["fields"].get("attachment", [])}
    tmp = tempfile.mkdtemp(prefix="bra-")
    uploaded, failed = [], []
    for f in a.attach or []:
        try:
            p, note = prepare_file(f, tmp, existing)
            att = upload(j, key, p)
            uploaded.append({"src": str(f), "name": p.name, "id": att["id"], "dims": dims(p), "note": note})
        except SystemExit:
            raise
        except Exception as e:  # keep going, report at the end
            failed.append({"src": str(f), "error": str(e)})
    body = text
    for u in uploaded:
        body += f"\n\n!{u['name']}!"
    _, c = j.req("POST", f"/rest/api/2/issue/{key}/comment", {"body": body})
    cid = c["id"]
    if uploaded:
        # The v2 wiki post resolves !file! to media nodes, centred at thumbnail size. Re-read the ADF and
        # only change those nodes: left-aligned, real pixels. Everything else (mentions, links) stays.
        uuid_to_dims = {}
        for u in uploaded:
            mu = j.media_uuid(u["id"])
            if mu:
                uuid_to_dims[mu] = u["dims"]
        order = [u["dims"] for u in uploaded]
        adf = j.get(f"/rest/api/3/issue/{key}/comment/{cid}")["body"]
        seen = 0

        def fix(n):
            nonlocal seen
            if isinstance(n, list):
                for x in n:
                    fix(x)
                return
            if not isinstance(n, dict):
                return
            if n.get("type") == "mediaSingle":
                n["attrs"] = {"layout": "align-start"}
            if n.get("type") == "media":
                at = n.setdefault("attrs", {})
                d = uuid_to_dims.get(at.get("id")) or (order[seen] if seen < len(order) else None)
                seen += 1
                at.setdefault("collection", "")
                if d:
                    at["width"], at["height"] = d
            fix(n.get("content"))
        fix(adf.get("content"))
        j.req("PUT", f"/rest/api/3/issue/{key}/comment/{cid}", {"body": adf})
    shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({"comment_id": cid,
                      "url": f"{j.base}/browse/{key}?focusedCommentId={cid}",
                      "uploaded": [{k: u[k] for k in ("src", "name", "dims", "note")} for u in uploaded],
                      "failed": failed}, ensure_ascii=False, indent=1))


def cmd_transition(a):
    j = Jira()
    key = a.key.upper()
    ts = j.get(f"/rest/api/3/issue/{key}/transitions").get("transitions", [])
    want = a.to.strip().lower()
    hit = next((t for t in ts if t["name"].lower() == want), None) or \
        next((t for t in ts if t["to"]["name"].lower() == want), None)
    if not hit:
        print(json.dumps({"error": "NO_MATCH", "wanted": a.to,
                          "available": [{"id": t["id"], "name": t["name"], "to": t["to"]["name"]} for t in ts]},
                         ensure_ascii=False, indent=1))
        sys.exit(4)
    j.req("POST", f"/rest/api/3/issue/{key}/transitions", {"transition": {"id": hit["id"]}})
    now = j.get(f"/rest/api/3/issue/{key}", fields="status")["fields"]["status"]["name"]
    print(json.dumps({"key": key, "transition": hit["name"], "status_now": now}, ensure_ascii=False))


def cmd_assign(a):
    j = Jira()
    key = a.key.upper()
    acc = None if a.account_id.lower() == "none" else a.account_id
    j.req("PUT", f"/rest/api/3/issue/{key}/assignee", {"accountId": acc})
    now = j.get(f"/rest/api/3/issue/{key}", fields="assignee")["fields"].get("assignee") or {}
    print(json.dumps({"key": key, "assignee_now": now.get("displayName")}, ensure_ascii=False))


def cmd_relink(a):
    j = Jira()
    key, other = a.key.upper(), a.other.upper()
    links = j.get(f"/rest/api/3/issue/{key}", fields="issuelinks")["fields"].get("issuelinks", [])
    removed = []
    if a.remove_blocks:
        for l in links:
            o = (l.get("outwardIssue") or l.get("inwardIssue") or {}).get("key")
            if l["type"]["name"].lower() == "blocks" and o == other:
                j.req("DELETE", f"/rest/api/3/issueLink/{l['id']}")
                removed.append(l["id"])
    added = False
    if a.add_relates:
        already = any(l["type"]["name"].lower() == "relates" and
                      (l.get("outwardIssue") or l.get("inwardIssue") or {}).get("key") == other for l in links)
        if not already:
            j.req("POST", "/rest/api/3/issueLink",
                  {"type": {"name": "Relates"}, "inwardIssue": {"key": key}, "outwardIssue": {"key": other}})
            added = True
    print(json.dumps({"key": key, "other": other, "removed_blocks_links": removed, "added_relates": added}))


def cmd_user(a):
    j = Jira()
    r = j.get("/rest/api/3/user/search", query=a.query, maxResults=10)
    print(json.dumps([{"name": u.get("displayName"), "accountId": u.get("accountId"), "active": u.get("active")}
                      for u in r], ensure_ascii=False, indent=1))


def cmd_log(a):
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "ticket": a.ticket.upper(),
           "reply_type": a.type, "template": a.template, "outcome": a.outcome,
           "draft_edited": a.edited, "gate_skips": [], "actions": a.action or [], "overdue_days": a.overdue_days}
    for s in a.skip or []:
        item, _, reason = s.partition(":")
        rec["gate_skips"].append({"item": item.strip(), "reason": reason.strip()})
    with LOG_FILE.open("a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"logged → {LOG_FILE}")


def cmd_stats(a):
    if not LOG_FILE.exists():
        die("还没有日志。")
    recs = [json.loads(l) for l in LOG_FILE.read_text().splitlines() if l.strip()]
    if a.since:
        recs = [r for r in recs if r["ts"][:10] >= a.since]
    posted = [r for r in recs if r.get("outcome") == "posted"]
    by_type = {}
    for r in recs:
        by_type[r["reply_type"]] = by_type.get(r["reply_type"], 0) + 1
    skips = [dict(s, ticket=r["ticket"]) for r in recs for s in r.get("gate_skips", [])]
    edited = [r for r in posted if r.get("draft_edited") in ("yes", "no")]
    print(json.dumps({
        "calls": len(recs), "posted": len(posted), "by_type": by_type,
        "draft_used_unchanged_rate": (round(sum(r["draft_edited"] == "no" for r in edited) / len(edited), 2)
                                      if edited else None),
        "gate_skips": skips}, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("setup"); p.add_argument("--email", required=True); p.add_argument("--site", required=True)
    p.set_defaults(fn=cmd_setup)
    sp.add_parser("whoami").set_defaults(fn=cmd_whoami)
    p = sp.add_parser("context"); p.add_argument("key"); p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--max-comments", type=int, default=20); p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_context)
    p = sp.add_parser("pending"); p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--limit", type=int, default=50); p.add_argument("--jql"); p.set_defaults(fn=cmd_pending)
    p = sp.add_parser("post"); p.add_argument("key"); p.add_argument("--body-file", required=True)
    p.add_argument("--attach", nargs="*"); p.set_defaults(fn=cmd_post)
    p = sp.add_parser("transition"); p.add_argument("key"); p.add_argument("--to", required=True)
    p.set_defaults(fn=cmd_transition)
    p = sp.add_parser("assign"); p.add_argument("key"); p.add_argument("--account-id", required=True)
    p.set_defaults(fn=cmd_assign)
    p = sp.add_parser("relink"); p.add_argument("key"); p.add_argument("--other", required=True)
    p.add_argument("--remove-blocks", action="store_true"); p.add_argument("--add-relates", action="store_true")
    p.set_defaults(fn=cmd_relink)
    p = sp.add_parser("user"); p.add_argument("query"); p.set_defaults(fn=cmd_user)
    p = sp.add_parser("log"); p.add_argument("--ticket", required=True); p.add_argument("--type", required=True)
    p.add_argument("--template", default=""); p.add_argument("--outcome", default="posted",
                                                             choices=["posted", "draft_only", "cancelled", "no_draft"])
    p.add_argument("--edited", default="unknown", choices=["yes", "no", "unknown"])
    p.add_argument("--skip", nargs="*", help='"item: reason"'); p.add_argument("--action", nargs="*")
    p.add_argument("--overdue-days", type=int); p.set_defaults(fn=cmd_log)
    p = sp.add_parser("stats"); p.add_argument("--since"); p.set_defaults(fn=cmd_stats)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
