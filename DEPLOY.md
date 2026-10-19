# 把这份摘要发布成网站

站点是**纯静态**的（HTML + 图片 + JSON，没有后端），所以"服务器"可以极轻：
最省事是白嫖静态托管，最自主是买台最小云服务器。

仓库根目录就是站点根：`index.html` 是存档页，`2026-W43/` 这种文件夹是一期一期，
历史期数会一直累积。

---

## 选哪条路

| 方案 | 花钱 | 上手难度 | 国内访问 | 适合 |
| --- | --- | --- | --- | --- |
| **A. 只看本地/局域网** | 0 | ★ | 只能同 WiFi | 自己看、给朋友投屏 |
| **B. GitHub Pages** | 0 | ★★ | 不稳定（github.io 时通时断） | 零成本公网，推荐先试 |
| **C. Netlify / Cloudflare Pages** | 0 | ★★ | 一般（比 GitHub 稳些） | 不想碰命令行 |
| **D. 自己的云服务器 + 域名** | ¥50–100/月（活动价更低） | ★★★ | 快（国内机房） | 长期稳定、要自己域名 |
| **E. 对象存储静态托管（COS/OSS）** | 几毛钱/月 + 流量 | ★★ | 快 | 不想管服务器 |

> 这台电脑**不能**直接当公网服务器：出口是运营商 NAT（`202.104.136.69`），
> 没有固定公网 IP，80/443 入站被封。想"自己机器跑、外面访问"只能靠隧道
> （Cloudflare Tunnel / frp），还得常年开机——不如交给托管或 VPS。

---

## A. 本地 / 局域网（现在就能用）

```powershell
.\deploy\serve_local.bat
```

- 本机：<http://127.0.0.1:8080/>
- 同 WiFi 手机：`http://<这台机器的内网IP>:8080/`
- 首次可能被 Windows 防火墙拦，要在"允许应用通过防火墙"里放行 Python
  （这一步需要管理员权限）。

## B. GitHub Pages（已备好自动发布）

仓库里已经放了 `.github/workflows/pages.yml`：**每周一 09:00（北京时间）
由 GitHub 的机器抓取、提交新一期、Pages 自动重新发布**，你电脑关机也不影响。

### 1. 建仓库（只需一次）

打开 <https://github.com/new>：

- Repository name：`netrunnerdb-weekly`
- 选 **Public**（私有仓库用 Pages 需要付费）
- **不要**勾 "Add a README file"、不要加 .gitignore / license（空仓库）

### 2. 推送代码（只需一次）

```powershell
cd netrunnerdb-weekly
git push -u origin main
```

> 本机没装 git，用的是免安装版：
> `~\Documents\deepseek-harness\default-workspace\tools\mingit\cmd\git.exe`
> 需要的话把 `tools\mingit\cmd` 加进 PATH。
> 认证走 SSH：把 `~\.ssh\id_ed25519.pub` 贴到
> <https://github.com/settings/ssh/new>（Title 随便写，Key type 选 Authentication）。

### 3. 打开 Pages（只需一次）

仓库 **Settings → Pages**：

- Source：**Deploy from a branch**
- Branch：**main**，文件夹选 **/ (root)**
- Save

等 1～2 分钟，地址是：

```
https://xlmcmath.github.io/netrunnerdb-weekly/
```

### 4. 打开定时任务（只需一次）

**Actions** 标签页 → 左侧「每周牌组摘要」→ 右侧 **Run workflow** 手动跑一次。
（新仓库的定时任务默认可能处于停用状态，点一次会启用。）

之后每周一自动更新；也可以随时点 Run workflow 立刻跑。

> 说明：仓库根的 `.nojekyll` 让 Pages 跳过 Jekyll，直接原样发布。

## C. Netlify / Cloudflare Pages（不碰命令行）

- **Netlify**：<https://app.netlify.com/drop> 把 `netrunnerdb-weekly` 文件夹拖进去
  → 立刻得到 `https://xxx.netlify.app`。要自动更新就连 Git 仓库，构建命令填
  `pip install lxml && python nrdb_weekly.py --out .`，Publish directory 填 `.`。
- **Cloudflare Pages**：连 Git 仓库，Build command 同上，Output directory 填 `.`。
- 两者都能绑自己的域名，免费 HTTPS。

## D. 自己的云服务器（国内访问快，长期用推荐）

### 1. 买服务器

- **腾讯云轻量应用服务器**：2 核 2G / 3M，Ubuntu 22.04，常规 ¥60 左右/月，
  新用户活动常见 ¥99/年；**阿里云 ECS** 类似。
- 地域选离你近的（广州/深圳）。纯文本站点 1M 带宽就够。
- 控制台「防火墙 / 安全组」放行 **22（SSH）** 和 **80（HTTP）**。

### 2. 传代码上去

```powershell
scp -r . root@<服务器IP>:/opt/netrunnerdb-weekly
```

### 3. 一键部署

```bash
ssh root@<服务器IP>
cd /opt/netrunnerdb-weekly
sudo bash deploy/vps-setup.sh
```

脚本会装 nginx、建 venv、生成站点到 `/var/www/netrunnerdb-weekly`、
装 nginx 配置，并加 **每周一 09:00 的 cron**——以后完全由服务器自己抓取。

访问 `http://<服务器IP>/`。

### 4. 以后本地改完再传

```powershell
.\deploy\upload_to_vps.ps1 -HostName root@<服务器IP>
```

### 5. 绑域名 + HTTPS（可选）

```
# DNS 加 A 记录：digest.example.com → 服务器 IP
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d digest.example.com
```

⚠️ **大陆服务器绑域名必须 ICP 备案**（免费，但要等几天到几周）。
不想备案：只用 IP 访问，或服务器放香港/新加坡（免备案，延迟高些）。

## E. 对象存储静态托管（腾讯云 COS / 阿里云 OSS）

1. 建 Bucket，权限「公有读」。
2. 开「静态网站」，默认首页 `index.html`。
3. 把仓库里的 `index.html` + `2026-*/` 等目录上传（或用 coscli / ossutil 同步）。
4. 用默认域名访问；绑自定义域名同样需要备案。

---

## 站点文件说明

| 路径 | 内容 |
| --- | --- |
| `index.html` | 存档页（所有期数入口） |
| `<年-W周>/index.html` | 某一期正文 |
| `<年-W周>/decks.md` / `.json` | 同一期的 Markdown / 结构化数据 |
| `<年-W周>/decklists/*.txt` | 单副牌组纯文本（导入 jnet 用） |
| `<年-W周>/img/*.jpg` | 身份卡缩略图（离线可用） |
| `card_names_zh.xlsx` | 中文译名表（发布到公网也没关系，是公开数据） |

一期约 0.6 MB，20 期十几 MB，任何免费额度都够。

只重新生成站点（不抓新数据也行，会把当前周重写一遍）：

```powershell
python nrdb_weekly.py --out .
```

---

## 常见问题

**Q: 抓取会不会把站点搞崩？**
请求间隔 0.35 秒、失败重试 3 次，一周只跑一次。

**Q: GitHub Actions 抓取失败？**
GitHub 机器在美国，偶尔会被 netrunnerdb 拒绝。手动 Run workflow 重试一次即可，
或者改用方案 D 在 VPS 上跑 cron。

**Q: 页面里没有中文名？**
`card_names_zh.xlsx` 要跟着提交（已在仓库里）。

**Q: 想让别人也能传牌组？**
那需要后端（数据库 + 登录），是另一个项目了。
