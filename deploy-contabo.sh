#!/bin/bash
set -e

echo "=== Hyperclients Deploy Script ==="

cd /root

# Clone or pull latest code
REPO_URL=https://github.com/pratikkshirsagar832-ctrl/Lead-forge-Ai.git
if [ -d "Lead-forge-Ai" ]; then
  cd Lead-forge-Ai
  git pull
else
  git clone $REPO_URL
  cd Lead-forge-Ai
fi

# Ensure frontend .env.local has all keys (fill in your real values)
cat > frontend/.env.local << 'ENVEOF'
NEXT_PUBLIC_API_URL=https://YOUR_API_DOMAIN
NEXT_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=YOUR_SUPABASE_ANON_KEY
NEXT_PUBLIC_RAZORPAY_KEY_ID=rzp_xxx_xxxxxxxxxxxx
GOOGLE_SEARCH_API_KEY=YOUR_GOOGLE_API_KEY
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
ENVEOF

# Backend env
cat > backend/.env << 'ENVEOF'
ENVIRONMENT=production
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_SERVICE_ROLE_KEY=YOUR_SUPABASE_SERVICE_ROLE_KEY
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
RAZORPAY_KEY_ID=rzp_xxx_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=YOUR_RAZORPAY_SECRET
ENVEOF

# Stop old containers
docker compose down 2>/dev/null || true

# Build and start
docker compose up -d --build

echo "=== Deploy complete! ==="
echo "Frontend: http://$(curl -s ifconfig.me):3000"
echo "Backend:  http://$(curl -s ifconfig.me):8000"
echo ""
echo "Check logs: docker compose logs -f"
