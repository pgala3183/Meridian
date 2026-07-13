terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  type        = string
  description = "GCP project id"
}

variable "region" {
  type        = string
  description = "Primary region for Cloud Run / Pub/Sub"
  default     = "us-central1"
}

variable "name_prefix" {
  type        = string
  description = "Resource name prefix"
  default     = "meridian"
}

variable "api_image" {
  type        = string
  description = "Container image for the API Cloud Run service"
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "worker_image" {
  type        = string
  description = "Container image for the worker Cloud Run service"
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "web_image" {
  type        = string
  description = "Container image for the web Cloud Run service"
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "billing_account" {
  type        = string
  description = "Billing account ID for budget alerts (e.g. 01ABCD-...)"
  default     = ""
}

variable "monthly_budget_usd" {
  type        = number
  description = "Monthly GCP budget threshold for the demo stack"
  default     = 50
}

variable "budget_alert_email" {
  type        = string
  description = "Email for billing budget threshold notifications (optional)"
  default     = ""
}

variable "enable_uptime_checks" {
  type        = bool
  description = "Create Cloud Monitoring uptime checks against /health"
  default     = true
}

locals {
  labels = {
    app     = "meridian"
    managed = "terraform"
  }
}

# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------

resource "google_project_service" "services" {
  for_each = toset([
    "run.googleapis.com",
    "pubsub.googleapis.com",
    "storage.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "billingbudgets.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
    "logging.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Service accounts (least privilege — no default compute SA)
# ---------------------------------------------------------------------------

resource "google_service_account" "api" {
  account_id   = "${var.name_prefix}-api"
  display_name = "Meridian API"
}

resource "google_service_account" "worker" {
  account_id   = "${var.name_prefix}-worker"
  display_name = "Meridian video worker"
}

resource "google_service_account" "pubsub_invoker" {
  account_id   = "${var.name_prefix}-pubsub-invoker"
  display_name = "Meridian Pub/Sub push invoker"
}

# ---------------------------------------------------------------------------
# GCS
# ---------------------------------------------------------------------------

resource "google_storage_bucket" "artifacts" {
  name                        = "${var.project_id}-${var.name_prefix}-artifacts"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false
  labels                      = local.labels

  versioning {
    enabled = true
  }

  depends_on = [google_project_service.services]
}

resource "google_storage_bucket_iam_member" "worker_object_admin" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_storage_bucket_iam_member" "api_object_viewer" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.api.email}"
}

# ---------------------------------------------------------------------------
# Firestore (Native mode database)
# ---------------------------------------------------------------------------

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.services]
}

resource "google_project_iam_member" "api_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "worker_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

# Trace + metrics export (OpenTelemetry → Cloud Trace / Monitoring)
resource "google_project_iam_member" "api_cloudtrace" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "worker_cloudtrace" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "api_monitoring_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "worker_monitoring_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "api_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "worker_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

# ---------------------------------------------------------------------------
# Artifact Registry (CI/CD image pushes)
# ---------------------------------------------------------------------------

resource "google_artifact_registry_repository" "meridian" {
  location      = var.region
  repository_id = var.name_prefix
  description   = "Meridian container images (api, worker, web)"
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.services]
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.meridian.repository_id}"
}

# ---------------------------------------------------------------------------
# Secret Manager (placeholders — values set out-of-band)
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret" "openai" {
  secret_id = "openai-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret" "anthropic" {
  secret_id = "anthropic-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret_iam_member" "api_openai" {
  secret_id = google_secret_manager_secret.openai.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

resource "google_secret_manager_secret_iam_member" "worker_openai" {
  secret_id = google_secret_manager_secret.openai.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_secret_manager_secret_iam_member" "api_anthropic" {
  secret_id = google_secret_manager_secret.anthropic.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

resource "google_secret_manager_secret_iam_member" "worker_anthropic" {
  secret_id = google_secret_manager_secret.anthropic.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}

# ---------------------------------------------------------------------------
# Pub/Sub
# ---------------------------------------------------------------------------

resource "google_pubsub_topic" "video_jobs" {
  name = "${var.name_prefix}-video-jobs"
  labels = local.labels
  depends_on = [google_project_service.services]
}

resource "google_pubsub_topic" "video_jobs_dlq" {
  name = "${var.name_prefix}-video-jobs-dlq"
  labels = local.labels
}

resource "google_pubsub_topic_iam_member" "api_publisher" {
  topic  = google_pubsub_topic.video_jobs.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.api.email}"
}

# ---------------------------------------------------------------------------
# Cloud Run — API
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "api" {
  name     = "${var.name_prefix}-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.api.email
    scaling {
      min_instance_count = 0
      max_instance_count = 10
    }
    containers {
      image = var.api_image
      ports {
        container_port = 8080
      }
      env {
        name  = "MERIDIAN_ENV"
        value = "production"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "MERIDIAN_JOB_STORE"
        value = "firestore"
      }
      env {
        name  = "MERIDIAN_STORAGE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "MERIDIAN_GCS_BUCKET"
        value = google_storage_bucket.artifacts.name
      }
      env {
        name  = "MERIDIAN_PUBSUB_TOPIC"
        value = google_pubsub_topic.video_jobs.id
      }
      env {
        name  = "MERIDIAN_OTEL_ENABLED"
        value = "true"
      }
      env {
        name  = "MERIDIAN_LOG_FORMAT"
        value = "json"
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ---------------------------------------------------------------------------
# Cloud Run — Worker
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "worker" {
  name     = "${var.name_prefix}-worker"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.worker.email
    scaling {
      min_instance_count = 0
      max_instance_count = 20
    }
    containers {
      image = var.worker_image
      ports {
        container_port = 8080
      }
      env {
        name  = "MERIDIAN_ENV"
        value = "production"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "MERIDIAN_JOB_STORE"
        value = "firestore"
      }
      env {
        name  = "MERIDIAN_STORAGE_BACKEND"
        value = "gcs"
      }
      env {
        name  = "MERIDIAN_GCS_BUCKET"
        value = google_storage_bucket.artifacts.name
      }
      env {
        name  = "MERIDIAN_OTEL_ENABLED"
        value = "true"
      }
      env {
        name  = "MERIDIAN_LOG_FORMAT"
        value = "json"
      }
      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }
    }
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_run_v2_service_iam_member" "worker_pubsub_invoker" {
  name     = google_cloud_run_v2_service.worker.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pubsub_invoker.email}"
}

resource "google_pubsub_subscription" "video_worker_push" {
  name  = "${var.name_prefix}-video-worker-push"
  topic = google_pubsub_topic.video_jobs.name

  ack_deadline_seconds = 60

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.worker.uri}/pubsub/push"
    oidc_token {
      service_account_email = google_service_account.pubsub_invoker.email
    }
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.video_jobs_dlq.id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  depends_on = [
    google_cloud_run_v2_service_iam_member.worker_pubsub_invoker,
  ]
}

resource "google_pubsub_subscription_iam_member" "worker_subscriber" {
  subscription = google_pubsub_subscription.video_worker_push.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.worker.email}"
}

# Allow Pub/Sub service agent to publish to DLQ (required for dead lettering)
data "google_project" "current" {
  project_id = var.project_id
}

resource "google_pubsub_topic_iam_member" "pubsub_dlq_publisher" {
  topic  = google_pubsub_topic.video_jobs_dlq.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "api_uri" {
  value = google_cloud_run_v2_service.api.uri
}

output "worker_uri" {
  value = google_cloud_run_v2_service.worker.uri
}

output "artifacts_bucket" {
  value = google_storage_bucket.artifacts.name
}

output "pubsub_topic" {
  value = google_pubsub_topic.video_jobs.id
}

output "api_service_account" {
  value = google_service_account.api.email
}

output "worker_service_account" {
  value = google_service_account.worker.email
}

# ---------------------------------------------------------------------------
# Web (Next.js demo) + billing budget alert
# ---------------------------------------------------------------------------

resource "google_service_account" "web" {
  account_id   = "${var.name_prefix}-web"
  display_name = "Meridian web demo"
}

resource "google_cloud_run_v2_service" "web" {
  name     = "${var.name_prefix}-web"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.web.email
    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }
    containers {
      image = var.web_image
      ports {
        container_port = 8080
      }
      env {
        name  = "NODE_ENV"
        value = "production"
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_run_v2_service_iam_member" "web_public" {
  name     = google_cloud_run_v2_service.web.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_monitoring_notification_channel" "budget_email" {
  count        = var.budget_alert_email == "" ? 0 : 1
  display_name = "${var.name_prefix}-budget-email"
  type         = "email"
  labels = {
    email_address = var.budget_alert_email
  }
  depends_on = [google_project_service.services]
}

resource "google_billing_budget" "meridian_demo" {
  count = var.billing_account == "" ? 0 : 1

  billing_account = var.billing_account
  display_name    = "${var.name_prefix}-monthly-cap"

  budget_filter {
    projects = ["projects/${data.google_project.current.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(floor(var.monthly_budget_usd))
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }

  dynamic "all_updates_rule" {
    for_each = length(google_monitoring_notification_channel.budget_email) > 0 ? [1] : []
    content {
      monitoring_notification_channels = [
        google_monitoring_notification_channel.budget_email[0].id,
      ]
      disable_default_iam_recipients = false
    }
  }
}

# ---------------------------------------------------------------------------
# Uptime checks (API + web /health)
# ---------------------------------------------------------------------------

locals {
  api_host = trimprefix(google_cloud_run_v2_service.api.uri, "https://")
  web_host = trimprefix(google_cloud_run_v2_service.web.uri, "https://")
}

resource "google_monitoring_uptime_check_config" "api_health" {
  count        = var.enable_uptime_checks ? 1 : 0
  display_name = "${var.name_prefix}-api-health"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = local.api_host
    }
  }

  depends_on = [google_project_service.services]
}

resource "google_monitoring_uptime_check_config" "web_health" {
  count        = var.enable_uptime_checks ? 1 : 0
  display_name = "${var.name_prefix}-web-health"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = local.web_host
    }
  }

  depends_on = [google_project_service.services]
}

output "web_uri" {
  value = google_cloud_run_v2_service.web.uri
}

output "uptime_check_api" {
  value = var.enable_uptime_checks ? google_monitoring_uptime_check_config.api_health[0].name : null
}
