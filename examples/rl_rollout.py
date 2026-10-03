"""RL rollout example — launch multiple sandboxes for parallel policy evaluation.

This demonstrates how an RL training loop might use Fireagent:
1. Create N sandboxes concurrently
2. Run a policy evaluation in each
3. Collect the episode results
4. Calculate the aggregate reward
5. Tear down all sandboxes
"""

import asyncio
import random
import time

import fireagent as fa


async def run_episode(episode_id: int) -> dict:
    """Simulate a single RL episode in an isolated sandbox."""
    sb = await fa.acreate(
        image="ubuntu:24.04",
        vcpus=1,
        memory_mib=256,
        disk_mib=512,
        ttl_seconds=600,
        labels={"episode_id": f"ep-{episode_id:04d}", "rollout": "rollout-001"},
    )

    try:
        # Wait for sandbox to be ready
        await sb.await_for("ready")

        # Run the policy episode (simulated)
        start = time.time()
        result = await sb.aexec(
            "python3 -c '"
            "import random, time; "
            "total_reward = 0; "
            "for step in range(100): "
            "  total_reward += random.choice([-1, 0, 1]); "
            "  time.sleep(0.001); "
            'print(f"{{total_reward}}")'
            "'"
        )
        elapsed = time.time() - start

        reward = int(result.stdout.strip())
        return {
            "episode_id": episode_id,
            "reward": reward,
            "steps": 100,
            "elapsed": elapsed,
            "exit_code": result.exit_code,
            "sandbox_id": sb.id,
        }
    finally:
        await sb.astop()
        await sb.adelete()


async def main() -> None:
    N_EPISODES = 5  # Scale to 100+ in production

    print(f"=== RL Rollout: {N_EPISODES} episodes ===\n")

    # Launch all episodes concurrently
    tasks = [run_episode(i) for i in range(N_EPISODES)]
    results = await asyncio.gather(*tasks)

    # Aggregate results
    rewards = [r["reward"] for r in results]
    total_reward = sum(rewards)
    mean_reward = total_reward / len(rewards)
    total_time = max(r["elapsed"] for r in results)
    failed = [r for r in results if r["exit_code"] != 0]

    print(f"Rollout complete:")
    print(f"  Episodes:     {N_EPISODES}")
    print(f"  Completed:    {len(results) - len(failed)}")
    print(f"  Failed:       {len(failed)}")
    print(f"  Total reward: {total_reward}")
    print(f"  Mean reward:  {mean_reward:.2f}")
    print(f"  Wall time:    {total_time:.2f}s")
    print(f"\n  Per-episode rewards: {rewards}")

    if failed:
        print(f"\n  Failed episodes: {[r['episode_id'] for r in failed]}")
    else:
        print("\n  All episodes completed successfully.")

    print("\n=== Rollout finished ===")



if __name__ == "__main__":
    asyncio.run(main())