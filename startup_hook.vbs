' NetrunnerDB weekly digest - silent weekly check (runs at logon, skips if this week is done).
' Installed into the user's Startup folder; delete this file to disable.
Dim sh, script, cmd
Set sh = CreateObject("WScript.Shell")
script = "C:\Users\Administrator\Documents\deepseek-harness\default-workspace\netrunnerdb-weekly\run_weekly.ps1"
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & script & """ -IfDue"
sh.Run cmd, 0, False
