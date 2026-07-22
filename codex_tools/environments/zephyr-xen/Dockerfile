# syntax=docker/dockerfile:1.7
#
# Reusable Zephyr/Xen build environment for workspace tasks.
#
# The image intentionally installs the Zephyr SDK and host-side tooling from
# pinned versions so a fresh workspace can recreate the environment without
# relying on a pre-existing local Docker image.

FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG ZEPHYR_SDK_VERSION=1.0.0
ARG ZEPHYR_VERSION=v4.4.1
ARG NINJA_VERSION=1.11.1
ARG USER_NAME=builder
ARG USER_ID=1000
ARG USER_GID=1000

ENV LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    HOME=/home/${USER_NAME} \
    ZEPHYR_SDK_INSTALL_DIR=/opt/zephyr-sdk-${ZEPHYR_SDK_VERSION} \
    ZEPHYR_TOOLCHAIN_VARIANT=zephyr \
    PATH=/opt/zephyr-sdk-${ZEPHYR_SDK_VERSION}/hosttools/sysroots/x86_64-pokysdk-linux/usr/bin:${PATH}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash \
       bash-completion \
       build-essential \
       ca-certificates \
       chrpath \
       clang \
       cmake \
       cpio \
       curl \
       device-tree-compiler \
       diffstat \
       dosfstools \
       file \
       gawk \
       git \
       git-lfs \
       gperf \
       libclang-dev \
       libglib2.0-0 \
       liblz4-tool \
       locales \
       locales-all \
       mtools \
       ninja-build \
       python3 \
       python3-clang \
       python3-pip \
       python3-venv \
       qemu-system-arm \
       qemu-utils \
       unzip \
       wget \
       xz-utils \
       zstd \
    && rm -rf /var/lib/apt/lists/*

RUN locale-gen en_US.UTF-8

RUN curl -fsSL "https://github.com/ninja-build/ninja/releases/download/v${NINJA_VERSION}/ninja-linux.zip" \
        -o /tmp/ninja-linux.zip \
    && unzip -o /tmp/ninja-linux.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/ninja \
    && test "$(ninja --version)" = "${NINJA_VERSION}" \
    && rm -f /tmp/ninja-linux.zip

RUN curl -fsSL "https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v${ZEPHYR_SDK_VERSION}/zephyr-sdk-${ZEPHYR_SDK_VERSION}_linux-x86_64_gnu.tar.xz" \
        -o /tmp/zephyr-sdk.tar.xz \
    && mkdir -p /opt \
    && tar -C /opt -xf /tmp/zephyr-sdk.tar.xz \
    && rm -f /tmp/zephyr-sdk.tar.xz \
    && "${ZEPHYR_SDK_INSTALL_DIR}/setup.sh" -h

RUN pip3 install --break-system-packages --upgrade \
        west \
        pyelftools \
        "git+https://github.com/svlad-90/moulin@main" \
    && curl -fsSL "https://raw.githubusercontent.com/zephyrproject-rtos/zephyr/${ZEPHYR_VERSION}/scripts/requirements-base.txt" \
        -o /tmp/zephyr-requirements-base.txt \
    && pip3 install --break-system-packages --upgrade -r /tmp/zephyr-requirements-base.txt \
    && rm -f /tmp/zephyr-requirements-base.txt

RUN mkdir -p /workspace "/home/${USER_NAME}" \
    && chown -R "${USER_ID}:${USER_GID}" /workspace "/home/${USER_NAME}"

WORKDIR /workspace
USER ${USER_ID}:${USER_GID}

RUN git config --global user.name "Isolated Builder" \
    && git config --global user.email "builder@example.com"

CMD ["/bin/bash"]
