# 把 public/ 上传到自己的服务器（Windows 自带 OpenSSH 的 scp/ssh）
#
# 用法：
#   .\deploy\upload_to_vps.ps1 -HostName root@1.2.3.4
#   .\deploy\upload_to_vps.ps1 -HostName ubuntu@example.com -Dest /var/www/netrunnerdb-weekly -SkipBuild
#
# 第一次连需要输密码；想免密就先 ssh-keygen + ssh-copy-id。

param(
    [Parameter(Mandatory = $true)][string]$HostName,
    [string]$Dest = "/var/www/netrunnerdb-weekly",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $root
try {
    if (-not $SkipBuild) {
        $py = "C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
        if (-not (Test-Path $py)) { $py = "python" }
        Write-Host "==> 生成站点到 public/ ..."
        & $py nrdb_weekly.py --out public
        if ($LASTEXITCODE -ne 0) { throw "生成失败，退出码 $LASTEXITCODE" }
    }

    if (-not (Test-Path "public\index.html")) { throw "public\index.html 不存在，先不加 -SkipBuild 跑一次" }

    $zip = Join-Path $env:TEMP "netrunnerdb-weekly.zip"
    Write-Host "==> 打包 ..."
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path "public\*" -DestinationPath $zip -Force

    Write-Host "==> 上传到 ${HostName}:/tmp/ ..."
    & scp $zip "${HostName}:/tmp/netrunnerdb-weekly.zip"
    if ($LASTEXITCODE -ne 0) { throw "scp 失败" }

    Write-Host "==> 远端解包到 $Dest ..."
    $remote = "set -e; mkdir -p '$Dest'; rm -rf '$Dest'/*; " +
              "if command -v unzip >/dev/null; then unzip -oq /tmp/netrunnerdb-weekly.zip -d '$Dest'; " +
              "else python3 -m zipfile -e /tmp/netrunnerdb-weekly.zip '$Dest'; fi; " +
              "rm -f /tmp/netrunnerdb-weekly.zip; ls -1 '$Dest' | head -20"
    & ssh $HostName $remote
    if ($LASTEXITCODE -ne 0) { throw "远端解包失败" }

    Write-Host ""
    Write-Host "完成。若 nginx 已按 deploy/nginx.conf 配好，访问 http://$($HostName.Split('@')[-1])/ 即可。"
}
finally {
    Pop-Location
    if ($zip -and (Test-Path $zip)) { Remove-Item $zip -Force -ErrorAction SilentlyContinue }
}
