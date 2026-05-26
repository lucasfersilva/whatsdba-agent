# ═══════════════════════════════════════════════════════════════════
#  WhatsDBA Agent — Instalador para Windows Server
#  Execute como Administrador: Right-click → "Run as Administrator"
# ═══════════════════════════════════════════════════════════════════
#Requires -RunAsAdministrator

$AgentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServiceName = "WhatsDBA-Agent"
$PythonMin = "3.11"

Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "  WhatsDBA Agent — Instalador Windows" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Verifica Python ────────────────────────────────────────────────────────
Write-Host "Verificando Python..." -ForegroundColor Yellow

# Função para encontrar o python.exe mesmo quando o PATH não foi atualizado na sessão atual
function Find-PythonExe {
    # 1. Tenta pelo PATH normal
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }

    # 2. Atualiza PATH da máquina e tenta de novo
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }

    # 3. Procura em caminhos comuns de instalação
    $commonPaths = @(
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "$env:ProgramFiles\Python310\python.exe",
        "$env:LocalAppData\Programs\Python\Python312\python.exe",
        "$env:LocalAppData\Programs\Python\Python311\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe"
    )
    foreach ($p in $commonPaths) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

$pythonExePath = Find-PythonExe
if (-not $pythonExePath) {
    Write-Host "Python nao encontrado. Baixando instalador..." -ForegroundColor Red
    $pythonUrl = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"
    $installer = "$env:TEMP\python-installer.exe"
    Write-Host "  Baixando Python 3.12..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $pythonUrl -OutFile $installer -UseBasicParsing
    Write-Host "  Instalando Python (aguarde)..." -ForegroundColor Yellow
    Start-Process -FilePath $installer -Args "/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1" -Wait
    Start-Sleep -Seconds 3
    $pythonExePath = Find-PythonExe
    if (-not $pythonExePath) {
        Write-Host "ERRO: Falha ao instalar Python. Instale manualmente em https://python.org e rode novamente." -ForegroundColor Red
        exit 1
    }
}
$pyVer = & "$pythonExePath" --version
Write-Host "OK: $pyVer ($pythonExePath)" -ForegroundColor Green

# ── 2. Cria virtualenv ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Criando ambiente virtual..." -ForegroundColor Yellow
Set-Location $AgentDir

# Remove venv corrompido (existe mas sem python.exe dentro)
if ((Test-Path "venv") -and (-not (Test-Path "venv\Scripts\python.exe"))) {
    Write-Host "  venv corrompido encontrado, removendo..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "venv"
}

if (-not (Test-Path "venv")) {
    Write-Host "  Criando venv com $pythonExePath ..." -ForegroundColor Yellow
    & "$pythonExePath" -m venv venv
    if (-not (Test-Path "venv\Scripts\python.exe")) {
        Write-Host "ERRO: Falha ao criar o ambiente virtual." -ForegroundColor Red
        Write-Host "  Tente rodar manualmente: $pythonExePath -m venv $AgentDir\venv" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "  OK: venv criado" -ForegroundColor Green
} else {
    Write-Host "  venv ja existe, reutilizando" -ForegroundColor DarkGray
}

Write-Host "  Instalando dependencias..." -ForegroundColor Yellow
& ".\venv\Scripts\python.exe" -m pip install --upgrade pip -q
& ".\venv\Scripts\pip.exe" install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: Falha ao instalar dependencias. Verifique sua conexao com a internet." -ForegroundColor Red
    exit 1
}
Write-Host "OK: dependencias instaladas" -ForegroundColor Green

# ── 3. Verifica ODBC Driver (SQL Server) ─────────────────────────────────────
Write-Host ""
Write-Host "Verificando ODBC Driver 17 para SQL Server..." -ForegroundColor Yellow
$odbc = Get-ItemProperty "HKLM:\SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 17 for SQL Server" -ErrorAction SilentlyContinue
if ($odbc) {
    Write-Host "OK: ODBC Driver 17 encontrado" -ForegroundColor Green
} else {
    Write-Host "AVISO: ODBC Driver 17 nao encontrado." -ForegroundColor Yellow
    Write-Host "  Baixe em: https://aka.ms/odbc17" -ForegroundColor Yellow
    Write-Host "  (Necessario apenas para monitorar SQL Server)" -ForegroundColor Yellow
}

# ── 4. Verifica .env ──────────────────────────────────────────────────────────
Write-Host ""
if (-not (Test-Path "$AgentDir\.env")) {
    Copy-Item "$AgentDir\.env.example" "$AgentDir\.env"
    Write-Host "IMPORTANTE: Configure o arquivo .env antes de continuar!" -ForegroundColor Red
    Write-Host "  Caminho: $AgentDir\.env" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Variaveis obrigatorias:" -ForegroundColor Yellow
    Write-Host "    WHATSDBA_LICENSE_KEY=WDBA-..." -ForegroundColor White
    Write-Host "    WHATSDBA_SERVER_URL=https://whatsdba.infractrl.com.br" -ForegroundColor White
    Write-Host '    DATABASES=[{"type":"sqlserver","name":"Prod","host":"127.0.0.1","port":1433,"user":"sa","password":"senha","database":"master"}]' -ForegroundColor White
    Write-Host ""
    notepad "$AgentDir\.env"
    Read-Host "Pressione Enter apos salvar o .env para continuar"
}

# ── 5. Instala como Windows Service via NSSM ──────────────────────────────────
Write-Host ""
Write-Host "Instalando como Windows Service..." -ForegroundColor Yellow

# Verifica se NSSM existe, se nao baixa
$nssm     = "$AgentDir\nssm.exe"
$useNssm  = $false

