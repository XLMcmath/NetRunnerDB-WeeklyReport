@echo off
rem 本地起一个静态服务器，预览/局域网分享用
rem 访问 http://127.0.0.1:8080/ ，同一 WiFi 下用 http://<这台机器的IP>:8080/
chcp 65001 >nul
cd /d "%~dp0.."
if not exist "index.html" (
    echo 还没有 index.html ，先生成一次：
    python nrdb_weekly.py
    pause
    exit /b 1
)
echo 服务中： http://127.0.0.1:8080/     ^(Ctrl+C 停止^)
python -m http.server 8080 --bind 0.0.0.0
