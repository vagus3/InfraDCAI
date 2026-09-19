variable "aws_region" {
  description = "Region to deploy into. ap-northeast-2 (Seoul) keeps latency low from Korea."
  type        = string
  default     = "ap-northeast-2"
}

variable "project_name" {
  description = "Prefix for every resource name, so a stray resource is traceable to this project."
  type        = string
  default     = "mini-chatgpt"
}

variable "instance_type" {
  description = "t3.micro is free-tier eligible on accounts under 12 months. See DECISIONS.md for why not ECS."
  type        = string
  default     = "t3.micro"
}

variable "github_repo" {
  description = "owner/repo -- the only repository allowed to assume the deploy role."
  type        = string
}

# The deploy job declares `environment: production`, which changes the OIDC
# token's subject from the ref form to the environment form. The trust policy
# has to match whichever form the workflow actually produces.
#
# Note what moved: with an environment subject, AWS no longer enforces the
# branch. That restriction now lives in the GitHub Environment's deployment
# branch policy, and it is not optional -- without it, any branch that can run
# a job naming this environment can assume the role.
variable "github_environment" {
  description = "GitHub Environment named by the deploy job. Only it may assume the role."
  type        = string
  default     = "production"
}

variable "openai_model" {
  description = "Model used by the deployed app."
  type        = string
  default     = "gpt-4o-mini"
}
