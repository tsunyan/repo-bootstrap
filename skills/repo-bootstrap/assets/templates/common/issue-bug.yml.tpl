name: "{{BUG_REPORT_NAME}}"
description: "{{BUG_REPORT_DESCRIPTION}}"
title: "[Bug] "
body:
  - type: textarea
    id: problem
    attributes:
      label: "{{BUG_REPORT_PROBLEM_LABEL}}"
      description: "{{BUG_REPORT_PROBLEM_HELP}}"
    validations:
      required: true
  - type: textarea
    id: reproduce
    attributes:
      label: "{{BUG_REPORT_STEPS_LABEL}}"
      description: "{{BUG_REPORT_STEPS_HELP}}"
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: "{{BUG_REPORT_EXPECTED_LABEL}}"
    validations:
      required: true
  - type: input
    id: version
    attributes:
      label: "{{BUG_REPORT_VERSION_LABEL}}"
  - type: markdown
    attributes:
      value: "{{BUG_REPORT_SECURITY_NOTICE}}"
