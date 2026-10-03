"""Basic smoke test — create, exec, stop, delete."""

import sys
import time

import fireagent as fa


def main() -> None:
    # Read API key from env
    api_key = "test-key"  # Default for local dev

    print("=== Fireagent smoke test ===\n")

    # 1. Create
    print("1. Creating sandbox...")
    sb = fa.create(
        image="ubuntu:24.04",
        vcpus=1,
        memory_mib=512,
        disk_mib=1024,
        ttl_seconds=300,
        labels={"test": "smoke-test"},
    )
    print(f"   Sandbox ID: {sb.id}")
    print(f"   State:       {sb.status().state}")

    # 2. Wait for ready
    print("\n2. Waiting for ready state...")
    sb.wait_for("ready", timeout_seconds=30)
    print(f"   State: {sb.status().state}")

    # 3. Execute a command
    print("\n3. Executing command...")
    result = sb.exec("echo 'Hello from Fireagent sandbox!'")
    print(f"   stdout:    {result.stdout!r}")
    print(f"   stderr:    {result.stderr!r}")
    print(f"   exit_code: {result.exit_code}")

    # 4. File persistence
    print("\n4. Testing file persistence...")
    sb.exec("echo 'persistent-data' > /workspace/test.txt")
    result = sb.exec("cat /workspace/test.txt")
    assert result.stdout.strip() == "persistent-data", "File persistence failed!"
    print(f"   File read: {result.stdout!r}")
    print("   File persistence: OK")

    # 5. Check status
    print("\n5. Getting sandbox status...")
    status = sb.status()
    print(f"   state:      {status.state}")
    print(f"   created_at: {status.created_at}")
    print(f"   host:       {status.host}")

    # 6. Stop
    print("\n6. Stopping sandbox...")
    sb.stop()
    sb.wait_for("stopped", timeout_seconds=30)
    print(f"   State: {sb.status().state}")

    # 7. Delete
    print("\n7. Deleting sandbox...")
    sb.delete()
    print("   Sandbox deleted.")

    print("\n=== Smoke test passed! ===")


if __name__ == "__main__":
    main()
