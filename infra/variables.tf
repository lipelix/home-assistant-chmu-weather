variable "cloudflare_account_id" {
  description = "Cloudflare account that owns the Worker."
  type        = string
}

variable "github_token" {
  description = <<-EOT
    Fine-grained GitHub PAT with "Actions: Read and write" on the forecast
    repository and nothing else. Pass it as TF_VAR_github_token; it is stored
    as a Worker secret, so it never appears in the Worker's source.
  EOT
  type        = string
  sensitive   = true
}

variable "github_repository" {
  description = "owner/repo holding the forecast workflow."
  type        = string
  default     = "lipelix/home-assistant-chmu-weather"
}

variable "github_workflow_file" {
  description = "File name of the workflow to dispatch."
  type        = string
  default     = "forecast-data.yml"
}

variable "github_ref" {
  description = "Branch the dispatched run checks out."
  type        = string
  default     = "main"
}

variable "worker_name" {
  description = "Name of the Worker doing the dispatching."
  type        = string
  default     = "chmu-forecast-scheduler"
}

variable "schedule" {
  description = <<-EOT
    Cron for the dispatch, in UTC. ALADIN publishes four runs a day at an
    irregular three to four and a half hours after 00/06/12/18Z, so the poll is
    what makes the lag small: three times an hour bounds it at twenty minutes.
    A poll with nothing new to publish exits before the download.
  EOT
  type        = string
  default     = "3,23,43 * * * *"
}
