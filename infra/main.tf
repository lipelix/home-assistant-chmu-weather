# The clock for the forecast publishing workflow.
#
# GitHub delays scheduled workflow runs under load and drops them when the load
# is high enough; measured on this repository it delivered about one firing
# every four hours no matter what the cron said, which left a fresh ALADIN run
# unpublished for hours. Cloudflare's cron triggers are punctual, so the
# schedule lives here and the workflow itself keeps only workflow_dispatch.

resource "cloudflare_workers_script" "forecast_scheduler" {
  account_id  = var.cloudflare_account_id
  script_name = var.worker_name

  content     = file("${path.module}/worker.js")
  main_module = "worker.js"

  # Pinned rather than "today": a compatibility date that moves on its own can
  # change runtime behaviour under a Worker nobody is watching.
  compatibility_date = "2026-09-18"

  bindings = [
    {
      name = "GITHUB_TOKEN"
      type = "secret_text"
      text = var.github_token
    },
    {
      name = "GITHUB_REPOSITORY"
      type = "plain_text"
      text = var.github_repository
    },
    {
      name = "GITHUB_WORKFLOW_FILE"
      type = "plain_text"
      text = var.github_workflow_file
    },
    {
      name = "GITHUB_REF"
      type = "plain_text"
      text = var.github_ref
    },
  ]

  observability = {
    enabled = true
  }
}

resource "cloudflare_workers_cron_trigger" "forecast_scheduler" {
  account_id  = var.cloudflare_account_id
  script_name = cloudflare_workers_script.forecast_scheduler.script_name

  schedules = [
    {
      cron = var.schedule
    },
  ]
}
