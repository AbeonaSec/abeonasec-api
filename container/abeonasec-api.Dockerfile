# using ubuntu container so we can install nvidia server utils for gpu monitoring
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y curl git python3 python3-pip nvidia-utils-535-server iproute2 && rm -rf /var/lib/apt/lists/*

RUN install -m 0755 -d /etc/apt/keyrings &&\
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg &&\
chmod a+r /etc/apt/keyrings/docker.gpg

RUN echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

RUN apt-get update && apt-get install -y docker-ce-cli && rm -rf /var/lib/apt/lists/*

# copy requirements.txt and pip install
COPY container/requirements.txt .
RUN pip install -r requirements.txt --break-system-packages

WORKDIR /app

# copy api files into container
COPY ../route ./route
COPY ../main.py .

# IMPORTANT: comment out the following RUN command for local build
# this is for the github workflow

# find 'host.containers.internal' entries (for elasticsearch client) in codebase 
# and replace them with abeonasec-es01 (container dns name)
RUN find route -type f -exec sed -i 's/host.containers.internal/abeonasec-es01/g' {} +

# run api on container start
CMD ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]
