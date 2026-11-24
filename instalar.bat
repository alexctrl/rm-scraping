@echo off
rem Instalador / atualizador do RM Imoveis.
rem Instala o programa na pasta onde este arquivo esta. Rode de novo para atualizar.
rem O que faz: baixa a versao mais recente do GitHub, instala o Python se precisar,
rem cria o ambiente (.venv) com as dependencias e cria os atalhos de uso.
rem A pasta data\ (seus dados) nunca e apagada.
setlocal
chcp 65001 >nul
title Instalador - RM Imóveis
set "RMBH_DIR=%~dp0"
set "RMBH_SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = [IO.File]::ReadAllText($env:RMBH_SELF); $i = $s.IndexOf('#' + '<POWERSHELL>'); Invoke-Expression $s.Substring($i)"
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%

#<POWERSHELL>
# ---------------------------------------------------------------------------
# Everything below is PowerShell, run by the line above. cmd never reaches it.
# ---------------------------------------------------------------------------
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with the progress bar
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Repo      = 'alexctrl/rm-scraping'
$PyVersion = '3.12.10'                     # installed only if no Python 3.9+ is found
$TaskName  = 'RM Imoveis - coleta diaria'
$Dir       = $env:RMBH_DIR.TrimEnd('\')
$Venv      = Join-Path $Dir '.venv'
$VPy       = Join-Path $Venv 'Scripts\python.exe'
$Utf8      = New-Object Text.UTF8Encoding $false

function Step($t) { Write-Host ''; Write-Host "==> $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "    $t" -ForegroundColor Green }
function Info($t) { Write-Host "    $t" }

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

function Write-Bat($name, $body) {
    [IO.File]::WriteAllText((Join-Path $Dir $name), (($body -join "`r`n") + "`r`n"), $Utf8)
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

try {
    if (-not $Dir -or -not (Test-Path $Dir)) { throw 'pasta de instalação inválida' }
    Set-Location $Dir
    Write-Host ''
    Write-Host '  RM Imóveis - instalador' -ForegroundColor White
    Write-Host "  Pasta: $Dir"

    # ------------------------------------------------------------ 1. download
    Step 'Procurando a versão mais recente no GitHub'
    $zipUrl = "https://github.com/$Repo/releases/latest/download/rm-scraping.zip"
    $tag = 'mais recente'
    try {
        $rel = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -UseBasicParsing `
                   -Headers @{ 'User-Agent' = 'rm-scraping-installer' }
        $tag = $rel.tag_name
        $asset = $rel.assets | Where-Object { $_.name -eq 'rm-scraping.zip' } | Select-Object -First 1
        if (-not $asset) { $asset = $rel.assets | Where-Object { $_.name -like 'rm-scraping-v*.zip' } | Select-Object -First 1 }
        if ($asset) { $zipUrl = $asset.browser_download_url }
    } catch { Info 'API do GitHub indisponível; usando o link direto' }

    $verFile = Join-Path $Dir 'rmbh_scraper\_version.py'
    $old = if (Test-Path $verFile) { 'v' + ((Get-Content $verFile -Raw) -replace '[^0-9.]', '') } else { $null }
    if ($old) { Ok "instalada: $old  ->  disponível: $tag" } else { Ok "versão: $tag" }

    Step 'Baixando e extraindo os arquivos'
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
        Get-ChildItem $src -Force | Where-Object { $_.Name -ne 'instalar.bat' } |   # never overwrite the running installer
            ForEach-Object { Copy-Item $_.FullName -Destination $Dir -Recurse -Force }
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force (Join-Path $Dir 'data') | Out-Null
    Ok 'arquivos atualizados (a pasta data\ foi preservada)'

    # ------------------------------------------------------------ 2. Python + dependencies
    Step 'Verificando o Python'
    $py = Find-Python
    if (-not $py) {
        Info "Python 3.9 ou mais novo não encontrado; instalando o Python $PyVersion"
        Install-Python
        $py = Find-Python
        if (-not $py) { throw 'o Python foi instalado mas não foi encontrado; feche esta janela e rode o instalador de novo' }
    }
    Ok "Python: $py"

    Step 'Instalando as dependências'
    if ((Test-Path $VPy) -and -not (Test-Py @($VPy))) {
        Info 'ambiente antigo inválido; recriando'
        Remove-Item $Venv -Recurse -Force
    }
    if (-not (Test-Path $VPy)) {
        & $py -m venv $Venv
        if ($LASTEXITCODE -ne 0) { throw 'não foi possível criar o ambiente virtual (.venv)' }
    }
    & $VPy -m pip install --disable-pip-version-check --quiet --upgrade -r (Join-Path $Dir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'falha ao instalar as dependências (verifique a conexão com a internet)' }
    $ver = & $VPy -m rmbh_scraper --version
    if ($LASTEXITCODE -ne 0) { throw 'o programa não iniciou após a instalação' }
    Ok "$ver pronto"

    # ------------------------------------------------------------ 3. launchers
    Step 'Criando os atalhos'
    $head = @('@echo off', 'chcp 65001 >nul', 'cd /d "%~dp0"')
    Write-Bat 'Coletar imoveis.bat' ($head + @(
        'title Coleta - RM Imóveis',
        'rem Coleta todos os imóveis e abre a apresentação. Use --images para baixar as fotos.',
        '".venv\Scripts\python.exe" -m rmbh_scraper crawl %*',
        'if errorlevel 1 pause'))
    Write-Bat 'Abrir apresentacao.bat' ($head + @(
        'title Apresentação - RM Imóveis',
        '".venv\Scripts\python.exe" -m rmbh_scraper view %*',
        'if errorlevel 1 pause'))
    Ok 'Coletar imoveis.bat   - coleta os imóveis e abre a apresentação'
    Ok 'Abrir apresentacao.bat - abre a apresentação com os dados atuais'

    # ------------------------------------------------------------ 4. daily schedule (optional)
    Step 'Coleta diária automática'
    try {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) {
            Register-Crawl $task.Triggers   # keep the chosen time, refresh the paths
            Ok "agendamento existente mantido ('$TaskName')"
        } else {
            $ans = Read-Host '    Deseja agendar a coleta para rodar todo dia automaticamente? (S/N)'
            if ($ans -match '^\s*[sSyY]') {
                $h = Read-Host '    Horário (HH:MM) [08:00]'
                if (-not $h) { $h = '08:00' }
                $at = [datetime]::ParseExact($h.Trim(), [string[]]@('H:mm', 'HH:mm', 'H'),
                                             [Globalization.CultureInfo]::InvariantCulture, 'None')
                Register-Crawl (New-ScheduledTaskTrigger -Daily -At $at)
                Ok ("agendado todo dia às {0:HH:mm} (log em data\coleta.log)" -f $at)
                Info 'se o computador estiver desligado no horário, a coleta roda assim que ele ligar'
            } else {
                Info 'sem agendamento (rode o instalador de novo se mudar de ideia)'
            }
        }
    } catch {
        Write-Host "    não foi possível configurar o agendamento: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    Write-Host ''
    Write-Host '  Instalação concluída!' -ForegroundColor Green
    Write-Host '  - Clique duas vezes em "Coletar imoveis.bat" para buscar os imóveis.'
    Write-Host '  - Para atualizar o programa no futuro, rode este instalador de novo.'
    exit 0
} catch {
    Write-Host ''
    Write-Host "  ERRO: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
