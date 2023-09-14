FROM ubuntu:16.04
RUN apt-get update && apt-get -y dist-upgrade && apt-get install -y bash wget git gcc cmake ninja g++ tzdata locales
RUN echo "Asia/Shanghai" > /etc/timezone && dpkg-reconfigure -f noninteractive tzdata &&\
    sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && echo 'LANG="en_US.UTF-8"'>/etc/default/locale && dpkg-reconfigure --frontend=noninteractive locales && \
    update-locale LANG=en_US.UTF-8
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh && bash Miniconda3-latest-Linux-x86_64.sh -b -p /opt/miniconda
ENV PATH /opt/miniconda/bin:$PATH
COPY ./condarc /root/.condarc
RUN conda init && . /root/.bashrc \
    && conda create -n SoftTeacher python=3.6 -y  && conda activate SoftTeacher \
    && conda install pytorch==1.9.0 torchvision torchaudio cudatoolkit=10.2 -c pytorch -y \
    && pip3 install https://pypi.tuna.tsinghua.edu.cn/packages/af/bf/8d189a5c43460f6b5c8eb81ead8732e94b9f73ef8d9abba9e8f5a61a6531/opencv_python-4.6.0.66-cp36-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl#sha256=dbdc84a9b4ea2cbae33861652d25093944b9959279200b7ae0badd32439f74de \
    && git clone https://github.com/microsoft/SoftTeacher && cd SoftTeacher && make install
