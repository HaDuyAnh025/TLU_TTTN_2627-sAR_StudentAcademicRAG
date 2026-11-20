#!/usr/bin/env bash
# Cai moi truong tren may thue Ubuntu (chay trong thu muc goc du an, nen chay bang nohup):
#   nohup bash deploy/setup_ubuntu.sh > /root/setup.log 2>&1 &
set -e

echo "== GPU =="
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv || echo "KHONG thay nvidia-smi: kiem tra driver GPU"

echo "== Goi he thong =="
if [ "$(id -u)" = "0" ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq unzip python3-venv python3-pip
fi

echo "== Python =="
python3 --version
python3 -m venv --system-site-packages .venv    # giu lai PyTorch co san trong image neu co
source .venv/bin/activate
pip install -q --upgrade pip

echo "== PyTorch =="
if python -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
  echo "PyTorch + CUDA da co san: $(python -c 'import torch; print(torch.__version__, torch.version.cuda)')"
else
  echo "Cai PyTorch (ban mac dinh kem CUDA)"
  pip install torch torchvision
fi

echo "== Thu vien du an =="
pip install -r deploy/requirements-gpu.txt
pip install --no-deps vietocr==0.3.13        # tranh keo phien ban torch/numpy cu

echo "== Kiem tra nhanh =="
python -c "import torch, pymupdf, rapidocr, vietocr; print('torch', torch.__version__, '| cuda', torch.cuda.is_available(), '| GPU', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')"
echo "XONG. Kich hoat lai sau nay bang: source .venv/bin/activate"
