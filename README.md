# TrufflePig

This is a pytest plugin called TrufflePig. When using this plugin, you'll be able to detect hidden HTTP requests that your tests are making to the public internet. This is helpful if you're not sure how many dependencies are run in your code under test.

Any detected http requests are printed out to a `truffles.log` file in your project's directory, where each line includes the name of the test where the HTTP request was detected.

This package leverages network namespaces, a Linux feature. That means you won't be able to run this natively on MacOS, since that feature does not exist on MacOS.

### Install

`trufflepig = { git = "https://github.com/evbots/trufflepig.git", rev="<commit hash here>" }`

The linux environment where you run the tests must have the following package available. See the install commands below for additional context.

```bash
# Install system dependencies
apt-get update && \
apt-get install -y debconf-utils && \
echo 'wireshark-common wireshark-common/install-setuid boolean true' | debconf-set-selections && \
DEBIAN_FRONTEND=noninteractive apt-get install -y \
iproute2 \
tcpdump \
tshark \
sudo \
python3 \
python3-pip \
procps \
iptables
```

### Use

`pytest [other arguments] --truffle-hunt`


### Commands for testing

```
docker build -t trufflepig .
docker run --rm --privileged -d -v $(pwd):/app --name trufflepig-container trufflepig
docker ps
docker exec trufflepig-container sudo -E pytest -vvv --truffle-hunt
docker exec -it trufflepig-container /bin/sh
```
