@echo off
echo [v4 Fixes] Backing up src to src\backup_v3...
if not exist src\backup_v3 mkdir src\backup_v3
robocopy src src\backup_v3 /E /XD backup_v3 /NFL /NDL /NJH /NJS /nc /ns /np >nul
echo [v4 Fixes] Backup complete.
echo [v4 Fixes] Running diagnostics...
E:\python311\python.exe diagnose.py
pause
