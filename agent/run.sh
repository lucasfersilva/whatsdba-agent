#!/bin/bash
# ═══════════════════════════════════════════════════
#  WhatsDBA — Iniciar Agente
# ═══════════════════════════════════════════════════
set -e

cd "$(dirname "$0")"

if [ -d "venv" ]; then
    source venv/bin/activate
fi

if [ ! -f ".env" ]; then
    echo "❌ .env não encontrado. Rode ./setup.sh primeiro."
    exit 1
fi

echo ""
echo "🤖 WhatsDBA Agente iniciando..."
echo "   Pressione Ctrl+C para parar."
echo ""

python3 main.py
