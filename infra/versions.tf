terraform {
  required_version = ">= 1.7"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

# CLOUDFLARE_API_TOKEN is read from the environment; it is never written here.
# The token needs "Workers Scripts: Edit" on the account below, nothing more.
provider "cloudflare" {}
