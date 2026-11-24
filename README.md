# 蚝历 · 节假日日历

2027 年节假日日历站点。中国数据依据国务院通知，农历节日与 24 节气由天文历法计算；
海外 62 国由开源假日库 [holidays](https://github.com/vacanza/holidays)（vacanza/holidays）
按年计算，名称经 `holiday_i18n.py` 译为中文。提供 `.ics` 下载与 `webcal://` 订阅两种用法。

## 数据与构建

| 数据块 | 来源 | 文件 |
|---|---|---|
| 中国内地 | 国办发明电〔2026〕10 号 + cnlunar 天文计算 | `china-2027.ics`（81 条） |
| 中国香港/澳门/台湾 | 当地公布假期整理，台湾剔政治纪念日 | `hk/mo/tw-2027.ics` |
| 海外 62 国 | holidays 库逐国计算，含补假/推算标注 | `xx-2027.ics`（62 个文件） |
| 地区合集 | 各国按语义合并 | `east-asia` 等 9 个合集 |
| 全球大全 | 446 条，同一天同一节日合并为一条 | `global-2027.ics` + 订阅别名 |

- **合并规则**（`holiday_canon.py`）：按「日期 + 节日语义」合并，不按名称字符串。
  元旦/元旦假期/新年 → 元旦；劳动节/国际劳动节/五一节/劳动者节 → 劳动节；
  圣诞节/节礼日/圣诞节次日 → 圣诞族。不同节日即使撞在同一天也不合并
  （如 12/2 老挝国庆日与阿联酋国庆日会并成「国庆日（2 国）」，因为确实是同类）；
  中国内地在大全里只放法定假期区间与调休上班，节日名与节气在中国单独文件里；
- 连续多日的连休（缅甸新年、俄罗斯元旦假期）自动压成区间，不逐日刷屏；
- 未收录译名以自身为键、不合并（宁可漏并，不要错并）；0 条英文残留；
- 每年更新：`YEAR` 改年份 → `SITE=https://域名 .venv/bin/python build.py`；
- 新增国家：在 `holiday_i18n.py` 的 `COUNTRIES` 加一行，跑覆盖率检查补译名即可。

覆盖检查命令（改动译名后必跑）：

```bash
../.venv/bin/python - <<'EOF'
import holidays, collections, sys
sys.path.insert(0,'.')
import holiday_i18n as i18n
names=collections.Counter()
for code,_,_,_,_ in i18n.COUNTRIES:
    for d,n in holidays.country_holidays(code, years=2027, language="en_US").items():
        names[n]+=1
un=[n for n in names if i18n.zh_name(n, [c for c,_,_,_,_ in i18n.COUNTRIES if c and (c,n) in [(x[0],n) for x in i18n.COUNTRIES]][:1] or "") == n]
print("未译:", len(un), un[:20])
EOF
```

## 目录结构

```
holiday-calendar-deploy/          ← 站点根目录，Nginx root 指到这里
├── index.html                    ← 构建产物，不要手改
├── template.html                 ← 页面模板，改这里
├── build.py                      ← 构建脚本（生成 ics + 页面 + sitemap）
├── stats.json                    ← 各文件条数，构建时注入页面
├── oyster-logo.png               ← 站点 logo（512px）
├── robots.txt / sitemap.xml      ← 构建产物
├── ics/
│   ├── china-2027.ics            ← 中国（官方假日 + 农历 + 节气 + 纪念日）
│   ├── china.ics                 ← 订阅别名，URL 不带年份，每年覆盖内容
│   ├── global-2027.ics           ← 全球合集
│   ├── global.ics                ← 订阅别名
│   ├── tw-2027.ics / hk / mo …   ← 各国文件
└── deploy/
    └── nginx.conf                ← 站点配置
```

## 构建

```bash
cd ~/Documents/蚝历项目
.venv/bin/python holiday-calendar-deploy/build.py            # 本地预览用默认域名
SITE=https://holiday.你的域名.com .venv/bin/python holiday-calendar-deploy/build.py   # 生产构建
```

`SITE` 决定 canonical、OG、sitemap 里的绝对地址。**上线前必须传**，否则 SEO 标签会指向 example.com。

依赖：`cnlunar`（农历与节气），已装在 `~/Documents/蚝历项目/.venv`。

## 部署到腾讯云

```bash
# 1. 服务器准备目录
ssh root@<IP> 'mkdir -p /var/www/haoli'

# 2. 上传（不要带 .venv、README 以外的东西）
rsync -avz --delete \
  --exclude 'build.py' --exclude 'template.html' --exclude 'stats.json' --exclude 'deploy' \
  ~/Documents/蚝历项目/holiday-calendar-deploy/ root@<IP>:/var/www/haoli/

# 3. Nginx
scp deploy/nginx.conf root@<IP>:/etc/nginx/conf.d/haoli.conf
ssh root@<IP> 'nginx -t && nginx -s reload'
```

`nginx -t` 必须通过再 reload。配置里 `server_name` 和 `root` 按实际改。

HTTPS 用 certbot：

```bash
ssh root@<IP> 'certbot --nginx -d holiday.你的域名.com'
```

> 域名解析到国内服务器（腾讯云）需要在工信部备案，否则 80/443 会被拦截。备案下来之前可以先用 IP + 非标端口做内部验证。

## 每年更新（以 2028 为例）

1. 改 `build.py` 顶部 `YEAR = 2028`；
2. 换 `CN_OFFICIAL` / `CN_WORKDAYS` 为国务院新通知的日期（农历、节气会按 YEAR 自动重算，不用动）；
3. 更新各国日期（`KR`、`TW` 是手写表，其余国家沿用上年文件后手工核对）；
4. `SITE=... build.py`；
5. `rsync` 上传；
6. **不要改订阅别名 `china.ics` / `global.ics` 的文件名**——老订阅靠它自动更新。

## 几个刻意的设计（改之前先读）

- **订阅 URL 不带年份**：`/ics/china.ics` 永远指向当年内容。带年份会让老订阅在跨年后变成死链。
- **UID 全局唯一**：每个文件有独立前缀（cn-、us-、gl-…），所以「全球大全」和各国家包可以叠加导入而不冲突。旧版本这里 477 个 UID 重复，叠加会出现覆盖。
- **CRLF 行尾**：RFC 5545 要求，Outlook 对 LF 容忍度差。
- **不写「入梅 / 出梅 / 三伏」**：这些是气象部门当年才发布的，提前写死等于编造。
- **台湾/香港/澳门写作「中国台湾 / 中国香港 / 中国澳门」**，且不收录政治性纪念日。
- **只给法定假日和春节、端午、中秋加提醒**（VALARM），其余不提醒，避免打扰。

## 自检

```bash
cd ~/Documents/蚝历项目/holiday-calendar-deploy
.venv/bin/python - <<'PY'
import glob, re, collections
c = collections.Counter()
for p in glob.glob('ics/*-2027.ics'):
    c.update(re.findall(r'UID:(\S+)', open(p, encoding='utf-8').read()))
dup = {k: v for k, v in c.items() if v > 1}
print('UID 总数', len(c), '重复', len(dup), '（应为 0）')
for p in glob.glob('ics/*-2027.ics'):
    raw = open(p, 'rb').read()
    assert raw.count(b'\r\n') == raw.count(b'\n'), p + ' 行尾不是 CRLF'
print('全部 CRLF 通过')
PY
```

## 发布流程（2026-11-07 定稿）

1. 本地构建：`YEARS=2026,2027 SITE=... [ICP=备案号] ../.venv/bin/python build.py`
2. 同步发布仓库：只把站点产物（`2026/ 2027/ robots.txt sitemap.xml oyster-logo.png`）
   复制进独立仓库 `bohub8888/haoli-site`（公开，仅静态文件）并推送。
   ⚠️ 不要把 `蚝历项目/` 整个目录推公开仓库——git 根在项目顶层，会把 `文档/设计/素材` 全带上去。
   原 `bohub8888/haoli-calendar` 已转私有；如需彻底删除须在网页端操作（需 delete_repo 权限）。
3. 服务器（腾讯云 lhins-3f81drk4，49.233.147.15，OpenCloudOS）：
   `curl -sfL https://codeload.github.com/bohub8888/haoli-site/tar.gz/refs/heads/main -o /tmp/site.tgz`
   → 解包 → `cp -a` 到 `/var/www/haoli/`（部署前先 `tar czf /root/haoli-backup-日期.tgz haoli`）。
4. nginx（配置在 `/etc/nginx/nginx.conf`，备份 `/root/nginx.conf.bak`）：
   - 首页**按服务器当前年份自动跳转**，不用每年手改：
     `map $time_iso8601 $haoli_year { default /2026/; "~^2027-" /2027/; "~^2028-" /2028/; }`
     `location = / { add_header Cache-Control "no-store"; return 302 $haoli_year; }`
     依赖服务器时区为 +0800（已确认）。**新增年份时在这行 map 里补一条**，
     否则该年 1/1 会落到 default（仍是 2026）。当前已列 2026/2027/2028。
   - `location ~* \.ics$ { default_type text/calendar; ... }`——缺这个头手机无法导入日历。
5. 线上验证：`/` 302、两页 200、154 个 ics 全 200 且 `Content-Type: text/calendar`、md5 与本地一致。
6. 待办：拿到 ICP 备案域名后 `SITE=https://域名 ICP=备案号` 重建重发，配 HTTPS，30 天内公安备案。

### 订阅（2026-11-07 加回）

- 每张卡片两颗按钮：导入（一次性快照）+ 订阅（`webcal://`，iPhone/iPad/Mac/Outlook 直接生效；安卓需日历内「通过网址添加」）。
- **UID 已改为内容寻址**（`前缀-年月日-摘要哈希@haoli`），不再用排序序号——序号会因增删一条整体位移，订阅者会看到事件重复/消失。改了这条之后订阅才安全。
- 同一天同名事件撞 UID 时加 `-2` 后缀；全部构建确定性（重复构建 md5 一致，已验证）。
- 构建产物传输：`git push` 偶发被代理拦（CONNECT 502），兜底走 GitHub Contents API 逐文件 PUT。

### HTTPS（2026-11-07 加，纯 IP 证书）

- iPhone 订阅日历**强制要求 TLS**：iOS 对 `http://` 订阅源在本地直接拒绝（请求根本不会到服务器，nginx 日志无记录）。
  解决：Let's Encrypt 2026-01 起 GA 的 **IP 地址证书**（必须 shortlived 档，有效期 160 小时≈6 天）。
- 签发：服务器 `/opt/certbot`（venv，certbot 5.9），
  `certbot certonly --preferred-profile shortlived --webroot -w /var/www/haoli --ip-address 49.233.147.15 --cert-name haoli-ip`
  → `/etc/letsencrypt/live/haoli-ip/`。证书 SAN = `IP Address:49.233.147.15`。
- 自动续期：`certbot-haoli.service/.timer`（每天 03:17/15:17 跑 renew + deploy-hook reload nginx）。
  **6 天期证书，续期链路断超过 6 天 https 就失效**——dry-run 已验证通过。
- nginx：80 端口整段 `return 301 https://$host$request_uri;`（webcal→http 的老客户端靠 301 兜底）；
  443 server 块复制原配置 + ssl 证书行；防火墙加 TCP 443。
- ics 不进 gzip_types（部分 iOS 版本解析不了压缩过的日历）。
- SITE 已改 `https://49.233.147.15`（canonical/webcal 链接随之）。换域名时：签发新证书 → 改 SITE 重建重发。
