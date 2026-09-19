output "site_url" {
  description = "Open this once the first deploy finishes."
  value       = "https://${local.site_address}"
}

output "public_ip" {
  value = aws_eip.app.public_ip
}

output "instance_id" {
  description = "Set as the INSTANCE_ID GitHub Actions variable."
  value       = aws_instance.app.id
}

output "ecr_repository_url" {
  description = "Set as the ECR_REPOSITORY GitHub Actions variable."
  value       = aws_ecr_repository.app.repository_url
}

output "github_actions_role_arn" {
  description = "Set as the AWS_ROLE_ARN GitHub Actions variable."
  value       = aws_iam_role.github_actions.arn
}

output "set_secrets_commands" {
  description = "Run these once to put the real secret values in place."
  value       = <<-EOT
    aws ssm put-parameter --region ${var.aws_region} --overwrite \
      --name ${local.ssm_prefix}/jwt_secret_key --type SecureString \
      --value "$(openssl rand -hex 32)"

    aws ssm put-parameter --region ${var.aws_region} --overwrite \
      --name ${local.ssm_prefix}/openai_api_key --type SecureString \
      --value "sk-your-key-here"
  EOT
}

output "shell_access" {
  description = "There is no SSH port. Use Session Manager."
  value       = "aws ssm start-session --region ${var.aws_region} --target ${aws_instance.app.id}"
}
