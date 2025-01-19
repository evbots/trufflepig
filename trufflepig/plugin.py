import pytest
import os
import subprocess
import time
import atexit
import signal
import json

LOG_FILE = "http_requests.log"

# --- Helper Functions ---

def get_current_netns():
    """Gets the name of the current network namespace."""
    with open("/proc/self/ns/net", "r") as f:
        return os.readlink(f.fileno())

def create_netns(name):
    """Creates a new network namespace."""
    subprocess.run(["sudo", "ip", "netns", "add", name], check=True)
    

def delete_netns(name):
    """Deletes a network namespace."""
    subprocess.run(["sudo", "ip", "netns", "delete", name], check=True)

def setup_veth(ns_name, veth0_name, veth1_name, veth0_ip, veth1_ip):
    """Sets up veth pair to connect network namespace to the main namespace."""
    # Create veth pair
    subprocess.run(["sudo", "ip", "link", "add", veth0_name, "type", "veth", "peer", "name", veth1_name], check=True)
    # Move veth1 to the new namespace
    subprocess.run(["sudo", "ip", "link", "set", veth1_name, "netns", ns_name], check=True)
    # Configure IPs
    subprocess.run(["sudo", "ip", "addr", "add", veth0_ip, "dev", veth0_name], check=True)
    subprocess.run(["sudo", "ip", "netns", "exec", ns_name, "ip", "addr", "add", veth1_ip, "dev", veth1_name], check=True)
    # Bring interfaces up
    subprocess.run(["sudo", "ip", "link", "set", veth0_name, "up"], check=True)
    subprocess.run(["sudo", "ip", "netns", "exec", ns_name, "ip", "link", "set", veth1_name, "up"], check=True)
    subprocess.run(["sudo", "ip", "netns", "exec", ns_name, "ip", "link", "set", "lo", "up"], check=True)

def setup_nat(ns_name, veth0_ip, external_interface):
    """Sets up NAT for the network namespace to access the internet."""
    # Enable IP forwarding
    subprocess.run(["sudo", "sysctl", "-w", "net.ipv4.ip_forward=1"], check=True)
    # Add default route in the namespace
    subprocess.run(["sudo", "ip", "netns", "exec", ns_name, "ip", "route", "add", "default", "via", veth0_ip], check=True)
    # Configure NAT
    subprocess.run([
        "sudo", "iptables", "-t", "nat", "-A", "POSTROUTING",
        "-s", veth0_ip, "-o", external_interface, "-j", "MASQUERADE"
    ], check=True)

def start_tcpdump(ns_name, interface, pcap_file):
    """Starts tcpdump in the specified network namespace to capture traffic."""

    cmd = [
        "sudo", "ip", "netns", "exec", ns_name,
        "tcpdump", "-i", interface, "-n", "-U", "-w", pcap_file
    ]

    process = subprocess.Popen(cmd, 
                               stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE)

    return process

