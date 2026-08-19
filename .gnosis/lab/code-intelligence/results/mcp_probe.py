"""Minimal MCP stdio client: initialize, list tools, call one tool.
Generic (argv: server command...). Used to test MCP integration quality
for code-intelligence candidates in the M2.1 lab, read/query only.
"""
import json
import subprocess
import sys


def send(proc, msg):
    data = json.dumps(msg)
    header = f"Content-Length: {len(data)}\r\n\r\n"
    proc.stdin.write((header + data).encode("utf-8"))
    proc.stdin.flush()


def read_message(proc):
    headers = {}
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        line = line.decode("utf-8", errors="replace").strip()
        if line == "":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length", "0"))
    if length == 0:
        return None
    body = proc.stdout.read(length)
    return json.loads(body.decode("utf-8", errors="replace"))


def main():
    argv = sys.argv[1:]
    cwd = argv[0]
    server_cmd = argv[1:]
    proc = subprocess.Popen(
        server_cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    send(proc, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "gnosis-mcp-probe", "version": "0.1"},
        },
    })
    init_reply = read_message(proc)
    print("INIT:", json.dumps(init_reply)[:500])

    send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools_reply = read_message(proc)
    tool_names = [t["name"] for t in tools_reply.get("result", {}).get("tools", [])]
    print("TOOLS:", json.dumps(tool_names))

    if len(argv) > len(server_cmd) + 1:
        pass

    proc.stdin.close()
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    err = proc.stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        print("STDERR TAIL:", err[-1000:])


if __name__ == "__main__":
    main()
