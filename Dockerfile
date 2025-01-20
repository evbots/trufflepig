# Use a base image with necessary tools
FROM debian:bullseye-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y debconf-utils && \
    echo 'wireshark-common wireshark-common/install-setuid boolean true' | debconf-set-selections && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    iproute2 \
    tcpdump \
    tshark \
    sudo \
    python3 \
    python3-pip

# Set working directory
WORKDIR /app

# Copy the project files
COPY . .

# Upgrade pip and setuptools
RUN pip3 install --upgrade pip setuptools

# Install the package and test dependencies
# (This will now use the mounted volume)
RUN pip3 install -e ".[test]"

# Modify sudoers file to include the path to sysctl
RUN echo "Defaults    secure_path = /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/sbin" >> /etc/sudoers

# Command to run the tests (using sudo)
# CMD ["sudo", "-E", "pytest", "-v"]
CMD ["tail", "-f", "/dev/null"]