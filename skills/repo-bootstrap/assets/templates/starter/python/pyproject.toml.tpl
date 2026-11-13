[build-system]
requires = ["setuptools>=77", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "{{PYTHON_DISTRIBUTION_NAME}}"
version = "0.1.0"
description = "{{PROJECT_DESCRIPTION_EN}}"
readme = "README.md"
requires-python = ">=3.11"
{{PYTHON_LICENSE_LINE}}

[project.optional-dependencies]
dev = ["build>=1", "pytest>=8", "ruff>=0.8"]

[project.scripts]
"{{CLI_COMMAND_NAME}}" = "{{PYTHON_MODULE}}.__main__:main"

[tool.setuptools.packages.find]
where = ["src"]
