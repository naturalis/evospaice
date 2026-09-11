FROM pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    curl \
    wget \
    ca-certificates \
    sudo \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*
    
# Create a non-root user
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=${USER_UID}
RUN groupadd --gid ${USER_GID} ${USERNAME} \
    && useradd --uid ${USER_UID} --gid ${USER_GID} -m ${USERNAME} -s /bin/bash \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} \
    && chmod 0440 /etc/sudoers.d/${USERNAME}

USER ${USERNAME}

ENV PATH="/home/${USERNAME}/.local/bin:${PATH}"

RUN pip install --no-cache-dir azureml-mlflow ai2-olmo datasets 'transformers>=4.40,<5.0'
