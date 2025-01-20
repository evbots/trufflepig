import pytest
import os
import subprocess
import json
import uuid
import time
import ctypes

LOG_FILE = "http_requests.log"

# --- Low-level setns() via ctypes ---

libc = ctypes.CDLL("libc.so.6", use_errno=True)
CLONE_NEWNET = 0x40000000  # from bits/sched.h

def setns(fd, nstype):
    """
    Wrapper around the Linux setns(int fd, int nstype) syscall
    to switch this *current* process into the namespace of 'fd'.
    """
    ret = libc.setns(fd, nstype)
    if ret != 0:
        e = ctypes.get_errno()
        raise OSError(e, f"setns failed: {os.strerror(e)}")


# --- Helper Functions ---

def create_netns(name):
    subprocess.run(["sudo", "ip", "netns", "add", name], check=True)

def delete_netns(name):
    subprocess.run(["sudo", "ip", "netns", "delete", name], check=True)

def setup_veth(ns_name, veth0_name, veth1_name, veth0_ip, veth1_ip):
    subprocess.run(["sudo", "ip", "link", "add", veth0_name, 
                    "type", "veth", "peer", "name", veth1_name], check=True)
    subprocess.run(["sudo", "ip", "link", "set", veth1_name, 
                    "netns", ns_name], check=True)
    subprocess.run(["sudo", "ip", "addr", "add", veth0_ip, 
                    "dev", veth0_name], check=True)
    subprocess.run(["sudo", "ip", "netns", "exec", ns_name, 
                    "ip", "addr", "add", veth1_ip, 
                    "dev", veth1_name], check=True)
    subprocess.run(["sudo", "ip", "link", "set", veth0_name, "up"], check=True)
    subprocess.run(["sudo", "ip", "netns", "exec", ns_name, 
                    "ip", "link", "set", veth1_name, "up"], check=True)
    subprocess.run(["sudo", "ip", "netns", "exec", ns_name, 
                    "ip", "link", "set", "lo", "up"], check=True)

def setup_nat(ns_name, veth0_ip, external_interface):
    subprocess.run(["sudo", "sysctl", "-w", "net.ipv4.ip_forward=1"], check=True)
    subprocess.run(["sudo", "ip", "netns", "exec", ns_name, 
                    "ip", "route", "add", "default", "via", veth0_ip], check=True)
    subprocess.run([
        "sudo", "iptables", "-t", "nat", "-A", "POSTROUTING",
        "-s", f"{veth0_ip}/24",
        "-o", external_interface, "-j", "MASQUERADE"
    ], check=True)

def start_tcpdump(ns_name, interface, pcap_file):
    """
    Start tcpdump *from the host namespace* but capturing in ns_name
    by using 'ip netns exec <ns_name>'.

    Alternatively, we could switch *this* Python process to the netns
    first and then spawn tcpdump normally. But using 'ip netns exec'
    is simpler for capturing while we do setns() in Python below.
    """
    cmd = [
        "sudo", "ip", "netns", "exec", ns_name,
        "tcpdump", "-i", interface, "-n", "-U", "-w", pcap_file
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def analyze_pcap(pcap_file, test_name):
    cmd = [
        "tshark", "-r", pcap_file, "-Y", "http.request",
        "-T", "json"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    try:
        http_requests = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Error parsing tshark JSON for {pcap_file}. Output was:\n{result.stdout}")
        return
    
    log_entries = []
    for req in http_requests:
        layers = req["_source"]["layers"]
        ip_src = layers.get("ip", {}).get("ip.src", "")
        ip_dst = layers.get("ip", {}).get("ip.dst", "")
        http_host = layers.get("http", {}).get("http.host", "")
        http_uri = layers.get("http", {}).get("http.request.full_uri", "")
        http_meth = layers.get("http", {}).get("http.request.method", "")
        frame_time = layers.get("frame", {}).get("frame.time", "")

        if ip_src.startswith("192.168.100.") and http_host and http_uri:
            log_entries.append({
                "test_name": test_name,
                "timestamp": frame_time,
                "source_ip": ip_src,
                "destination_ip": ip_dst,
                "http_host": http_host,
                "http_method": http_meth,
                "http_request_uri": http_uri
            })

    if log_entries:
        with open(LOG_FILE, "a") as f:
            for entry in log_entries:
                f.write(json.dumps(entry) + "\n")

# --- The Pytest Fixture ---

@pytest.fixture(scope="function")
def monitor_http_requests(request):
    """
    Creates a new netns for *this* Python process so that the test's
    HTTP traffic actually egresses from 192.168.100.x and can be seen by tcpdump.
    
    Steps:
    1. Create netns, veth pair, NAT
    2. Start tcpdump in that netns
    3. Switch *this* Python process into that netns (setns)
    4. yield => run the actual test inside the netns
    5. Teardown: switch back to old netns, stop tcpdump, analyze pcap, remove netns
    """

    test_name = request.node.name
    random_id = str(uuid.uuid4())[:8]

    # We'll generate unique names for the namespace, veth, pcap, etc.
    ns_name = f"testns-{os.getpid()}-{test_name}-{random_id}".replace("[","_").replace("]","_")
    veth0_name = f"v0-{random_id}"
    veth1_name = f"v1-{random_id}"
    veth0_ip = "192.168.100.1"
    veth1_ip = "192.168.100.2"
    pcap_file = f"{test_name}.pcap"

    # We'll detect the external interface so NAT can route out
    try:
        route_info = subprocess.check_output(["ip", "route", "get", "1.1.1.1"]).decode()
        external_interface = route_info.split()[4]
    except Exception as e:
        pytest.fail(f"Unable to determine external interface: {e}")

    # (A) Create the new netns + veth, NAT
    create_netns(ns_name)
    setup_veth(ns_name, veth0_name, veth1_name, veth0_ip + "/24", veth1_ip + "/24")
    setup_nat(ns_name, veth0_ip, external_interface)

    # (B) Start tcpdump in the new netns (from the host)
    tcpdump_proc = start_tcpdump(ns_name, veth1_name, pcap_file)
    time.sleep(1)  # small delay to ensure tcpdump is listening

    # (C) Save a reference to the current (old) netns
    #     We'll open /proc/self/ns/net for reading so we can return later.
    old_netns_fd = os.open("/proc/self/ns/net", os.O_RDONLY)

    # (D) Now join the *new* netns in this Python process
    new_ns_path = f"/var/run/netns/{ns_name}"
    # The 'ip netns add' command automatically creates /var/run/netns/<ns_name> 
    # unless your distro stores them elsewhere, adjust accordingly
    with open(new_ns_path, "r") as new_ns:
        setns(new_ns.fileno(), CLONE_NEWNET)

    # At this point, any subsequent code, including your test's requests, 
    # will run in the netns we just set.

    try:
        # (E) yield control to the test — the test now runs inside the netns
        yield ns_name

    finally:
        # (F) Teardown
        # 1. switch back to old netns (so we can remove the new one cleanly)
        setns(old_netns_fd, CLONE_NEWNET)
        os.close(old_netns_fd)

        # 2. Stop tcpdump
        if tcpdump_proc.poll() is None:
            tcpdump_proc.terminate()
            try:
                tcpdump_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tcpdump_proc.kill()

        # 3. Analyze captured traffic
        analyze_pcap(pcap_file, test_name)

        # 4. Cleanup pcap
        if os.path.exists(pcap_file):
            os.remove(pcap_file)

        # 5. Cleanup veth + netns
        subprocess.run(["sudo", "ip", "link", "delete", veth0_name], check=False)
        delete_netns(ns_name)

