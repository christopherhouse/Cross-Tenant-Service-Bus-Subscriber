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

param crossTenantServiceBusNamespace = '<tenant-b-servicebus-namespace>.servicebus.windows.net'
param crossTenantTopicName           = '<topic-name>'
param crossTenantSubscriptionName    = '<subscription-name>'
param crossTenantTenantId            = '<tenant-b-entra-tenant-id>'
param crossTenantAppClientId         = '<app-registration-client-id-in-tenant-b>'

// ── Runtime tuning ───────────────────────────────────────────────────────────

param messageContainerName  = 'sb-messages'
param timerSchedule         = '0 */1 * * * *'
param maxMessageBatchSize   = 10
