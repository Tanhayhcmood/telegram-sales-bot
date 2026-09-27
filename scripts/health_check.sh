#!/bin/bash
BASE_URL="${APP_URL:-http://localhost:8000}"

echo "=== Health Check ==="

response=$(curl -sf "${BASE_URL}/api/healthz" 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "✅ API: OK - $response"
else
    echo "❌ API: FAILED"
    exit 1
fi

response=$(curl -sf -H "X-API-Key: ${API_KEY}" "${BASE_URL}/api/v1/metrics/health" 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "✅ Full Health: OK"
    echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
else
    echo "❌ Full Health: FAILED"
fi
