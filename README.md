# 刃恒 Tag 监控 / Where Did Lofter Tags Go

Lofter 平台长期存在 Tag 参与数异常波动的问题。新帖发布后，官方统计的参与数有时不增反降，疑似存在"吞 tag"现象。本项目通过每小时自动抓取 [#刃恒](https://www.lofter.com/tag/%E5%88%83%E6%81%92/new) tag 页面的官方参与数与用户实际发帖情况，记录和追踪这一异常的长期趋势。

> 数据可能存在误差，仅供大致趋势参考。存在计数限制，无法将当日之前的人为隐藏或修改tag的变动计入考量。

---

## 目标

- 每小时抓取一次官方参与数，记录其变化曲线
- 同时统计该小时内用户新发的帖子数量
- 每日结算时重新爬取昨日全天现存帖子数，对比tag当日增长数量

---

## 数据字段说明

### `data/records.json`

```
{
  "baseline": {
    "count": 65786,          // 基准参与数（监控开始时的官方数值）
    "time":  "2026-03-21 15:00"  // 基准时间（北京时间）
  },
  "hourly": [ ... ],         // 每小时爬取记录，永久保留
  "daily":  [ ... ],         // 每日归档记录
  "today":  { ... }          // 今日实时结算（每小时更新）
}
```

#### hourly 单条字段

| 字段 | 说明 |
|---|---|
| `time` | 爬取时间，北京时间，格式 `YYYY-MM-DD HH:MM` |
| `date` | 日期，格式 `YYYY-MM-DD` |
| `official_count` | 该时刻 Lofter 官方显示的 tag 参与数 |
| `baseline_delta` | 与基准参与数的差值（正=增长，负=倒退） |
| `new_posts_count` | 本小时内爬取到的新帖数量 |
| `latest_post_ts` | 本次最新帖子的发布时间戳（毫秒），用于下次翻页截止 |

#### daily 单条字段

| 字段 | 说明 |
|---|---|
| `date` | 日期 |
| `total_new_posts` | 当天现存帖子数（0 点重新爬取，已删帖不计） |
| `official_start` | 当天第一条 hourly 记录的官方参与数 |
| `official_end` | 当天最后一条 hourly 记录的官方参与数 |
| `official_growth` | 官方参与数当日净变化（`end - start`，负数表示倒退） |

---

## 使用说明

### 环境要求

- Python 3.11+
- 依赖：`pip install requests`

### 配置

在 GitHub repo 的 **Settings → Secrets → Actions** 中添加：

| Secret 名称 | 内容 |
|---|---|
| `LOFTER_AUTH` | Lofter 登录 Cookie 值（手机号登录对应 `LOFTER-PHONE-LOGIN-AUTH`） |

不同登录方式对应的 Cookie 字段名：
登录方式Cookie 字段名手机号登录LOFTER-PHONE-LOGIN-AUTHQQ / 微信 / 微博登录LOFTER_SESS邮箱登录NTES_SESSLofter ID 登录Authorization
Cookie 获取方法：

浏览器登录 Lofter，进入主页或任意页面
按 F12 打开开发者工具 → 点击 Application 标签 → 左侧展开 Cookies → 点击 Lofter 域名
在列表中找到你登录方式对应的字段名，复制右侧的 Value
将该 Value 粘贴到 GitHub Secret 的内容栏中

### 本地运行

```bash
LOFTER_AUTH=你的cookie值 python scraper.py
```

### 自动运行

项目使用 GitHub Actions 每小时整点自动执行（存在时间延迟），结果自动 commit 回 repo，GitHub Pages 页面实时更新。

### 查看面板

开启 GitHub Pages（Settings → Pages → Deploy from branch: main / root）后访问：

```
https://<你的用户名>.github.io/<repo名>/
```

---

## 文件结构

```
├── scraper.py            # 刃恒爬虫
├── index.html            # 刃恒监控面板
├── data/
│   └── records.json      # 刃恒数据（永久保留）
├── .github/
│   └── workflows/
│       └── scrape.yml    # GitHub Actions 定时任务
├── requirements.txt
└── README.md
```

---

## 免责声明

本项目仅用于记录和研究 Lofter 平台 tag 参与数的公开变化趋势，不涉及任何账号数据或私人信息。爬取频率为每小时一次，对平台服务影响极小。
