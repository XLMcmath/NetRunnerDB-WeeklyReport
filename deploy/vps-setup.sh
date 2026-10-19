#!/usr/bin/env bash
# NetrunnerDB 每周牌组摘要 · Ubuntu/Debian 一键部署
#
# 用法（在服务器上，repo 目录里执行）：
#   sudo bash deploy/vps-setup.sh
#
# 它会：
#   1. 装 nginx / python3-venv / unzip
#   2. 建 venv 并装 lxml
#   3. 生成第一版站点到 /var/www/netrunnerdb-weekly
#   4. 装 nginx 站点配置并 reload
#   5. 加一条 cron：每周一 09:00 重新抓取
#
# 目标系统：Ubuntu 20.04+ / Debian 11+

set -euo pipefail

SITE_ROOT="/var/www/netrunnerdb-weekly"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_DIR/.venv"

if [[ $EUID -ne 0 ]]; then
  echo "请用 sudo 运行：sudo bash deploy/vps-setup.sh" >&2
  exit 1
fi

echo "==> 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y nginx python3 python3-venv python3-pip unzip

echo "==> 准备 Python 环境（$VENV）"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet lxml

echo "==> 生成第一版站点 → $SITE_ROOT"
mkdir -p "$SITE_ROOT"
"$VENV/bin/python" "$REPO_DIR/nrdb_weekly.py" --out "$SITE_ROOT"

echo "==> 安装 nginx 配置"
install -m 644 "$REPO_DIR/deploy/nginx.conf" /etc/nginx/sites-available/netrunnerdb-weekly
ln -sf /etc/nginx/sites-available/netrunnerdb-weekly /etc/nginx/sites-enabled/netrunnerdb-weekly
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl reload nginx

echo "==> 添加每周一 09:00 的 cron"
CRON_LINE="0 9 * * 1 cd $REPO_DIR && $VENV/bin/python nrdb_weekly.py --out $SITE_ROOT >/var/log/netrunnerdb-weekly.log 2>&1"
( crontab -l 2>/dev/null | grep -v "nrdb_weekly.py --out" ; echo "$CRON_LINE" ) | crontab -

IP="$(curl -s --max-time 5 https://api.ipify.org || echo '你的服务器IP')"
cat <<EOF

部署完成 ✅

  站点目录 : $SITE_ROOT
  代码目录 : $REPO_DIR
  自动更新 : 每周一 09:00（crontab -l 可查看）
  日志     : /var/log/netrunnerdb-weekly.log

  访问：http://$IP/

注意：
  - 云厂商「安全组 / 防火墙」要放行 80 端口，否则外网打不开
  - 想绑域名：把 nginx.conf 里 server_name 改成你的域名，然后
    sudo certbot --nginx -d 你的域名   （免费 HTTPS，需先 apt install certbot python3-certbot-nginx）
  - 中国大陆服务器绑域名需要 ICP 备案；不绑域名、直接 IP 访问则不需要
EOF
