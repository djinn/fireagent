"""Agent workflow example — simulate an AI agent using a sandbox.

This demonstrates how an agent harness might use Fireagent:
1. Create a sandbox with a task repository
2. Have the agent explore and edit files
3. Run tests
4. Collect results
5. Clean up
"""

import fireagent as fa
import json


def main() -> None:
    print("=== Agent workflow example ===\n")

    # Create sandbox with workspace
    sb = fa.create(
        image="ubuntu:24.04",
        vcpus=2,
        memory_mib=1024,
        disk_mib=2048,
        ttl_seconds=1800,
        labels={
            "job_id": "job-001",
            "task_id": "task-abc",
            "agent_id": "agent-gpt4",
        },
    )
    print(f"Created sandbox: {sb.id}")
    sb.wait_for("ready")

    # Agent reads a file
    print("\n1. Agent reads workspace contents...")
    result = sb.exec("ls -la /workspace")
    print(f"   {result.stdout}")

    # Agent writes a solution
    print("\n2. Agent writes solution...")
    sb.exec("cat > /workspace/solution.py << 'EOF'",
            working_dir="/workspace")
    sb.exec("""cat > /workspace/solution.py << 'PYEOF'
def solve(n: int) -> int:
    \"\"\"Return the nth Fibonacci number.\"\"\"
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
PYEOF""")
    print("   Solution written.")

    # Agent runs tests
    print("\n3. Agent runs tests...")
    sb.exec("""cat > /workspace/test_solution.py << 'PYEOF'
from solution import solve

def test_solve():
    assert solve(0) == 0
    assert solve(1) == 1
    assert solve(10) == 55
    assert solve(20) == 6765
    print("All tests passed!")
PYEOF""")
    result = sb.exec("python3 /workspace/test_solution.py")
    print(f"   stdout: {result.stdout}")
    print(f"   exit_code: {result.exit_code}")

    # Agent collects artifacts
    print("\n4. Agent collects output...")
    result = sb.exec("python3 -c 'from solution import solve; print(solve(100))'")
    print(f"   Fibonacci(100) = {result.stdout.strip()}")

    # Agent logs the session
    print("\n5. Session summary:")
    status = sb.status()
    print(f"   sandbox_id: {sb.id}")
    print(f"   state:      {status.state}")
    print(f"   duration:   {status.ttl_seconds}s TTL")

    # Clean up
    print("\n6. Cleaning up...")
    sb.stop()
    sb.wait_for("stopped")
    sb.delete()
    print("   Sandbox deleted.")

    print("\n=== Agent workflow completed! ===")



if __name__ == "__main__":
    main()