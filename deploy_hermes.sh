#!/bin/bash
# Hermes Groq Deployment Script
# Run this from your local machine to deploy Hermes with Groq

set -e

echo "🚀 Deploying Hermes with Groq..."
echo ""

# Check we're in the right directory
if [ ! -f "backend/services/hermes_agent.py" ]; then
    echo "❌ Error: Please run this from the Algotrading repository root"
    exit 1
fi

# Fetch latest changes
echo "📥 Fetching latest changes..."
git fetch origin claude/tender-mendel-R2h2U

# Switch to branch
echo "🔄 Switching to branch..."
git checkout claude/tender-mendel-R2h2U

# Pull any changes
echo "⬇️  Pulling changes..."
git pull origin claude/tender-mendel-R2h2U

# Show recent commits
echo ""
echo "📝 Recent commits:"
git log --oneline -6
echo ""

# Confirm before pushing
read -p "✅ Ready to push to Railway? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Deployment cancelled"
    exit 1
fi

# Push to Railway
echo "🚀 Pushing to Railway..."
git push origin claude/tender-mendel-R2h2U

echo ""
echo "✅ Code pushed successfully!"
echo ""
echo "⏳ Railway is deploying (takes ~2 minutes)..."
echo ""
echo "📋 Next steps:"
echo "1. Add GROQ_API_KEY to Railway environment variables"
echo "   - Get key from: https://console.groq.com/"
echo "   - Add to Railway: GROQ_API_KEY=gsk_YOUR_KEY"
echo ""
echo "2. Wait for Railway deployment to complete"
echo ""
echo "3. Check Railway logs for:"
echo "   ✅ [Hermes] Hermes Agent initialized"
echo "   ✅ [Hermes] NIFTYBEES: HOLD/BUY (confidence=0.XX)"
echo ""
echo "📖 See HERMES_DEPLOY_GROQ.md for detailed instructions"
echo ""
