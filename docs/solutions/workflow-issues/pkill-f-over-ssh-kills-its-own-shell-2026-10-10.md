---
title: pkill -f over ssh kills the ssh command's own bash -c when the pattern is in the command line
date: 2026-10-10
category: workflow-issues
module: robot ssh operations
problem_type: workflow_issue
component: development_workflow
symptoms:
  - "ssh command with pkill -f <pattern> drops the connection with no output"
root_cause: environment
resolution_type: workflow_improvement
severity: medium
tags: [ssh, pkill, shell]
---

# pkill -f over ssh kills its own shell

## Problem

`pkill -f <pattern>` matches the `bash -c '...'` that ssh runs whenever the pattern text appears in the command line, so it kills its own shell.

## Rule

- Use the bracket trick (`[x]yz`) AND keep the literal pattern out of every other argument of the same command line.
- Print a date or nonce before claiming remote state is live.

## Evidence

Project skill `rosy-device-access`.
