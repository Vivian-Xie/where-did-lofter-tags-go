"""
Lofter Tag Monitor - scraper.py
每小时运行一次，爬取 tag 页的：
  1. 官方"参与"总数（HTML解析）
  2. 最新帖子列表（DWR API），记录每篇的 permalink + publishTime
每天北京时间 0 点做日结算
"""

import json
import os
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────────────
TAG_URL     = "https://www.lofter.com/tag/%E5%88%83%E6%81%92/new"
TAG_NAME    = "%E5%88%83%E6%81%92"          # URL编码后的tag名
DWR_URL     = "http://www.lofter.com/dwr/call/plaincall/TagBean.search.dwr"
DATA_FILE   = "data/records.json"
LOGIN_KEY   = "LOFTER-PHONE-LOGIN-AUTH"     # cookie名，手机号登录
LOGIN_AUTH  = os.environ.get("LOFTER_AUTH", "")  # 从GitHub Secrets读取
CST         = timezone(timedelta(hours=8))   # 北京时间

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Host": "www.lofter.com",
    "Referer": TAG_URL,
}

# ── 工具函数 ──────────────────────────────────────────────────────────────────

def cst_now() -> datetime:
    return datetime.now(CST)

def load_data() -> dict:
    p = Path(DATA_FILE)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"hourly": [], "daily": []}

def save_data(data: dict):
    Path("data").mkdir(exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── 第一步：获取登录 session ──────────────────────────────────────────────────

def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)

    # 先请求登录页拿到基础 cookies（NTESwebSI 等）
    try:
        session.get("http://www.lofter.com/login", params={"urschecked": "true"}, timeout=15)
    except Exception as e:
        print(f"[warn] 登录页请求失败: {e}")

    # 注入用户的 auth cookie
    if LOGIN_AUTH:
        session.cookies.set(LOGIN_KEY, LOGIN_AUTH, domain="www.lofter.com")
    else:
        print("[warn] LOFTER_AUTH 环境变量为空，可能无法获取数据")

    # 请求主页让 session 完全初始化
    try:
        session.get("http://www.lofter.com/", timeout=15)
    except Exception as e:
        print(f"[warn] 主页请求失败: {e}")

    return session

# ── 第二步：爬取官方"参与"总数 ───────────────────────────────────────────────

def fetch_official_count(session: requests.Session) -> int | None:
    """
    解析 tag 页 HTML 里的：
    <div class="tag-count f-fl"> 4457.7万浏览 &nbsp;&nbsp;65783参与 </div>
    返回"参与"数字（整数）
    """
    try:
        resp = session.get(TAG_URL, timeout=15)
        html = resp.text

        # 匹配 "数字参与" 或 "数字万参与"
        match = re.search(r'([\d.]+)(万?)参与', html)
        if not match:
            print("[warn] 未找到参与数，HTML片段：", html[html.find("tag-count"):html.find("tag-count")+200])
            return None

        num_str = match.group(1)
        wan     = match.group(2)
        num     = float(num_str)
        if wan == "万":
            num = int(num * 10000)
        else:
            num = int(num)

        print(f"[info] 官方参与数: {num}")
        return num

    except Exception as e:
        print(f"[error] fetch_official_count: {e}")
        return None

# ── 第三步：爬取最新帖子列表（DWR API）───────────────────────────────────────

