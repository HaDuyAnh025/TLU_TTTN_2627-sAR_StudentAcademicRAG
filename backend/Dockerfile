FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# INSTALL_ML=false: image nhẹ (~300MB), chỉ chạy được với EMBEDDING_PROVIDER=hash
ARG INSTALL_ML=true

COPY requirements.txt requirements-ml.txt ./
RUN pip install -r requirements.txt \
 && if [ "$INSTALL_ML" = "true" ]; then \
      pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 \
      && pip install -r requirements-ml.txt ; \
    fi

COPY . .

EXPOSE 8000

# Tạo/cập nhật bảng DB rồi chạy API
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
