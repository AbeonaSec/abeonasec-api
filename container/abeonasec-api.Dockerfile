# using python 3.12 container
FROM python:3.12
RUN add-apt-repository ppa:graphics-drivers &&\
  apt-get update && apt-get install -y curl nvidia-utils-535-server && rm -rf /var/lib/apt/lists/*

# copy requirements.txt and pip install
COPY container/requirements.txt .
RUN pip install -r requirements.txt

WORKDIR /app

# copy api files into container
COPY ../route ./route
COPY ../main.py .

# IMPORTANT: comment out the following RUN command for local build
# this is for the github workflow

# find 'host.containers.internal' entries (for elasticsearch client) in codebase 
# and replace them with abeonasec-es01 (podman dns name)
RUN find route -type f -exec sed -i 's/host.containers.internal/abeonasec-es01/g' {} +

# run api on container start
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
