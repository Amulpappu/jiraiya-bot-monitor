$watchPath = "C:\Users\lohit\Downloads\files"
$branch = "main"
$debounceSeconds = 10
$lastPush = [datetime]::MinValue

# Files/folders to ignore
$ignorePatterns = @("\.git\\", "__pycache__", "\.pyc$", "venv\\", "\.log$", "processed_images\.json", "\.flag$")

function Should-Ignore($path) {
    foreach ($p in $ignorePatterns) {
        if ($path -match $p) { return $true }
    }
    return $false
}

function Git-AutoPush {
    $now = Get-Date
    if (($now - $lastPush).TotalSeconds -lt $debounceSeconds) { return }

    Set-Location $watchPath

    $status = git status --porcelain 2>&1
    if (-not $status) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] No changes to push." -ForegroundColor DarkGray
        return
    }

    # Check for secrets before pushing
    $diff = git diff --cached --diff-filter=d 2>&1
    if ($diff -match "DISCORD_TOKEN.*=.*[A-Za-z0-9]{20,}") {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] WARNING: Possible secret detected. Skipping push!" -ForegroundColor Red
        return
    }

    git add -A
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $changedFiles = (git diff --cached --name-only) -join ", "
    $msg = "Auto-update: $changedFiles [$timestamp]"

    git commit -m $msg 2>&1 | Out-Null
    $pushResult = git push origin $branch 2>&1

    if ($LASTEXITCODE -eq 0) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Pushed: $changedFiles" -ForegroundColor Green
    } else {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Push failed: $pushResult" -ForegroundColor Red
    }

    $script:lastPush = Get-Date
}

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Auto Git Push - Watching: $watchPath" -ForegroundColor Cyan
Write-Host "  Branch: $branch | Debounce: ${debounceSeconds}s" -ForegroundColor Cyan
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $watchPath
$watcher.IncludeSubdirectories = $true
$watcher.EnableRaisingEvents = $false
$watcher.NotifyFilter = [System.IO.NotifyFilters]::LastWrite -bor [System.IO.NotifyFilters]::FileName -bor [System.IO.NotifyFilters]::DirectoryName

# Simple polling approach (more reliable on Windows than events for git repos)
Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Watching for file changes..." -ForegroundColor Yellow

while ($true) {
    Start-Sleep -Seconds $debounceSeconds

    Set-Location $watchPath
    $status = git status --porcelain 2>&1

    if ($status) {
        $changedFiles = ($status | ForEach-Object { $_.Trim().Substring(3) }) -join ", "

        # Check if all changes are in ignored paths
        $hasRealChanges = $false
        foreach ($line in $status) {
            $file = $line.Trim().Substring(3)
            if (-not (Should-Ignore $file)) {
                $hasRealChanges = $true
                break
            }
        }

        if ($hasRealChanges) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Changes detected: $changedFiles" -ForegroundColor Yellow
            Git-AutoPush
        }
    }
}
