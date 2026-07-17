#!/bin/bash
set -e

echo "=========================================="
echo "Building Algotrading - Frontend + Backend"
echo "=========================================="

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install 'setuptools<68'
pip install -r requirements.txt

# Build frontend
echo "🎨 Building React frontend..."
cd frontend
rm -rf node_modules/.cache build
npm ci --prefer-offline
GENERATE_SOURCEMAP=false npm run build
cd ..

echo "✅ Build complete!"
ls -lh frontend/build/ 2>/dev/null || echo "❌ WARNING: frontend/build not found"
