$ErrorActionPreference = 'Stop'
$pythonw = "C:\Users\pavlo\AppData\Local\Programs\Python\Python312\pythonw.exe"
$scriptPath = Join-Path $PSScriptRoot "run.py"
$runCommand = "`"$pythonw`" `"$scriptPath`""
Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "WinRemoteTaskManager" -Value $runCommand -Type String
Write-Output "Autostart registered: $runCommand"
