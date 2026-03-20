FROM python:3.9-slim

WORKDIR /app

# Install system dependencies needed for geopy/requests/ssl
RUN apt-get update && apt-get install -y \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face Spaces requires running as non-root user
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app
COPY --chown=user . $HOME/app

EXPOSE 7860
ENV PORT=7860

CMD ["sh", "-c", "streamlit run app.py --server.port 7860 --server.address 0.0.0.0"]

