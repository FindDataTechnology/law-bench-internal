## ADDED Requirements

### Requirement: Render service image delivery

The render-service image (built from `Dockerfile.render` at repo root) SHALL
be built and published by the same GitHub Actions workflow, on the same
triggers as the main image (push to the default branch, push of a `v*` tag),
to `ccr.ccs.tencentyun.com/law-bench/law-render`, using the same
`sha-<short>` plus `latest` tag scheme. The render-service workload in
namespace `law-bench` SHALL reference the TCR image and pull it with the
`tcr-pull` imagePullSecret.

#### Scenario: Push publishes both application images

- **WHEN** a commit is pushed to the default branch
- **THEN** TCR contains both `law-bench/law-template:sha-<short>` and
  `law-bench/law-render:sha-<short>` built from that commit

#### Scenario: Render pod cold-node pull

- **WHEN** the render-service pod referencing
  `ccr.ccs.tencentyun.com/law-bench/law-render:sha-<x>` is scheduled on a
  node that has never held that image
- **THEN** kubelet pulls it successfully using the `tcr-pull` secret,
  without manifesting `ImagePullBackOff`
