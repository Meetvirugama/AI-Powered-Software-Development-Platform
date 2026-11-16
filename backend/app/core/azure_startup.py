"""
Azure App Service startup utilities.

Azure health probe configuration note:
  Set 'Health check path' in Azure App Service → Monitoring → Health check to:
  /api/v1/health/live
  
  Without this, Azure load balancer uses GET / which returns 404 and may 
  incorrectly mark instances as unhealthy.
"""
# This module is intentionally a documentation-only module.
# The actual health endpoint is registered in backend/app/api/v1/health.py
AZURE_HEALTH_CHECK_PATH = "/api/v1/health/live"
AZURE_READINESS_CHECK_PATH = "/api/v1/health/ready"