def analyze_pcap(pcap_file, test_name):
    """Analyzes the pcap file for HTTP requests and logs them."""
    cmd = [
        "tshark", "-r", pcap_file, "-Y", "http.request", 
        "-T", "json"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    try:
        http_requests = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Error decoding JSON from tshark output for {pcap_file}. Output: {result.stdout}")
        return
    
    
    log_entries = []
    for request in http_requests:
        try:
            source_layers = request["_source"]["layers"]
            
            # Extract relevant information, handle missing keys gracefully
            frame_time = source_layers.get("frame", {}).get("frame.time", "")
            ip_src = source_layers.get("ip", {}).get("ip.src", "")
            ip_dst = source_layers.get("ip", {}).get("ip.dst", "")
            http_host = source_layers.get("http", {}).get("http.host", "")
            http_request_uri = source_layers.get("http", {}).get("http.request.full_uri", "")
            http_method = source_layers.get("http", {}).get("http.request.method", "")
            
            if not http_host or not http_request_uri:
                continue  # Skip if essential HTTP info is missing
            
            if ip_src.startswith("192.168.100."):
                log_entries.append({
                    "test_name": test_name,
                    "timestamp": frame_time,
                    "source_ip": ip_src,
                    "destination_ip": ip_dst,
                    "http_host": http_host,
                    "http_method": http_method,
                    "http_request_uri": http_request_uri
                })

        except KeyError as e:
            print(f"KeyError: {e} in request: {request}")

    with open(LOG_FILE, "a") as f:
        for entry in log_entries:
            f.write(json.dumps(entry) + "\n")

# --- Pytest Fixture ---

@pytest.fixture(scope="function")
def monitor_http_requests(request):
    """
    Fixture to isolate tests in a network namespace and capture HTTP traffic.
    """
    test_name = request.node.name
    ns_name = f"testns-{os.getpid()}-{request.node.name}"
    ns_name = ns_name.replace("[", "_").replace("]", "_")  # Sanitize name
    veth0_name = f"veth0-{os.getpid()}"
    veth1_name = f"veth1-{os.getpid()}"
    veth0_ip = "192.168.100.1/24"
    veth1_ip = "192.168.100.2/24"
    external_interface = "eth0"  # Replace with your actual external interface (e.g., eth0, enp0s3)
    pcap_file = f"{test_name}.pcap"

    # Create and configure the network namespace
    create_netns(ns_name)
    setup_veth(ns_name, veth0_name, veth1_name, veth0_ip, veth1_ip)
    setup_nat(ns_name, veth0_ip.split('/')[0], external_interface)

    # Start tcpdump before moving the process
    tcpdump_process = start_tcpdump(ns_name, veth1_name, pcap_file)

    # Move the current process to the new namespace
    original_ns = get_current_netns()
    subprocess.run(["sudo", "ip", "netns", "exec", ns_name, "nsenter", "--net="+original_ns, "--", "bash", "-c", f"exec {os.getpid()}"], check=True)

    
    def cleanup():
        
        # Ensure tcpdump is terminated
        if tcpdump_process.poll() is None:  # Check if still running
            tcpdump_process.terminate()
            try:
                tcpdump_process.wait(timeout=5)  # Wait for termination
            except subprocess.TimeoutExpired:
                tcpdump_process.kill()  # Force kill if it doesn't terminate
        
        # Analyze the pcap file
        analyze_pcap(pcap_file, test_name)

        # Clean up veth and network namespace
        subprocess.run(["sudo", "ip", "link", "delete", veth0_name], check=False)
        delete_netns(ns_name)

        # Clean up pcap file
        if os.path.exists(pcap_file):
            os.remove(pcap_file)
    
    # add finalizer to be sure we always clean up even if things go wrong.
    request.addfinalizer(cleanup)
    
    # Yeild the current namespace name in case tests need to connect to it.
    yield ns_name

# --- Global Cleanup (if needed) ---

def cleanup_all_netns():
    """Cleans up any leftover network namespaces (for safety)."""
    try:
        result = subprocess.run(["sudo", "ip", "netns"], capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if line.startswith("testns-"):
                delete_netns(line.split()[0])
    except subprocess.CalledProcessError as e:
        print(f"Error during cleanup_all_netns: {e}")

atexit.register(cleanup_all_netns)

# Terminate leftover tcpdump processes
def cleanup_tcpdump_processes():
    try:
        # Find tcpdump processes
        pids = [pid for pid in os.listdir('/proc') if pid.isdigit() and os.path.exists(os.path.join('/proc', pid, 'exe')) and os.readlink(os.path.join('/proc', pid, 'exe')).endswith('tcpdump')]

        for pid in pids:
            try:
                # Terminate each process
                os.kill(int(pid), signal.SIGTERM)
                print(f"Terminated tcpdump process with PID: {pid}")
            except ProcessLookupError:
                print(f"Process with PID {pid} not found.")
            except OSError as e:
                print(f"Error terminating process {pid}: {e}")

    except Exception as e:
        print(f"Error during cleanup_tcpdump_processes: {e}")

atexit.register(cleanup_tcpdump_processes)
