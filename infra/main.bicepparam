/*
  main.bicepparam – parameter values for main.bicep

  Copy this file and supply real values before running a deployment.
  Never commit sensitive values to source control; prefer using
  GitHub Actions secrets and passing them at deployment time.
*/

using './main.bicep'

param environmentName = 'dev'
param workloadName    = 'sbsub'

// ── Cross-tenant Service Bus (Tenant B) ──────────────────────────────────────
// Replace with actual values from your Tenant B environment.

param crossTenantServiceBusNamespace = 'sbns-x-tenant-ingest.servicebus.windows.net'
param crossTenantTopicName           = 'publish'
param crossTenantSubscriptionName    = 'all-messages'
param crossTenantTenantId            = '596c1564-6e95-4c35-a80b-2dbe45a162f3'
param crossTenantAppClientId         = 'c4522b48-1222-4db9-85b6-8252dc9c4825'

// ── Runtime tuning ───────────────────────────────────────────────────────────

param messageContainerName  = 'sbmessages'
param timerSchedule         = '0 */1 * * * *'
param maxMessageBatchSize   = 10