def fetch_new_posts(session: requests.Session, since_timestamp: int = 0) -> list[dict]:
    """
    通过 PC 端 DWR API 获取 tag 最新帖子。
    since_timestamp: 上次爬取的最早时间戳（毫秒），只返回更新的帖子。
    返回 list of {"permalink": str, "publishTime": int(ms), "publishTimeStr": str}
    """
    get_num  = 100
    got_num  = 0
    all_posts = []
    seen_permalinks = set()

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
            print(f"[error] DWR 请求失败: {e}")
            break

        # 按 activityTags 分割，每段对应一篇帖子
        chunks = content.split("activityTags")[1:]
        if not chunks:
            print("[info] 无新帖子或已到最后一页")
            break

        stop = False
        for chunk in chunks:
            # 提取 permalink（唯一ID）
            permalink_match = re.search(r's\d+\.permalink="(.*?)"', chunk)
            if not permalink_match:
                continue
            permalink = permalink_match.group(1)
            if permalink in seen_permalinks:
                continue
            seen_permalinks.add(permalink)

            # 提取发布时间戳（毫秒）
            ts_match = re.search(r's\d+\.publishTime=(\d+);', chunk)
            if not ts_match:
                continue
            pub_ts = int(ts_match.group(1))

            # 如果已经早于上次记录的最早时间，停止翻页
            if since_timestamp and pub_ts <= since_timestamp:
                stop = True
                break

            pub_time_str = datetime.fromtimestamp(pub_ts / 1000, tz=CST).strftime("%Y-%m-%d %H:%M:%S")
            all_posts.append({
                "permalink":      permalink,
                "publishTime":    pub_ts,
                "publishTimeStr": pub_time_str,
            })

        if stop:
            print(f"[info] 已追溯到上次记录时间，停止翻页")
            break

        got_num += get_num
        if len(chunks) < get_num:
            print(f"[info] 帖子不足一页，获取结束")
            break

        # 更新翻页参数：用最后一篇的 publishTime
        last_ts_match = re.search(r's\d+\.publishTime=(\d+);', chunks[-1])
        if not last_ts_match:
            break
        last_ts = last_ts_match.group(1)
        data["c0-param6"] = f"number:{get_num}"
        data["c0-param7"] = f"number:{got_num}"
        data["c0-param8"] = f"number:{last_ts}"
        time.sleep(0.5)

    print(f"[info] 本次获取新帖: {len(all_posts)} 篇")
    return all_posts

# ── 第四步：计算增量并写入数据 ───────────────────────────────────────────────

def run():
    now       = cst_now()
    now_str   = now.strftime("%Y-%m-%d %H:%M")
    today_str = now.strftime("%Y-%m-%d")

    print(f"\n====== {now_str} CST 开始爬取 ======")

    data = load_data()

    # 找上一条 hourly 记录，获取 since_timestamp
    since_ts = 0
    if data["hourly"]:
        last = data["hourly"][-1]
        since_ts = last.get("earliest_post_ts", 0)

    session        = get_session()
    official_count = fetch_official_count(session)
    new_posts      = fetch_new_posts(session, since_ts)

    # 计算这次新增帖子数
    new_count = len(new_posts)

    # 记录最早时间戳（用于下次翻页截止）
    earliest_ts = min((p["publishTime"] for p in new_posts), default=since_ts)

    hourly_record = {
        "time":             now_str,
        "date":             today_str,
        "official_count":   official_count,
        "new_posts_count":  new_count,
        "earliest_post_ts": earliest_ts,
    }
    data["hourly"].append(hourly_record)

    # 只保留最近 30 天的 hourly 数据，防止文件过大
    cutoff = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    data["hourly"] = [r for r in data["hourly"] if r.get("date", "") >= cutoff]

    # ── 日结算：如果是 0 点那次爬取 ─────────────────────────────────
    if now.hour == 0:
        yesterday     = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        today_hourly  = [r for r in data["hourly"] if r.get("date") == yesterday]

        if today_hourly:
            total_new   = sum(r["new_posts_count"] for r in today_hourly)
            counts      = [r["official_count"] for r in today_hourly if r["official_count"] is not None]
            start_count = counts[0]  if counts else None
            end_count   = counts[-1] if counts else None
            official_growth = (end_count - start_count) if (start_count and end_count) else None

            daily_record = {
                "date":             yesterday,
                "total_new_posts":  total_new,
                "official_start":   start_count,
                "official_end":     end_count,
                "official_growth":  official_growth,
                "discrepancy":      (official_growth - total_new) if (official_growth is not None) else None,
            }
            data["daily"].append(daily_record)
            print(f"[info] 日结算 {yesterday}: 新帖={total_new}, 官方增长={official_growth}, 差异={daily_record['discrepancy']}")

    save_data(data)
    print(f"[info] 数据已保存到 {DATA_FILE}")
    print(f"====== 爬取完成 ======\n")

if __name__ == "__main__":
    run()
