# Setup script for Heliox demo environment (PowerShell)

$ErrorActionPreference = "Stop"

$ApiUrl = if ($env:API_URL) { $env:API_URL } else { "http://localhost:8000" }
$AdminKey = if ($env:ADMIN_KEY) { $env:ADMIN_KEY } else { "admin-secret-key" }

Write-Host "🚀 Setting up Heliox demo environment..." -ForegroundColor Green
Write-Host "API URL: $ApiUrl"

# Wait for API to be ready
Write-Host "⏳ Waiting for API to be ready..."
$maxRetries = 30
$retryCount = 0
while ($retryCount -lt $maxRetries) {
    try {
        $response = Invoke-RestMethod -Uri "$ApiUrl/health" -Method Get -TimeoutSec 2
        if ($response.status) {
            break
        }
    } catch {
        Start-Sleep -Seconds 2
        $retryCount++
    }
}
Write-Host "✅ API is ready" -ForegroundColor Green

# Create demo tenant
Write-Host "📦 Creating demo tenant..."
$headers = @{
    "X-Admin-Key" = $AdminKey
    "Content-Type" = "application/json"
}

try {
    $tenantResponse = Invoke-RestMethod -Uri "$ApiUrl/admin/tenants" -Method Post -Headers $headers -Body (@{
        name = "Demo Tenant"
        description = "Demo tenant for testing"
    } | ConvertTo-Json)
    $tenantId = $tenantResponse.id
} catch {
    Write-Host "⚠️  Tenant might already exist, fetching..."
    $tenants = Invoke-RestMethod -Uri "$ApiUrl/admin/tenants" -Method Get -Headers $headers
    $tenantId = $tenants[0].id
}

Write-Host "✅ Tenant ID: $tenantId" -ForegroundColor Green

# Create API key
Write-Host "🔑 Creating API key..."
try {
    $keyResponse = Invoke-RestMethod -Uri "$ApiUrl/admin/keys" -Method Post -Headers $headers -Body (@{
        tenant_id = $tenantId
        name = "Demo Key"
        quota_daily = 10000
    } | ConvertTo-Json)
    $apiKey = $keyResponse.key
    Write-Host "✅ API Key: $apiKey" -ForegroundColor Green
    Write-Host ""
    Write-Host "⚠️  SAVE THIS KEY - it won't be shown again!" -ForegroundColor Yellow
} catch {
    Write-Host "⚠️  Could not create key, it may already exist" -ForegroundColor Yellow
}

# Create cache policy
Write-Host "📋 Creating cache policy..."
try {
    Invoke-RestMethod -Uri "$ApiUrl/admin/policies" -Method Post -Headers $headers -Body (@{
        name = "default"
        description = "Default cache policy"
        ttl_seconds = 300
        stale_seconds = 60
        cacheable_statuses_json = @(200, 201, 204, 301, 304)
    } | ConvertTo-Json)
    Write-Host "✅ Cache policy created" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Policy might already exist" -ForegroundColor Yellow
}

# Get policy ID
$policies = Invoke-RestMethod -Uri "$ApiUrl/admin/policies" -Method Get -Headers $headers
$policyId = $policies[0].id

# Create demo route
Write-Host "🛤️  Creating demo route..."
try {
    Invoke-RestMethod -Uri "$ApiUrl/admin/routes" -Method Post -Headers $headers -Body (@{
        name = "demo"
        description = "Demo route to example upstream"
        path_pattern = "/*"
        methods = @("GET", "POST", "PUT", "PATCH", "DELETE")
        upstream_base_url = "http://upstream:8001"
        timeout_ms = 30000
        policy_id = $policyId
    } | ConvertTo-Json)
    Write-Host "✅ Demo route created" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Route might already exist" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "🎉 Demo setup complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Gateway URL: $ApiUrl"
Write-Host "Admin UI: http://localhost:3000"
Write-Host "Upstream: http://localhost:8001"
Write-Host ""
Write-Host "Try these commands:"
Write-Host ""
Write-Host "# Cache miss (slow):"
Write-Host "Invoke-RestMethod '$ApiUrl/g/demo/slow?delay=2' -Headers @{'X-API-Key'='YOUR_KEY'}"
Write-Host ""
Write-Host "# List items:"
Write-Host "Invoke-RestMethod '$ApiUrl/g/demo/items' -Headers @{'X-API-Key'='YOUR_KEY'}"
