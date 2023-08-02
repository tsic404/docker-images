FROM ubuntu:22.04
RUN apt-get update && apt-get install -y locales tzdata && \
    locale-gen en_US en_US.UTF-8 && \
    update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 && \
    export LANG=en_US.UTF-8 && \
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && echo "Asia/Shanghai" >> /etc/timezone  && \
    apt-get install -y software-properties-common && \
    add-apt-repository universe && \
    apt-get install curl -y && \
    curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | tee /etc/apt/sources.list.d/ros2.list > /dev/null && \
    apt-get update && apt-get upgrade -y && \
    apt-get install -y ros-humble-desktop && \
    apt-get install -y ros-humble-ros-base && \
    apt-get install -y ros-dev-tools && \
    apt-get clean && apt-get autoclean && rm -rf /var/lib/apt/lists/*

CMD ["source /opt/ros/humble/setup.bash", "bash"]
