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
// Note the push is slow (~1.4 MiB/s to the S3-backed registry): a full image
// takes ~15 min. The generous timeout below accounts for that.

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
        sh 'docker build --build-arg BASE_IMAGE="$BASE_IMAGE_MIRROR" --build-arg UV_INDEX_URL="$UV_INDEX_URL" -t "$IMAGE:$TAG" -t "$IMAGE:latest" -f Dockerfile .'
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
    }
    success {
      echo "Pushed ${IMAGE}:${TAG}"
    }
  }
}
