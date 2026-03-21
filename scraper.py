"""
Lofter Tag Monitor - scraper.py
每小时整点运行，爬取：
  1. 官方"参与"总数（HTML 解析）
  2. 最新帖子列表（DWR API），只计本小时新发的帖子
每次爬取后实时结算当天；每天 0 点额外归档昨天。
"""

import json
import os
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────────────
TAG_URL    = "https://www.lofter.com/tag/%E5%88%83%E6%81%92/new"
TAG_NAME   = "%E5%88%83%E6%81%92"
DWR_URL    = "http://www.lofter.com/dwr/call/plaincall/TagBean.search.dwr"
DATA_FILE  = "data/records.json"
LOGIN_KEY  = "LOFTER-PHONE-LOGIN-AUTH"
LOGIN_AUTH = os.environ.get("LOFTER_AUTH", "")
CST        = timezone(timedelta(hours=8))

# 基准点：2026-03-21 15:00 CST，官方参与数 65786
BASELINE_COUNT = 65786
BASELINE_TIME  = "2026-03-21 15:00"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Host":    "www.lofter.com",
    "Referer": TAG_URL,
}

# ── 工具 ──────────────────────────────────────────────────────────────────────

def cst_now() -> datetime:
    return datetime.now(CST)

def load_data() -> dict:
    p = Path(DATA_FILE)
    if p.exists():
        raw = p.read_text(encoding="utf-8").strip()
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                print("[warn] records.json 解析失败，重置")
    return {
        "baseline": {"count": BASELINE_COUNT, "time": BASELINE_TIME},
        "hourly": [],   # 永久保留，不删除
        "daily":  [],   # 每天 0 点归档
        "today":  {},   # 实时结算
    }

