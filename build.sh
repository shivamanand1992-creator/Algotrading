#!/bin/bash
set -e

echo "=========================================="
echo "Building Algotrading - Frontend + Backend"
echo "=========================================="
echo "Build started at: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "Current directory: $(pwd)"
echo "Node version: $(node --version 2>/dev/null || echo 'NOT FOUND')"
echo "NPM version: $(npm --version 2>/dev/null || echo 'NOT FOUND')"

# Install Python dependencies
echo ""
echo "📦 Installing Python dependencies..."
pip install 'setuptools<68'
pip install -r requirements.txt

# Build frontend
echo ""
echo "🎨 Building React frontend..."
echo "Entering frontend directory..."
cd frontend

echo "Cleaning old builds..."
rm -rf node_modules/.cache build

echo "Installing frontend dependencies..."
npm install --verbose

echo "Running React build..."
GENERATE_SOURCEMAP=false npm run build

echo ""
echo "Verifying frontend build..."
if [ -d "build" ]; then
    echo "✅ frontend/build directory exists!"
    echo "Build contents:"
    ls -lh build/
    echo ""
    echo "Build size:"
    du -sh build/
    echo ""
    echo "Checking for index.html:"
    if [ -f "build/index.html" ]; then
        echo "✅ build/index.html found!"
        head -n 5 build/index.html
    else
        echo "❌ ERROR: build/index.html NOT FOUND!"
        exit 1
    fi
else
    echo "❌ ERROR: frontend/build directory NOT CREATED!"
    echo "Something went wrong with npm run build"
    exit 1
fi

cd ..

echo ""
echo "=========================================="
echo "✅ Build complete!"
echo "=========================================="
echo "Build finished at: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
