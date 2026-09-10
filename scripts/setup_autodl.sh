#!/usr/bin/env bash
# ============================================================
# AutoDL 实例环境一键搭建(通用模板,后续所有实验复用)
#
# 目标组合:
#   镜像:PyTorch 2.5.1 / Python 3.12 / Ubuntu 22.04 / CUDA 12.4
#   vLLM:0.7.3(官方对应 PyTorch 2.5.1,与镜像严丝合缝)
#
# 为什么要钉版本:
#   vLLM 按 PyTorch 小版本编译,且 pip 默认会为了满足新版 vLLM
#   而静默升级 torch。0.9.x 要 torch 2.7.0 / cu128,装到
#   torch 2.5.1 / cu124 的镜像上必然错配报错。
#   本脚本用 constraints 把 torch 钉死:vLLM 若要求更高 torch,
#   pip 会明确报错,而不是悄悄换掉 torch。
#
# 用法:
#   bash scripts/setup_autodl.sh                    # 装依赖 + 验 GPU
#   SKIP_GPU_CHECK=1 bash scripts/setup_autodl.sh   # 无卡模式(只装不验)
#   VLLM_VERSION=0.8.5 bash scripts/setup_autodl.sh # 换版本(需镜像 torch 2.6.0)
# ============================================================
set -euo pipefail

VLLM_VERSION="${VLLM_VERSION:-0.7.3}"
SKIP_GPU_CHECK="${SKIP_GPU_CHECK:-0}"
TORCH_VERSION="${TORCH_VERSION:-2.5.1}"

echo "=== [1/5] 环境变量 ==="
export HF_HOME="${HF_HOME:-/root/autodl-tmp/hf-cache}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
mkdir -p "$HF_HOME"
source /etc/network_turbo 2>/dev/null || true
echo "HF_HOME=$HF_HOME"
echo "HF_ENDPOINT=$HF_ENDPOINT"

echo "=== [2/5] 安装前基线快照 ==="
python - <<'PY'
try:
    import torch
    print("BEFORE torch:", torch.__version__, "| cuda:", torch.version.cuda)
except Exception as exc:
    print("BEFORE torch: 未安装 ->", exc)
PY

echo "=== [3/5] 锁版本安装(关键步骤) ==="
CONSTRAINTS="$(mktemp)"
cat > "$CONSTRAINTS" <<EOF
torch==${TORCH_VERSION}
torchvision==0.20.1
torchaudio==${TORCH_VERSION}
EOF
echo "--- constraints ---"; cat "$CONSTRAINTS"; echo "-------------------"

pip install --no-cache-dir \
  "vllm==${VLLM_VERSION}" \
  transformers datasets sentence-transformers \
  -c "$CONSTRAINTS"

echo "=== [4/5] 版本验证 ==="
python - <<'PY'
import importlib
for name in ("torch", "vllm", "transformers", "datasets", "sentence_transformers"):
    try:
        mod = importlib.import_module(name)
        print(f"OK   {name:<22} {getattr(mod, '__version__', '?')}")
    except Exception as exc:
        print(f"FAIL {name:<22} {type(exc).__name__}: {exc}")
import torch
print("torch.version.cuda =", torch.version.cuda)
PY

if [ "$SKIP_GPU_CHECK" = "0" ]; then
  python - <<'PY'
import sys
import torch
ok = torch.cuda.is_available()
print("torch.cuda.is_available() =", ok)
if not ok:
    print("GPU 不可用:检查驱动/是否无卡模式开机")
    sys.exit(1)
print("GPU:", torch.cuda.get_device_name(0))
PY
else
  echo "(SKIP_GPU_CHECK=1:跳过 GPU 验证。无卡模式下 cuda.is_available() 为 False 属正常)"
fi

echo "=== [5/5] 依赖一致性 ==="
pip check || echo "!! pip check 有告警,人工确认是否影响 vLLM 加载"

echo
echo "===== 完成 ====="
echo "每个新 SSH 会话都要重设这两个变量(或写进 ~/.bashrc):"
echo "  export HF_HOME=$HF_HOME"
echo "  export HF_ENDPOINT=$HF_ENDPOINT"
