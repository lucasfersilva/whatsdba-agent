#!/bin/bash
# ═══════════════════════════════════════════════════
#  WhatsDBA — Setup do Agente (roda no cliente)
# ═══════════════════════════════════════════════════
set -e

echo ""
echo "🤖 WhatsDBA — Setup do Agente"
echo "════════════════════════════════"

# Verifica Python
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 não encontrado. Instale Python 3.11+"
    exit 1
fi

PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✅ Python $PYTHON_VER encontrado"

# Aviso sobre ODBC Driver (SQL Server)
echo ""
echo "ℹ️  Para monitorar SQL Server, você precisa do ODBC Driver 17:"
echo "   Ubuntu/Debian: https://docs.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server"
echo "   (pode pular se usar apenas MySQL)"
echo ""

# Cria virtualenv
if [ ! -d "venv" ]; then
    echo "📦 Criando ambiente virtual..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "📦 Instalando dependências..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "✅ Dependências instaladas"

# Verifica .env
if [ ! -f ".env" ]; then
    echo ""
    echo "⚠️  Arquivo .env não encontrado. Criando modelo..."
    cp .env.example .env
    echo ""
    echo "✏️  CONFIGURE o arquivo agent/.env:"
    echo "   1. WHATSDBA_LICENSE_KEY=  → chave gerada no painel WhatsDBA"
    echo "   2. WHATSDBA_SERVER_URL=   → URL do servidor SaaS"
    echo "   3. DATABASES=             → bancos a monitorar (JSON)"
    echo ""
    echo "Exemplo de DATABASES no .env:"
    echo '  DATABASES=[{"type":"sqlserver","name":"Prod","host":"127.0.0.1","port":1433,"user":"sa","password":"senha","database":"master"}]'
    echo ""
    echo "Após configurar, rode: ./run.sh"
else
    echo "✅ .env encontrado"
    echo ""
    echo "✅ Setup concluído! Rode ./run.sh para iniciar o agente."
fi