if (-not (Test-Path $nssm)) {
    Write-Host "  Baixando NSSM (gerenciador de servicos)..." -ForegroundColor Yellow

    $nssmZip  = "$env:TEMP\nssm.zip"
    $nssmUrls = @(
        "https://github.com/kirillkovalenko/nssm/releases/download/v2.24/nssm-2.24.zip",
        "https://nssm.cc/release/nssm-2.24.zip",
        "https://www.nssm.cc/release/nssm-2.24.zip"
    )

    foreach ($url in $nssmUrls) {
        try {
            Write-Host "  Tentando: $url" -ForegroundColor DarkGray
            Invoke-WebRequest -Uri $url -OutFile $nssmZip -TimeoutSec 20 -ErrorAction Stop
            if (Test-Path $nssmZip) { break }
        } catch {
            Write-Host "  Falhou, tentando proximo..." -ForegroundColor DarkGray
        }
    }

    if (Test-Path $nssmZip) {
        Expand-Archive -Path $nssmZip -DestinationPath "$env:TEMP\nssm_extract" -Force
        $nssmExe = Get-ChildItem "$env:TEMP\nssm_extract" -Recurse -Filter "nssm.exe" |
                   Where-Object { $_.FullName -like "*win64*" } |
                   Select-Object -First 1
        if (-not $nssmExe) {
            $nssmExe = Get-ChildItem "$env:TEMP\nssm_extract" -Recurse -Filter "nssm.exe" | Select-Object -First 1
        }
        if ($nssmExe) {
            Copy-Item $nssmExe.FullName $nssm
            Write-Host "  OK: NSSM instalado" -ForegroundColor Green
        }
    }
}

if (Test-Path $nssm) {
    $useNssm = $true
} else {
    Write-Host "  NSSM nao disponivel. Usando Windows Service nativo (sc.exe)..." -ForegroundColor Yellow
}

# Cria pasta de logs
New-Item -ItemType Directory -Force -Path "$AgentDir\logs" | Out-Null

$pythonExe  = "$AgentDir\venv\Scripts\python.exe"
$mainScript = "$AgentDir\main.py"

# Remove servico antigo se existir
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host "  Removendo servico anterior..." -ForegroundColor Yellow
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    if ($useNssm) {
        & $nssm remove $ServiceName confirm 2>$null
    } else {
        sc.exe delete $ServiceName | Out-Null
    }
    Start-Sleep -Seconds 3
}

if ($useNssm) {
    # ── Instala via NSSM (melhor suporte a logs e restart) ──────────────
    & $nssm install  $ServiceName $pythonExe $mainScript
    & $nssm set      $ServiceName AppDirectory  $AgentDir
    & $nssm set      $ServiceName DisplayName   "WhatsDBA Agent"
    & $nssm set      $ServiceName Description   "Agente de monitoramento WhatsDBA"
    & $nssm set      $ServiceName Start         SERVICE_AUTO_START
    & $nssm set      $ServiceName AppStdout     "$AgentDir\logs\agent.log"
    & $nssm set      $ServiceName AppStderr     "$AgentDir\logs\agent-error.log"
    & $nssm set      $ServiceName AppRotateFiles 1
    & $nssm set      $ServiceName AppRotateBytes 10485760
    & $nssm set      $ServiceName AppRestartDelay 5000
    & $nssm start    $ServiceName
} else {
    # ── Fallback: wrapper .bat + sc.exe ────────────────────────────────
    # Cria um wrapper .bat que o sc.exe consegue executar
    $wrapperBat = "$AgentDir\run-service.bat"
    @"
@echo off
cd /d "$AgentDir"
"$pythonExe" "$mainScript" >> "$AgentDir\logs\agent.log" 2>> "$AgentDir\logs\agent-error.log"
"@ | Set-Content $wrapperBat -Encoding ASCII

    # Usa sc.exe para criar o servico com o wrapper
    # Como sc nao roda .bat nativamente, usamos powershell como executor
    $psCmd = "powershell.exe -NonInteractive -NoProfile -ExecutionPolicy Bypass -Command `"Set-Location '$AgentDir'; & '$pythonExe' '$mainScript'`""
    sc.exe create $ServiceName binPath= $psCmd start= auto DisplayName= "WhatsDBA Agent" | Out-Null
    sc.exe description $ServiceName "Agente de monitoramento WhatsDBA - coleta metricas de bancos de dados" | Out-Null
    sc.exe failure $ServiceName reset= 60 actions= restart/5000/restart/10000/restart/30000 | Out-Null
    Start-Service -Name $ServiceName -ErrorAction SilentlyContinue
}

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host ""
    Write-Host "====================================================" -ForegroundColor Green
    Write-Host "  WhatsDBA Agent instalado e rodando!" -ForegroundColor Green
    Write-Host "====================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Servico: $ServiceName" -ForegroundColor White
    Write-Host "  Status:  Running" -ForegroundColor Green
    Write-Host "  Logs:    $AgentDir\logs\agent.log" -ForegroundColor White
    Write-Host ""
    Write-Host "  Comandos uteis:" -ForegroundColor Yellow
    Write-Host "    Parar:    Stop-Service $ServiceName" -ForegroundColor White
    Write-Host "    Iniciar:  Start-Service $ServiceName" -ForegroundColor White
    Write-Host "    Status:   Get-Service $ServiceName" -ForegroundColor White
    Write-Host "    Logs:     Get-Content $AgentDir\logs\agent.log -Tail 50" -ForegroundColor White
} else {
    Write-Host "AVISO: Servico instalado mas pode nao ter iniciado." -ForegroundColor Yellow
    Write-Host "Verifique os logs em: $AgentDir\logs\" -ForegroundColor Yellow
    Write-Host "Ou tente: Start-Service $ServiceName" -ForegroundColor Yellow
}
