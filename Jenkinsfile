// Jenkins CI for law-bench: build the web-app image and push it to the
// in-cluster Harbor project `law-bench`.
//
// Runs on the built-in node (the Jenkins pod), which has the host docker CLI +
// socket mounted, so `docker build`/`push` execute against cheap-3's docker
// daemon. That daemon already lists 100.64.0.8:30880 as an insecure registry
// (Harbor is served over plain HTTP) — see deploy/cheap-box/README.md "Harbor".
//
// Image : 100.64.0.8:30880/law-bench/law-template
// Tags  : sha-<short-git>  and  latest
// Cred  : Jenkins credential `harbor-law-bench` (Harbor robot robot$law-bench+ci)
//
// The push is the slow part (blobs land in the S3-backed RustFS registry at low
// throughput); the 60-min timeout below covers it. The image is ~2.3 GB — the
// Dockerfile avoids a ~1.2 GB duplicate chown layer (COPY --chown onto a
// pre-created user) and keeps uv's ~1.2 GB wheel cache out of the image, so the
// largest blob is ~350 MB where it used to be ~720 MB.

pipeline {
  agent any

  options {
    timestamps()
    timeout(time: 60, unit: 'MINUTES')
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '20'))
  }

  environment {
    REGISTRY = '100.64.0.8:30880'
    IMAGE    = '100.64.0.8:30880/law-bench/law-template'
    // ghcr.io's blob CDN is unreachable from the in-cluster builder (metadata
    // resolves, layer downloads stall forever), so the base image is pulled
    // through a mirror. The Dockerfile keeps ghcr.io as its BASE_IMAGE default
    // for other environments. Swap here if the mirror is unavailable.
    BASE_IMAGE_MIRROR = 'ghcr.nju.edu.cn/astral-sh/uv:python3.12-bookworm-slim'
    // Domestic PyPI mirror. Direct pypi.org is unreachable from the builder
    // network (transfers hang or arrive truncated), so uv is pointed here via
    // the Dockerfile's UV_INDEX_URL build arg. Swap if the mirror is down.
    UV_INDEX_URL = 'https://pypi.tuna.tsinghua.edu.cn/simple'
    // Domestic Debian mirrors. deb.debian.org is ~460x slower from the builder
    // (measured 20 KB/s vs 9.6 MB/s) and a stalled fonts-noto-cjk download once
    // burned the entire 60-min timeout, so apt is pointed at tuna via the
    // Dockerfile's DEBIAN_MIRROR / DEBIAN_SECURITY_MIRROR build args.
    DEBIAN_MIRROR          = 'https://mirrors.tuna.tsinghua.edu.cn/debian'
    DEBIAN_SECURITY_MIRROR = 'https://mirrors.tuna.tsinghua.edu.cn/debian-security'
    // Admin-assistant island stage: node base image via a docker-hub mirror and
    // npm via a domestic registry, same builder-network rationale as above.
    // Swap here if a mirror is unavailable.
    NODE_IMAGE_MIRROR = 'docker.m.daocloud.io/library/node:22-slim'
    NPM_REGISTRY      = 'https://registry.npmmirror.com'
  }

  stages {
    stage('Resolve tag') {
      steps {
        script {
          env.GIT_SHA = sh(returnStdout: true, script: 'git rev-parse --short=7 HEAD').trim()
          env.TAG = "sha-${env.GIT_SHA}"
          echo "Building ${env.IMAGE}:${env.TAG}"
        }
      }
    }

    stage('Build') {
      steps {
        sh 'docker build --build-arg BASE_IMAGE="$BASE_IMAGE_MIRROR" --build-arg UV_INDEX_URL="$UV_INDEX_URL" --build-arg DEBIAN_MIRROR="$DEBIAN_MIRROR" --build-arg DEBIAN_SECURITY_MIRROR="$DEBIAN_SECURITY_MIRROR" --build-arg NODE_IMAGE="$NODE_IMAGE_MIRROR" --build-arg NPM_REGISTRY="$NPM_REGISTRY" -t "$IMAGE:$TAG" -t "$IMAGE:latest" -f Dockerfile .'
      }
    }

    stage('Push to Harbor') {
      steps {
        withCredentials([usernamePassword(credentialsId: 'harbor-law-bench',
                                          usernameVariable: 'HARBOR_USER',
                                          passwordVariable: 'HARBOR_PASS')]) {
          sh '''
            set -e
            echo "$HARBOR_PASS" | docker login "$REGISTRY" -u "$HARBOR_USER" --password-stdin
            docker push "$IMAGE:$TAG"
            docker push "$IMAGE:latest"
          '''
        }
      }
    }
  }

  post {
    always {
      sh 'docker logout "$REGISTRY" || true'
      sh '''#!/bin/bash
                imgs=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^100.64.0.8:30880/' || true)
                if [ -n "$imgs" ]; then
                    echo "post-build cleanup: removing local build images:"
                    echo "$imgs"
                    echo "$imgs" | xargs -r docker rmi >/dev/null 2>&1 || true
                fi
                docker container prune -f >/dev/null 2>&1 || true
                docker image prune -f >/dev/null 2>&1 || true
                docker builder prune -a -f --filter until=24h >/dev/null 2>&1 || true
            '''
    }
    success {
      echo "Pushed ${IMAGE}:${TAG}"
    }
  }
}
