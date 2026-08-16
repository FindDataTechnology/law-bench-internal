import os, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(override=True)
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")
import litellm, requests

base = os.environ.get("OPENAI_API_BASE", "")
key = os.environ.get("OPENAI_API_KEY", "")
print(f"base={base}  key_set={bool(key)}  key_len={len(key)}")

# 1) query /v1/models (IP server -> direct, no proxy)
print("\n=== /v1/models ===")
try:
    r = requests.get(base.rstrip("/").replace("/v1","") + "/v1/models",
                     headers={"Authorization": f"Bearer {key}"}, timeout=15)
    data = r.json()
    ids = sorted([m.get("id") for m in data.get("data", [])])
    print(f"status={r.status_code}  n_models={len(ids)}")
    # filter to interesting families
    for fam in ("deepseek","qwen","kimi","glm","gpt"):
        hits = [m for m in ids if fam in m.lower()]
        if hits: print(f"  {fam}: {hits}")
except Exception as e:
    print(f"  FAIL: {e}")

# 2) tiny completion per candidate
print("\n=== completion probe ===")
for m in ["openai/kimi-k3","openai/glm-5.2","openai/deepseek-v3",
          "openai/deepseek-v4-pro","openai/deepseek-v4-flash","openai/qwen-3.7-plus"]:
    try:
        r = litellm.completion(model=m, messages=[{"role":"user","content":"回复OK"}], max_tokens=10)
        print(f"  {m}: OK -> {(r.choices[0].message.content or '').strip()!r}")
    except Exception as e:
        s = str(e)
        head = s.splitlines()[0][:140] if s else repr(e)
        print(f"  {m}: FAIL -> {head}")
