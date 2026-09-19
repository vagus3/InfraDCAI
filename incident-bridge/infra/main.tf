terraform {
  required_version = ">= 1.5"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.40" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_vpc" "default" { default = true }

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Resolving the AMI through SSM means a rebuild picks up the current patched
# image instead of a hardcoded id that silently rots.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
}

# ---------------------------------------------------------------------------
# Container registry
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "app" {
  name                 = var.project_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Untagged and old images cost money for nothing. Ten is enough history to
# roll back a bad deploy a few times.
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep only the 10 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

# Allocated before the instance so user-data can bake the final hostname into
# the Caddy config -- Caddy needs to know its own domain to request a cert.
resource "aws_eip" "app" {
  domain = "vpc"
  tags   = { Name = "${var.project_name}-eip" }
}

resource "aws_security_group" "app" {
  name        = "${var.project_name}-sg"
  description = "Public HTTP/HTTPS only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP (redirects to HTTPS, and serves the ACME challenge)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # No port 22. Shell access goes through SSM Session Manager, which means
  # no key material to leak and every session is logged in CloudTrail.
  egress {
    description = "Outbound to ECR, SSM, and the model API"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---------------------------------------------------------------------------
# Secrets
#
# Terraform creates the parameters but never holds the real values: anything
# passed through Terraform lands in the state file in plaintext. Real values
# are set once with the AWS CLI (see README) and ignored on later applies.
# ---------------------------------------------------------------------------

locals {
  ssm_prefix = "/${var.project_name}"
}

resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "aws_ssm_parameter" "postgres_password" {
  name  = "${local.ssm_prefix}/postgres_password"
  type  = "SecureString"
  value = random_password.postgres.result
}

resource "aws_ssm_parameter" "jwt_secret_key" {
  name  = "${local.ssm_prefix}/jwt_secret_key"
  type  = "SecureString"
  value = "set-me-with-the-aws-cli"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "openai_api_key" {
  name  = "${local.ssm_prefix}/openai_api_key"
  type  = "SecureString"
  value = "set-me-with-the-aws-cli"

  lifecycle {
    ignore_changes = [value]
  }
}

# ---------------------------------------------------------------------------
# Instance role
# ---------------------------------------------------------------------------

resource "aws_iam_role" "ec2" {
  name = "${var.project_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "ecr_read" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# Scoped to this project's parameters only -- the instance has no reason to
# read anything else in the account's parameter store.
resource "aws_iam_role_policy" "read_secrets" {
  name = "${var.project_name}-read-secrets"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
      Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_prefix}/*"
    }]
  })
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.project_name}-instance-profile"
  role = aws_iam_role.ec2.name
}

# ---------------------------------------------------------------------------
# Instance
# ---------------------------------------------------------------------------

locals {
  # nip.io resolves <ip>.nip.io to <ip>, which gives us a real hostname that
  # Let's Encrypt will issue a certificate for -- no domain purchase needed.
  site_address = "${replace(aws_eip.app.public_ip, ".", "-")}.nip.io"
}

resource "aws_instance" "app" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only -- blocks the SSRF-to-credentials path
  }

  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    aws_region     = var.aws_region
    ecr_repo_url   = aws_ecr_repository.app.repository_url
    ecr_registry   = split("/", aws_ecr_repository.app.repository_url)[0]
    ssm_prefix     = local.ssm_prefix
    site_address   = local.site_address
    openai_model   = var.openai_model
  })

  # Re-running user-data means recreating the instance, which is exactly what
  # you want when the compose file or proxy config changes.
  user_data_replace_on_change = true

  tags = { Name = "${var.project_name}-app" }
}

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}
