@echo off
rem RM Imoveis - instala, atualiza e abre o programa.
rem Na primeira vez instala tudo na pasta onde este arquivo esta. Depois, a cada uso:
rem procura a versao mais recente no GitHub (e atualiza se houver), coleta os imoveis
rem e abre a apresentacao em tela cheia. A pasta data\ (seus dados) nunca e apagada.
setlocal
chcp 65001 >nul
title RM Imóveis
set "RMBH_DIR=%~dp0"
set "RMBH_SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = [IO.File]::ReadAllText($env:RMBH_SELF); $i = $s.IndexOf('#' + '<POWERSHELL>'); Invoke-Expression $s.Substring($i)"
set "RC=%ERRORLEVEL%"
rem a newer copy of this launcher was downloaded: swap it in (one parsed block, so it is safe)
if exist "%~f0.new" (move /y "%~f0.new" "%~f0" >nul & exit /b %RC%)
if not "%RC%"=="0" pause
exit /b %RC%

#<POWERSHELL>
# ---------------------------------------------------------------------------
# Everything below is PowerShell, run by the line above. cmd never reaches it.
# ---------------------------------------------------------------------------
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with the progress bar
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Repo         = 'alexctrl/rm-scraping'
$LauncherName = 'RM-Imoveis.bat'           # release asset with the newest copy of this file
$PyVersion    = '3.12.10'                  # installed only if no Python 3.9+ is found
$TaskName     = 'RM Imoveis - coleta diaria'
$Dir          = $env:RMBH_DIR.TrimEnd('\')
$Self         = $env:RMBH_SELF
$Venv         = Join-Path $Dir '.venv'
$VPy          = Join-Path $Venv 'Scripts\python.exe'
$VerFile      = Join-Path $Dir 'rmbh_scraper\_version.py'
$Headers      = @{ 'User-Agent' = 'rm-scraping-launcher' }

function Step($t) { Write-Host ''; Write-Host "==> $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "    $t" -ForegroundColor Green }
function Info($t) { Write-Host "    $t" }
function Warn($t) { Write-Host "    $t" -ForegroundColor Yellow }

function Test-Py([string[]]$cmd) {
    # returns the interpreter path if $cmd runs Python 3.9+, else $null
    $ErrorActionPreference = 'Continue'
    $exe = $cmd[0]; $rest = @($cmd | Select-Object -Skip 1)
    try {
        $out = & $exe @rest -c "import sys; print(sys.executable if sys.version_info >= (3, 9) else '')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return ([string]($out | Select-Object -Last 1)).Trim() }
    } catch {}
    return $null
}

function Find-Python {
    $cands = @()
    if (Get-Command py -ErrorAction SilentlyContinue)     { $cands += ,@('py', '-3') }
    if (Get-Command python -ErrorAction SilentlyContinue) { $cands += ,@('python') }   # may be the Store stub; Test-Py rejects it
    foreach ($root in @("$env:LOCALAPPDATA\Programs\Python", $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($root -and (Test-Path $root)) {
            Get-ChildItem $root -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending |
                ForEach-Object { $p = Join-Path $_.FullName 'python.exe'; if (Test-Path $p) { $cands += ,@($p) } }
        }
    }
    foreach ($c in $cands) { $r = Test-Py $c; if ($r) { return $r } }
    return $null
}

function Install-Python {
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
    $url  = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-$arch.exe"
    $exe  = Join-Path $env:TEMP "python-$PyVersion-$arch.exe"
    Info "baixando $url"
    Invoke-WebRequest $url -OutFile $exe -UseBasicParsing
    Info 'instalando o Python só para o seu usuário (pode levar alguns minutos)...'
    $p = Start-Process $exe -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1',
        'InstallLauncherAllUsers=0', 'Include_test=0', 'Include_doc=0')
    Remove-Item $exe -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0) { throw "a instalação do Python falhou (código $($p.ExitCode))" }
}

function Get-Latest {
    # newest release: @{ Tag; ZipUrl; BatUrl }, or $null when GitHub can't be reached
    try {
        $rel = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -UseBasicParsing -Headers $Headers -TimeoutSec 20
    } catch { return $null }
    $zip = $rel.assets | Where-Object { $_.name -eq 'rm-scraping.zip' } | Select-Object -First 1
    if (-not $zip) { $zip = $rel.assets | Where-Object { $_.name -like 'rm-scraping-v*.zip' } | Select-Object -First 1 }
    $bat = $rel.assets | Where-Object { $_.name -eq $LauncherName } | Select-Object -First 1
    return @{
        Tag    = $rel.tag_name
        ZipUrl = if ($zip) { $zip.browser_download_url } else { "https://github.com/$Repo/releases/latest/download/rm-scraping.zip" }
        BatUrl = if ($bat) { $bat.browser_download_url } else { $null }
    }
}

function Install-Files($zipUrl) {
    $tmp = Join-Path $env:TEMP ('rm-scraping-' + [guid]::NewGuid())
    New-Item -ItemType Directory $tmp | Out-Null
    try {
        $zip = Join-Path $tmp 'app.zip'
        Invoke-WebRequest $zipUrl -OutFile $zip -UseBasicParsing
        $src = Join-Path $tmp 'app'
        Expand-Archive $zip -DestinationPath $src -Force
        if (-not (Test-Path (Join-Path $src 'rmbh_scraper\__init__.py'))) { throw 'o pacote baixado não contém o programa' }
        # replace the program folders (drops files removed upstream); data\ and .venv\ are left alone
        foreach ($d in 'rmbh_scraper', 'viewer', 'tools', 'docs') {
            $t = Join-Path $Dir $d
            if (Test-Path $t) { Remove-Item $t -Recurse -Force }
        }
        Get-ChildItem $src -Force | Where-Object { $_.Name -notlike '*.bat' } |   # never overwrite the running launcher
            ForEach-Object { Copy-Item $_.FullName -Destination $Dir -Recurse -Force }
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force (Join-Path $Dir 'data') | Out-Null
}

function Update-Launcher($batUrl) {
    # stage a newer copy of this .bat; the batch code swaps it in after we exit
    if (-not $batUrl) { return }
    try {
        $new = Join-Path $env:TEMP ('rm-imoveis-' + [guid]::NewGuid() + '.bat')
        Invoke-WebRequest $batUrl -OutFile $new -UseBasicParsing
        $a = [IO.File]::ReadAllBytes($new); $b = [IO.File]::ReadAllBytes($Self)
        if ([Convert]::ToBase64String($a) -ne [Convert]::ToBase64String($b)) {
            Move-Item $new "$Self.new" -Force
            Info 'este arquivo também foi atualizado (vale a partir da próxima abertura)'
        } else { Remove-Item $new }
    } catch { Warn "não foi possível atualizar este arquivo: $($_.Exception.Message)" }
}

function Install-Deps {
    if ((Test-Path $VPy) -and -not (Test-Py @($VPy))) {
        Info 'ambiente antigo inválido; recriando'
        Remove-Item $Venv -Recurse -Force
    }
    if (-not (Test-Path $VPy)) {
        $py = Find-Python
        if (-not $py) {
            Info "Python 3.9 ou mais novo não encontrado; instalando o Python $PyVersion"
            Install-Python
            $py = Find-Python
            if (-not $py) { throw 'o Python foi instalado mas não foi encontrado; feche esta janela e abra de novo' }
        }
        Ok "Python: $py"
        & $py -m venv $Venv
        if ($LASTEXITCODE -ne 0) { throw 'não foi possível criar o ambiente virtual (.venv)' }
    }
    & $VPy -m pip install --disable-pip-version-check --quiet --upgrade -r (Join-Path $Dir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'falha ao instalar as dependências (verifique a conexão com a internet)' }
}

function Register-Crawl($trigger) {
    # cmd /c ""python.exe" args >> log" - the outer quotes are stripped by cmd
    $arg = '/c ""' + $VPy + '" -m rmbh_scraper crawl --no-view >> "data\coleta.log" 2>&1"'
    $action   = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $arg -WorkingDirectory $Dir
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                    -ExecutionTimeLimit (New-TimeSpan -Hours 3)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description "Coleta diária dos imóveis da RM Imóveis ($Dir)" -Force | Out-Null
}

function Set-Schedule([bool]$ask) {
    try {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) {
            Register-Crawl $task.Triggers   # keep the chosen time, refresh the paths
            return
        }
        if (-not $ask) { return }
        Step 'Coleta diária automática (opcional)'
        $ans = Read-Host '    Deseja que a coleta rode também todo dia sozinha, mesmo sem abrir o programa? (S/N)'
        if ($ans -match '^\s*[sSyY]') {
            $h = Read-Host '    Horário (HH:MM) [08:00]'
            if (-not $h) { $h = '08:00' }
            $at = [datetime]::ParseExact($h.Trim(), [string[]]@('H:mm', 'HH:mm', 'H'),
                                         [Globalization.CultureInfo]::InvariantCulture, 'None')
            Register-Crawl (New-ScheduledTaskTrigger -Daily -At $at)
            Ok ("agendado todo dia às {0:HH:mm} (log em data\coleta.log)" -f $at)
        } else {
            Info 'sem agendamento'
        }
    } catch {
        Warn "não foi possível configurar o agendamento: $($_.Exception.Message)"
    }
}

function Remove-OldLaunchers {
    # shortcuts made by the old installer; this file replaces them
    foreach ($n in 'Coletar imoveis.bat', 'Abrir apresentacao.bat', 'instalar.bat') {
        $f = Join-Path $Dir $n
        if ((Test-Path $f) -and ($f -ne $Self) -and ((Get-Content $f -Raw) -match 'rmbh_scraper|RM Im')) {
            Remove-Item $f -Force
        }
    }
}

try {
    if (-not $Dir -or -not (Test-Path $Dir)) { throw 'pasta inválida' }
    Set-Location $Dir
    Write-Host ''
    Write-Host '  RM Imóveis' -ForegroundColor White
    Write-Host "  Pasta: $Dir"

    # ------------------------------------------------------------ 1. install or update
    $installed = (Test-Path (Join-Path $Dir 'rmbh_scraper\__init__.py')) -and (Test-Path $VPy)
    $current   = if (Test-Path $VerFile) { 'v' + ((Get-Content $VerFile -Raw) -replace '[^0-9.]', '') } else { $null }

    Step 'Procurando atualizações no GitHub'
    $latest = Get-Latest
    if (-not $installed) {
        if (-not $latest) { throw 'sem acesso ao GitHub; verifique a conexão com a internet e tente de novo' }
        Info "programa não instalado nesta pasta; instalando a versão $($latest.Tag)"
        Step 'Baixando os arquivos'
        Install-Files $latest.ZipUrl
        Ok 'arquivos instalados'
        Step 'Preparando o Python e as dependências'
        Install-Deps
        Ok 'dependências instaladas'
        Update-Launcher $latest.BatUrl
        Set-Schedule $true
    } elseif (-not $latest) {
        Warn "sem acesso ao GitHub; usando a versão instalada ($current)"
    } elseif ($latest.Tag -ne $current) {
        Info "nova versão disponível: $current -> $($latest.Tag)"
        Step 'Atualizando'
        Install-Files $latest.ZipUrl
        Install-Deps
        Update-Launcher $latest.BatUrl
        Set-Schedule $false
        Ok "atualizado para $($latest.Tag)"
    } else {
        Ok "já está na versão mais recente ($current)"
        if (-not (Test-Py @($VPy))) { Install-Deps }   # e.g. Python was removed since the last run
    }
    Remove-OldLaunchers

    # ------------------------------------------------------------ 2. crawl
    Step 'Coletando os imóveis no site (pode levar alguns minutos)'
    & $VPy -m rmbh_scraper crawl --no-view
    if ($LASTEXITCODE -ne 0) {
        if (Test-Path (Join-Path $Dir 'data\listings.json')) {
            Warn 'a coleta falhou; a apresentação vai mostrar os dados da última coleta'
        } else {
            throw 'a coleta falhou e ainda não há dados para mostrar'
        }
    }

    # ------------------------------------------------------------ 3. slideshow
    Step 'Abrindo a apresentação em tela cheia'
    & $VPy -m rmbh_scraper view --fullscreen
    exit 0
} catch {
    Write-Host ''
    Write-Host "  ERRO: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
