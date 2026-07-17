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
npm install
npm run build
cd ..

echo "✅ Build complete!"
echo "Frontend build folder: $(ls -lh frontend/build 2>/dev/null || echo 'NOT FOUND')"
