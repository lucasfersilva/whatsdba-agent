#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  WhatsDBA Agent — Instalador para Linux
#  Testado em: Ubuntu 20.04/22.04/24.04, Debian 11/12, RHEL/CentOS 8+
#  Execute como root ou com sudo:
#    sudo bash install-linux.sh
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Cores ─────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "  ${GREEN}✓${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "  ${RED}✗${RESET}  $*"; exit 1; }
info() { echo -e "  ${CYAN}→${RESET}  $*"; }

AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="whatsdba-agent"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SERVICE_USER="${SUDO_USER:-$(whoami)}"   # roda como o usuário que chamou sudo
VENV_DIR="${AGENT_DIR}/venv"
LOG_DIR="${AGENT_DIR}/logs"
PYTHON_MIN="3.9"

echo ""
echo -e "${CYAN}${BOLD}════════════════════════════════════════════${RESET}"
echo -e "${CYAN}${BOLD}  WhatsDBA Agent — Instalador Linux${RESET}"
echo -e "${CYAN}${BOLD}════════════════════════════════════════════${RESET}"
echo ""

# ── Verifica root ─────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  err "Execute com sudo: sudo bash install-linux.sh"
fi

# ── 1. Verifica Python 3.9+ ───────────────────────────────────────
echo -e "${BOLD}[1/5] Verificando Python...${RESET}"

