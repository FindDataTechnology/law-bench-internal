## Purpose

Defines how the law-bench main image is built, published, and delivered to
the cheap cluster: GitHub Actions builds on push, publishes to Tencent TCR
personal edition, and the cluster pulls from TCR while ArgoCD continues to
roll out from the Gitee manifest source.

## ADDED Requirements

### Requirement: Build and publish the main image on push

The system SHALL build the law-bench main image (`Dockerfile` at repo root)
on GitHub Actions whenever a commit is pushed to the default branch, and
whenever a `v*` tag is pushed, and publish it to the Tencent TCR personal
edition registry. The build MUST NOT depend on the GitHub-hosted runner
having access to any China-side mirror: the Dockerfile's default base image
and package indexes apply unchanged.

#### Scenario: Code push to main triggers a published image

- **WHEN** a commit is pushed to the default branch of the GitHub repository
- **THEN** GitHub Actions builds the main image from that commit and pushes
  it to TCR tagged `sha-<7-char-short-sha>` and `latest`

#### Scenario: Tag push publishes a version tag

- **WHEN** a tag matching `v*` is pushed
- **THEN** the built image is also pushed under the tag's ref name

### Requirement: Canonical registry path and tag scheme

The published image SHALL live at `ccr.ccs.tencentyun.com/law-bench/law-template`.
A `sha-<short>` tag SHALL identify exactly the commit it was built from, and
MUST NOT be re-pushed with different content.

#### Scenario: Manifest references resolve to TCR

- **WHEN** a deployment manifest references `ccr.ccs.tencentyun.com/law-bench/law-template:sha-<x>`
- **THEN** that tag exists in TCR and was built from commit `<x>`

### Requirement: Cluster pulls from TCR authenticated

Workloads in namespace `law-bench` that reference `ccr.ccs.tencentyun.com`
images SHALL carry an imagePullSecret (k8s `docker-registry` secret
`tcr-pull`) holding the TCR login credentials, so any cluster node can pull
the image without a pre-imported local containerd copy. The web deployment
and the assistant-MCP deployment SHALL use TCR image references with this
secret.

#### Scenario: First pull on a cold node

- **WHEN** a pod referencing a TCR image is scheduled on a node that has
  never held that image
- **THEN** kubelet pulls it successfully using the `tcr-pull` secret, without
  manifesting `ImagePullBackOff`

### Requirement: Deploy trigger stays the Gitee manifest bump

A production deploy SHALL remain: bump the image tag in the top-level
`deploy/*.yaml` manifests and push to the Gitee repository, which the ArgoCD
`law-bench` application watches. The GitHub repository hosts code and CI but
MUST NOT be an ArgoCD application source (cluster nodes cannot reach
github.com). Pushing code without a manifest tag bump SHALL NOT roll pods.

#### Scenario: Roll by tag bump

- **WHEN** a commit that changes only the image tag in `deploy/deployment.yaml`
  is pushed to Gitee
- **THEN** ArgoCD syncs and the web pod runs the referenced TCR tag

#### Scenario: Code-only push does not roll

- **WHEN** a code commit is pushed without a manifest image-tag change
- **THEN** the running pods keep their current images

### Requirement: Dual-track rollback to Harbor remains available

During the transition period the legacy Jenkins→Harbor path SHALL remain
operational, and Harbor SHALL retain previously built tags. Rolling back a
TCR-based deployment SHALL NOT require rebuilding anything: flip the
manifest image references back to the Harbor path
(`100.64.0.8:30880/law-bench/law-template:sha-<x>`) with a tag that exists
there, and push.

#### Scenario: Rollback by manifest flip

- **WHEN** a TCR-sourced roll misbehaves and the manifest references are
  flipped back to a Harbor tag that already exists
- **THEN** the next ArgoCD sync schedules pods from the Harbor image, with
  no rebuild involved
