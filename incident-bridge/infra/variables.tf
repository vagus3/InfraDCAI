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

variable "github_branch" {
  description = "Only pushes to this branch may deploy."
  type        = string
  default     = "main"
}

variable "openai_model" {
  description = "Model used by the deployed app."
  type        = string
  default     = "gpt-4o-mini"
}