PYTHON=""
for cmd in python3 python3.12 python3.11 python3.10 python3.9; do
  if command -v "$cmd" &>/dev/null; then
    VER=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    MAJOR=${VER%%.*}; MINOR=${VER##*.}
    if [[ $MAJOR -ge 3 && $MINOR -ge 9 ]]; then
      PYTHON="$cmd"; ok "Encontrado: $cmd ($VER)"; break
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  warn "Python 3.9+ não encontrado. Tentando instalar..."
  if command -v apt-get &>/dev/null; then
    apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip
    PYTHON="python3"
  elif command -v dnf &>/dev/null; then
    dnf install -y -q python3 python3-pip
    PYTHON="python3"
  elif command -v yum &>/dev/null; then
    yum install -y -q python3 python3-pip
    PYTHON="python3"
  else
    err "Não foi possível instalar Python automaticamente. Instale Python 3.9+ e execute novamente."
  fi
  ok "Python instalado: $($PYTHON --version)"
fi

# ── 2. Cria virtualenv ────────────────────────────────────────────
echo ""
echo -e "${BOLD}[2/5] Configurando ambiente virtual...${RESET}"
cd "$AGENT_DIR"

# Remove venv corrompido
if [[ -d "$VENV_DIR" && ! -f "$VENV_DIR/bin/python" ]]; then
  warn "venv corrompido encontrado, removendo..."
  rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  info "Criando venv..."
  "$PYTHON" -m venv "$VENV_DIR" || err "Falha ao criar venv. Instale python3-venv: sudo apt install python3-venv"
  ok "venv criado"
else
  ok "venv já existe, reutilizando"
fi

info "Instalando dependências..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r requirements.txt -q
ok "Dependências instaladas"

# ── 3. Verifica ODBC Driver (SQL Server) ─────────────────────────
echo ""
echo -e "${BOLD}[3/5] Verificando ODBC Driver para SQL Server...${RESET}"

ODBC_OK=false
if command -v odbcinst &>/dev/null; then
  if odbcinst -q -d -n "ODBC Driver 17 for SQL Server" &>/dev/null 2>&1 || \
     odbcinst -q -d -n "ODBC Driver 18 for SQL Server" &>/dev/null 2>&1; then
    ODBC_OK=true; ok "ODBC Driver encontrado"
  fi
fi

if [[ "$ODBC_OK" == "false" ]]; then
  warn "ODBC Driver para SQL Server não encontrado (necessário apenas para SQL Server)."
  echo ""
  echo -e "  Para instalar no Ubuntu/Debian:"
  echo -e "    ${CYAN}curl https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -${RESET}"
  echo -e "    ${CYAN}curl https://packages.microsoft.com/config/ubuntu/\$(lsb_release -rs)/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list${RESET}"
  echo -e "    ${CYAN}sudo apt-get update && sudo ACCEPT_EULA=Y apt-get install -y msodbcsql17 unixodbc-dev${RESET}"
  echo ""
  echo -e "  Para instalar no RHEL/CentOS:"
  echo -e "    ${CYAN}curl https://packages.microsoft.com/config/rhel/8/prod.repo | sudo tee /etc/yum.repos.d/mssql-release.repo${RESET}"
  echo -e "    ${CYAN}sudo ACCEPT_EULA=Y dnf install -y msodbcsql17${RESET}"
  echo ""
  echo -e "  Documentação: ${CYAN}https://aka.ms/odbc-linux${RESET}"
  echo ""
  read -r -p "  Continuar sem o ODBC Driver? (apenas MySQL será monitorado) [s/N] " RESP
  [[ "${RESP,,}" == "s" ]] || err "Instale o ODBC Driver e execute novamente."
fi

# ── 4. Configura .env ─────────────────────────────────────────────
echo ""
echo -e "${BOLD}[4/5] Configurando .env...${RESET}"

if [[ ! -f "${AGENT_DIR}/.env" ]]; then
  if [[ -f "${AGENT_DIR}/.env.example" ]]; then
    cp "${AGENT_DIR}/.env.example" "${AGENT_DIR}/.env"
  else
    cat > "${AGENT_DIR}/.env" << 'EOF'
# ── WhatsDBA Agent — Configuração ───────────────────────────────────
WHATSDBA_LICENSE_KEY=WDBA-XXXX-XXXX-XXXX
WHATSDBA_SERVER_URL=https://whatsdba.infractrl.com.br
COLLECT_INTERVAL=60

# Instâncias monitoradas (auto-descobre todos os bancos)
# SQL Server:
# INSTANCES=[{"type":"sqlserver","host":"127.0.0.1","port":1433,"user":"sa","password":"SENHA"}]
# MySQL:
# INSTANCES=[{"type":"mysql","host":"127.0.0.1","port":3306,"user":"root","password":"SENHA"}]
INSTANCES=[{"type":"sqlserver","host":"127.0.0.1","port":1433,"user":"sa","password":"SUA_SENHA_AQUI"}]
EOF
  fi

  warn "IMPORTANTE: configure o arquivo .env antes de continuar!"
  echo -e "  Caminho: ${CYAN}${AGENT_DIR}/.env${RESET}"
  echo ""
  echo -e "  Variáveis obrigatórias:"
  echo -e "    ${CYAN}WHATSDBA_LICENSE_KEY${RESET}=WDBA-..."
  echo -e "    ${CYAN}WHATSDBA_SERVER_URL${RESET}=https://whatsdba.infractrl.com.br"
  echo -e "    ${CYAN}INSTANCES${RESET}=[{\"type\":\"sqlserver\",\"host\":\"IP\",\"port\":1433,\"user\":\"sa\",\"password\":\"SENHA\"}]"
  echo ""

  # Abre editor
  EDITOR_CMD=""
  for ed in nano vim vi; do
    if command -v "$ed" &>/dev/null; then EDITOR_CMD="$ed"; break; fi
  done

  if [[ -n "$EDITOR_CMD" ]]; then
    read -r -p "  Abrir o editor agora para configurar o .env? [S/n] " RESP
    [[ "${RESP,,}" != "n" ]] && "$EDITOR_CMD" "${AGENT_DIR}/.env"
  else
    warn "Nenhum editor encontrado. Edite manualmente: ${AGENT_DIR}/.env"
  fi
else
  ok ".env já existe, mantendo configuração atual"
fi

# ── 5. Instala serviço systemd ────────────────────────────────────
echo ""
echo -e "${BOLD}[5/5] Instalando serviço systemd...${RESET}"

mkdir -p "$LOG_DIR"

# Para e remove serviço anterior se existir
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
  info "Parando serviço anterior..."
  systemctl stop "$SERVICE_NAME"
fi
if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
  systemctl disable "$SERVICE_NAME" &>/dev/null
fi

# Escreve o unit file
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=WhatsDBA Agent — Monitoramento de banco de dados
Documentation=https://whatsdba.infractrl.com.br
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${AGENT_DIR}
ExecStart=${VENV_DIR}/bin/python ${AGENT_DIR}/main.py
Restart=on-failure
RestartSec=10
StartLimitInterval=60
StartLimitBurst=5
StandardOutput=append:${LOG_DIR}/agent.log
StandardError=append:${LOG_DIR}/agent-error.log
EnvironmentFile=${AGENT_DIR}/.env

[Install]
WantedBy=multi-user.target
EOF

# Ajusta dono dos arquivos para o usuário correto
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${AGENT_DIR}" 2>/dev/null || true

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start  "$SERVICE_NAME"

sleep 2

echo ""
if systemctl is-active --quiet "$SERVICE_NAME"; then
  echo -e "${GREEN}${BOLD}════════════════════════════════════════════${RESET}"
  echo -e "${GREEN}${BOLD}  WhatsDBA Agent instalado e rodando!${RESET}"
  echo -e "${GREEN}${BOLD}════════════════════════════════════════════${RESET}"
  echo ""
  echo -e "  Serviço:  ${CYAN}${SERVICE_NAME}${RESET}"
  echo -e "  Status:   ${GREEN}running${RESET}"
  echo -e "  Logs:     ${CYAN}${LOG_DIR}/agent.log${RESET}"
  echo ""
  echo -e "  ${BOLD}Comandos úteis:${RESET}"
  echo -e "    Status:    ${CYAN}sudo systemctl status ${SERVICE_NAME}${RESET}"
  echo -e "    Logs live: ${CYAN}sudo journalctl -u ${SERVICE_NAME} -f${RESET}"
  echo -e "    Parar:     ${CYAN}sudo systemctl stop ${SERVICE_NAME}${RESET}"
  echo -e "    Reiniciar: ${CYAN}sudo systemctl restart ${SERVICE_NAME}${RESET}"
  echo ""
else
  echo -e "${YELLOW}${BOLD}Serviço instalado mas não iniciou corretamente.${RESET}"
  echo -e "  Verifique o .env e os logs:"
  echo -e "    ${CYAN}sudo journalctl -u ${SERVICE_NAME} -n 50${RESET}"
  echo -e "    ${CYAN}cat ${LOG_DIR}/agent-error.log${RESET}"
  echo ""
  echo -e "  Após corrigir, reinicie com:"
  echo -e "    ${CYAN}sudo systemctl restart ${SERVICE_NAME}${RESET}"
fi
