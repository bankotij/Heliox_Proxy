#!/bin/bash
# Setup script for Heliox demo environment

set -e

API_URL="${API_URL:-http://localhost:8000}"
ADMIN_KEY="${ADMIN_KEY:-admin-secret-key}"

echo "🚀 Setting up Heliox demo environment..."
echo "API URL: $API_URL"

# Wait for API to be ready
echo "⏳ Waiting for API to be ready..."
until curl -s "$API_URL/health" > /dev/null 2>&1; do
  sleep 2
done
echo "✅ API is ready"

# Create demo tenant
echo "📦 Creating demo tenant..."
TENANT_RESPONSE=$(curl -s -X POST "$API_URL/admin/tenants" \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Demo Tenant", "description": "Demo tenant for testing"}')

TENANT_ID=$(echo $TENANT_RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")

if [ -z "$TENANT_ID" ]; then
  echo "⚠️  Tenant might already exist, fetching..."
  TENANT_ID=$(curl -s "$API_URL/admin/tenants" \
    -H "X-Admin-Key: $ADMIN_KEY" | python3 -c "import sys, json; print(json.load(sys.stdin)[0]['id'])" 2>/dev/null)
fi

echo "✅ Tenant ID: $TENANT_ID"

# Create API key
echo "🔑 Creating API key..."
KEY_RESPONSE=$(curl -s -X POST "$API_URL/admin/keys" \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"tenant_id\": \"$TENANT_ID\", \"name\": \"Demo Key\", \"quota_daily\": 10000}")

API_KEY=$(echo $KEY_RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin)['key'])" 2>/dev/null || echo "")

if [ -z "$API_KEY" ]; then
  echo "⚠️  Could not create key, listing existing..."
  API_KEY=$(curl -s "$API_URL/admin/keys" \
    -H "X-Admin-Key: $ADMIN_KEY" | python3 -c "import sys, json; print(json.load(sys.stdin)[0]['key_prefix'] + '...')" 2>/dev/null)
else
  echo "✅ API Key: $API_KEY"
  echo ""
  echo "⚠️  SAVE THIS KEY - it won't be shown again!"
fi

# Create cache policy
echo "📋 Creating cache policy..."
curl -s -X POST "$API_URL/admin/policies" \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "default",
    "description": "Default cache policy",
    "ttl_seconds": 300,
    "stale_seconds": 60,
    "cacheable_statuses_json": [200, 201, 204, 301, 304]
  }' > /dev/null

echo "✅ Cache policy created"

# Get policy ID
POLICY_ID=$(curl -s "$API_URL/admin/policies" \
  -H "X-Admin-Key: $ADMIN_KEY" | python3 -c "import sys, json; print(json.load(sys.stdin)[0]['id'])" 2>/dev/null)

# Create demo route
echo "🛤️  Creating demo route..."
curl -s -X POST "$API_URL/admin/routes" \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"demo\",
    \"description\": \"Demo route to example upstream\",
    \"path_pattern\": \"/*\",
    \"methods\": [\"GET\", \"POST\", \"PUT\", \"PATCH\", \"DELETE\"],
    \"upstream_base_url\": \"http://upstream:8001\",
    \"timeout_ms\": 30000,
    \"policy_id\": \"$POLICY_ID\"
  }" > /dev/null

echo "✅ Demo route created"

echo ""
echo "=========================================="
echo "🎉 Demo setup complete!"
echo "=========================================="
echo ""
echo "Gateway URL: $API_URL"
echo "Admin UI: http://localhost:3000"
echo "Upstream: http://localhost:8001"
echo ""
echo "Try these commands:"
echo ""
echo "# Cache miss (slow):"
echo "curl '$API_URL/g/demo/slow?delay=2' -H 'X-API-Key: YOUR_KEY'"
echo ""
echo "# Cache hit (fast):"
echo "curl '$API_URL/g/demo/slow?delay=2' -H 'X-API-Key: YOUR_KEY'"
echo ""
echo "# List items:"
echo "curl '$API_URL/g/demo/items' -H 'X-API-Key: YOUR_KEY'"
echo ""
