## 1. Repo sync + transfer to FindDataTechnology org

- [x] 1.1 Fast-forward local main to `origin/main` (absorb Gitee-only commit `41bb8f7`)
- [x] 1.2 Push main to the `github` remote so the mirror is current before transfer
- [x] 1.3 Transfer the repo: `gh api -X POST repos/law-ai-official/law-bench/transfer -f new_owner=FindDataTechnology`, then verify `gh repo view FindDataTechnology/law-bench`
- [x] 1.4 Re-point local remote: `git remote set-url github https://github.com/FindDataTechnology/law-bench.git`; set `git config --global http.https://github.com.proxy http://127.0.0.1:7890`; verify a `git fetch github` succeeds

## 2. GitHub Actions → TCR workflow

- [ ] 2.1 Set repo secrets `TCR_USER` (`100035884308`) and `TCR_PASS` on `FindDataTechnology/law-bench` (`gh secret set`)
- [ ] 2.2 Rewrite `.github/workflows/build-and-push.yml`: constant image `ccr.ccs.tencentyun.com/law-bench/law-template`, drop insecure-registry steps and CN-mirror build args, keep metadata tag scheme + GHA cache, add `concurrency` group, update header comment (secrets doc)
- [ ] 2.3 Commit + push to GitHub, trigger `workflow_dispatch`, watch the run to green
- [ ] 2.4 Verify the published tag: TCR console shows `sha-<short>` (+ `latest`), or `docker manifest inspect ccr.ccs.tencentyun.com/law-bench/law-template:<tag>` from a cheap box with the creds

## 3. Cluster pull path

- [ ] 3.1 Create the pull secret from a cluster box with working kubectl (cheap-6, or cheap-4 with `KUBECONFIG=/root/.kube/config-cheap13`): `kubectl -n law-bench create secret docker-registry tcr-pull --docker-server=ccr.ccs.tencentyun.com --docker-username=100035884308 --docker-password=<TCR_PASS>`
- [ ] 3.2 Pull probe: `kubectl -n law-bench run tcr-pull-test --restart=Never --image=ccr.ccs.tencentyun.com/law-bench/law-template:<tag-from-2.4>` → pod reaches `Running`/`CrashLoopBackOff` (image pulled, entrypoint may exit — that is fine) and NOT `ImagePullBackOff`; then `kubectl delete pod tcr-pull-test`

## 4. Manifest flip + roll (content-identical first roll)

- [ ] 4.1 `deploy/deployment.yaml`: both container images → `ccr.ccs.tencentyun.com/law-bench/law-template:sha-db5ed10`; add `imagePullSecrets: [name: tcr-pull]`; keep `nodeSelector`
- [ ] 4.2 `deploy/assistant-mcp-deployment.yaml`: same image ref switch + `imagePullSecrets`
- [ ] 4.3 Commit, push to Gitee `origin`; force ArgoCD refresh (`kubectl -n argocd annotate application law-bench argocd.argoproj.io/refresh=normal --overwrite`); watch both deployments roll to Ready
- [ ] 4.4 Smoke: `scripts/smoke_prod.sh https://lawbench.finddatatech.cloud` (13 checks) + MCP endpoint sanity (`lawbench-mcp` 401-when-anonymous)
- [ ] 4.5 Also push the manifest commit to the `github` remote (mirror stays in sync)

## 5. Docs

- [ ] 5.1 `deploy/cheap-box/README.md`: rewrite the "Image delivery" material — new flow diagram (push GitHub → Actions → TCR; bump tag → push Gitee → ArgoCD), the pull secret, the rollback-by-flip procedure, TCR tag-cleanup note, and the Jenkins/Harbor dual-track status
- [ ] 5.2 `AGENTS.md` ops section: note the new image flow + "push both remotes" habit and that cluster↔github is unreachable (ArgoCD must stay on Gitee)
- [ ] 5.3 `openspec validate --change switch-image-pipeline-github-actions-tcr` passes
