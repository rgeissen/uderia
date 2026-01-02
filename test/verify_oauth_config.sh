#!/bin/bash
# OAuth Credentials Verification Script
# Run this after populating .env to verify all credentials are set

echo "🔐 OAuth Configuration Verification"
echo "===================================="
echo ""

# Load .env file
if [ ! -f .env ]; then
    echo "❌ .env file not found. Create one using:"
    echo "   cp .env.oauth.template .env"
    exit 1
fi

# Check if env file has any values
if ! grep -q "OAUTH_" .env; then
    echo "⚠️  No OAuth configuration found in .env"
    exit 1
fi

echo "Checking OAuth configuration..."
echo ""

# Function to check variable
check_var() {
    local var_name=$1
    local var_value=$(grep "^${var_name}=" .env | cut -d'=' -f2-)
    
    if [ -z "$var_value" ]; then
        echo "❌ $var_name: NOT SET"
        return 1
    elif [ "$var_value" = "False" ] || [ "$var_value" = "True" ] || [ "$var_value" = "" ]; then
        echo "⚠️  $var_name: $var_value (empty or default)"
        return 0
    else
        echo "✅ $var_name: Configured"
        return 0
    fi
}

# Check core settings
echo "Core Settings:"
check_var "OAUTH_HTTPS_ONLY"
check_var "OAUTH_INSECURE_TRANSPORT"
check_var "OAUTH_CALLBACK_URL"
echo ""

# Check provider credentials
echo "Provider Credentials:"
echo "  Google:"
check_var "OAUTH_GOOGLE_CLIENT_ID"
check_var "OAUTH_GOOGLE_CLIENT_SECRET"

echo ""
echo "  GitHub:"
check_var "OAUTH_GITHUB_CLIENT_ID"
check_var "OAUTH_GITHUB_CLIENT_SECRET"

echo ""
echo "  Microsoft:"
check_var "OAUTH_MICROSOFT_CLIENT_ID"
check_var "OAUTH_MICROSOFT_CLIENT_SECRET"

echo ""
echo "  Discord:"
check_var "OAUTH_DISCORD_CLIENT_ID"
check_var "OAUTH_DISCORD_CLIENT_SECRET"

echo ""
echo "  Okta:"
check_var "OKTA_DOMAIN"
check_var "OAUTH_OKTA_CLIENT_ID"
check_var "OAUTH_OKTA_CLIENT_SECRET"

echo ""
echo "===================================="
echo ""
echo "📝 Next Steps:"
echo "1. Fill in any missing credentials in .env"
echo "2. See OAUTH_SETUP_STEPS.md for credential setup"
echo "3. Run: python -m trusted_data_agent"
echo "4. Test: curl http://localhost:8000/api/v1/auth/oauth/providers"