def save_data(data: dict):
    Path("data").mkdir(exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── 登录 session ──────────────────────────────────────────────────────────────

def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get("http://www.lofter.com/login",
                    params={"urschecked": "true"}, timeout=15)
    except Exception as e:
        print(f"[warn] 登录页失败: {e}")
    if LOGIN_AUTH:
        session.cookies.set(LOGIN_KEY, LOGIN_AUTH, domain="www.lofter.com")
    else:
        print("[warn] LOFTER_AUTH 为空")
    try:
        session.get("http://www.lofter.com/", timeout=15)
    except Exception as e:
        print(f"[warn] 主页失败: {e}")
    return session

# ── 爬取官方参与数 ────────────────────────────────────────────────────────────

def fetch_official_count(session: requests.Session):
    try:
        resp  = session.get(TAG_URL, timeout=15)
        html  = resp.text
        match = re.search(r'([\d.]+)(万?)参与', html)
        if not match:
            print("[warn] 未找到参与数")
            return None
        num = float(match.group(1))
        if match.group(2) == "万":
            num = int(num * 10000)
        else:
            num = int(num)
        print(f"[info] 官方参与数: {num}")
        return num
    except Exception as e:
        print(f"[error] fetch_official_count: {e}")
        return None

# ── 爬取本小时新帖 ────────────────────────────────────────────────────────────

def fetch_new_posts(session: requests.Session, since_ts_ms: int) -> list:
    """
    只返回 publishTime > since_ts_ms 的帖子。
    since_ts_ms 应该是上次爬取时「最新那篇帖子」的时间戳（毫秒）。
    第一次运行时传入当前时间戳，等于只统计此后新发的帖子。
    """
    get_num   = 100
    got_num   = 0
    all_posts = []
    seen      = set()

    data = {
        "callCount":       "1",
        "httpSessionId":   "",
        "scriptSessionId": "${scriptSessionId}187",
        "c0-id":           "0",
        "batchId":         "870178",
        "c0-scriptName":   "TagBean",
        "c0-methodName":   "search",
        "c0-param0":       f"string:{TAG_NAME}",
        "c0-param1":       "number:0",
        "c0-param2":       "string:",
        "c0-param3":       "string:new",
        "c0-param4":       "boolean:false",
        "c0-param5":       "number:0",
        "c0-param6":       f"number:{get_num}",
        "c0-param7":       f"number:{got_num}",
        "c0-param8":       f"number:{int(time.time() * 1000)}",
    }

    while True:
        try:
            resp    = session.post(DWR_URL, data=data, timeout=20)
            content = resp.content.decode("utf-8")
        except Exception as e:
            print(f"[error] DWR 失败: {e}")
            break

        chunks = content.split("activityTags")[1:]
        if not chunks:
            print("[info] 无帖子返回")
            break

        reached_old = False
        for chunk in chunks:
            pm = re.search(r's\d+\.permalink="(.*?)"', chunk)
            if not pm:
                continue
            permalink = pm.group(1)
            if permalink in seen:
                continue
            seen.add(permalink)

            ts_m = re.search(r's\d+\.publishTime=(\d+);', chunk)
            if not ts_m:
                continue
            pub_ts = int(ts_m.group(1))

            # 遇到比上次最新帖子还旧的，停止
            if pub_ts <= since_ts_ms:
                reached_old = True
                break

            pub_str = datetime.fromtimestamp(
                pub_ts / 1000, tz=CST).strftime("%Y-%m-%d %H:%M:%S")
            all_posts.append({
                "permalink":      permalink,
                "publishTime":    pub_ts,
                "publishTimeStr": pub_str,
            })

        if reached_old:
            print("[info] 已追溯到上次最新帖，停止翻页")
            break

        got_num += get_num
        if len(chunks) < get_num:
            break

        last_ts_m = re.search(r's\d+\.publishTime=(\d+);', chunks[-1])
        if not last_ts_m:
            break
        data["c0-param6"] = f"number:{get_num}"
        data["c0-param7"] = f"number:{got_num}"
        data["c0-param8"] = f"number:{last_ts_m.group(1)}"
        time.sleep(0.5)

    print(f"[info] 本次新帖: {len(all_posts)} 篇")
    return all_posts

# ── 结算 ──────────────────────────────────────────────────────────────────────

def settle_today(data: dict, today_str: str):
    """每次爬取后都调用，实时更新 data['today']"""
    today_hourly = [r for r in data["hourly"] if r.get("date") == today_str]
    total_new    = sum(r.get("new_posts_count", 0) for r in today_hourly)
    counts       = [r["official_count"] for r in today_hourly
                    if r.get("official_count") is not None]
    data["today"] = {
        "date":            today_str,
        "total_new_posts": total_new,
        "official_latest": counts[-1] if counts else None,
        "hours_recorded":  len(today_hourly),
    }
    print(f"[info] 今日实时: 用户发帖={total_new}, 官方参与={counts[-1] if counts else '—'}")

def settle_yesterday(data: dict, yesterday_str: str):
    """0 点时调用，把昨天数据归档到 daily"""
    if any(d["date"] == yesterday_str for d in data["daily"]):
        print(f"[info] {yesterday_str} 已归档")
        return
    yest = [r for r in data["hourly"] if r.get("date") == yesterday_str]
    if not yest:
        return
    total_new = sum(r.get("new_posts_count", 0) for r in yest)
    counts    = [r["official_count"] for r in yest
                 if r.get("official_count") is not None]
    start     = counts[0]  if counts else None
    end       = counts[-1] if counts else None
    official_growth = (end - start) if (start is not None and end is not None) else None

    data["daily"].append({
        "date":            yesterday_str,
        "total_new_posts": total_new,       # 当天用户发帖数
        "official_start":  start,
        "official_end":    end,
        "official_growth": official_growth, # 正=增长 负=倒退
    })
    print(f"[info] 归档 {yesterday_str}: 发帖={total_new}, 官方变化={official_growth}")

# ── 主函数 ────────────────────────────────────────────────────────────────────

def run():
    now           = cst_now()
    now_str       = now.strftime("%Y-%m-%d %H:%M")
    today_str     = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"\n====== {now_str} CST ======")

    data = load_data()

    # 确保 baseline 存在（兼容旧数据）
    if "baseline" not in data:
        data["baseline"] = {"count": BASELINE_COUNT, "time": BASELINE_TIME}

    # ── 确定 since_ts：上次记录的「最新帖子」时间戳 ──
    # 用 latest_post_ts 字段（最新），不是 earliest
    since_ts = 0
    if data["hourly"]:
        since_ts = data["hourly"][-1].get("latest_post_ts", 0)
    # 第一次运行：since_ts=0，会捞出很多历史帖子
    # 为了避免第一次数据虚高，如果 since_ts==0 就用「当前时间戳-1小时」
    if since_ts == 0:
        since_ts = int((now - timedelta(hours=1)).timestamp() * 1000)
        print(f"[info] 首次运行，since_ts 设为 1 小时前")

    session        = get_session()
    official_count = fetch_official_count(session)
    new_posts      = fetch_new_posts(session, since_ts)

    new_count  = len(new_posts)
    # 记录这批帖子里「最新那篇」的时间戳，下次用作截止点
    latest_ts  = max((p["publishTime"] for p in new_posts), default=since_ts)

    # 与基准的差值
    baseline_delta = (official_count - BASELINE_COUNT) if official_count is not None else None

    data["hourly"].append({
        "time":            now_str,
        "date":            today_str,
        "official_count":  official_count,
        "baseline_delta":  baseline_delta,   # 相对基准的变化量
        "new_posts_count": new_count,
        "latest_post_ts":  latest_ts,        # 本次最新帖子时间戳
    })

    # hourly 永久保留，不做裁剪
    settle_today(data, today_str)

    if now.hour == 0:
        settle_yesterday(data, yesterday_str)

    save_data(data)
    print(f"[info] 已保存 → {DATA_FILE}")
    print(f"====== 完成 ======\n")


if __name__ == "__main__":
    run()
