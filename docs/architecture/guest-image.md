# Guest Image Construction

## Why it matters

The guest image is the foundation of isolation. It's the **only** component that runs in the guest kernel — all other layers (workspace, code, secrets) are mounted or attached at runtime.

Fireagent's guest image must be:

- **Minimal** – Only packages needed for core development tasks.
- **Immutable** – No changes after build; all task state lives in the workspace volume.
- **Reproducible** – Same inputs, same output, regardless of build environment.
- **Secure** – No default credentials, no enabled services, no unnecessary packages.
- **Versioned** – Semantic versioning with digest tracking.
- **Verified** – Signed by the build system and scanned before use.

## Build process

We use a **buildroot-based** approach to create a minimal root filesystem. Buildroot is chosen for its reproducibility, simplicity, and strong package management.

### Build steps

1. **Configure Buildroot**
   - Use `buildroot-2025.02` (LTS version)
   - Set `BR2_TARGET_ROOTFS_CPIO` to generate a cpio archive
   - Enable `BR2_PACKAGE_LINUX_KERNEL` with Firecracker-compatible kernel
   - Select only necessary packages:
     - `bash`, `coreutils`, `findutils`, `grep`, `sed`, `awk`, `grep`
     - `git`, `python3`, `pip3`, `curl`, `wget`, `dnsutils`, `ca-certificates`
     - `openssh-client` (but no server)
     - `systemd` (minimal init with predictable startup)

2. **Pinned dependencies**
   - All packages are pinned to specific versions (e.g., `python3-3.12.3`)
   - No `latest`, no `unstable`, no `HEAD`

3. **Build image**
   - Run `make` in the buildroot environment
   - Output: `output/images/rootfs.cpio`

4. **Generate filesystem**
   - Convert cpio to ext4:
     ```bash
     sudo mkfs.ext4 -F -b 4096 -i 4096 -m 1 -L rootfs rootfs.ext4 < rootfs.cpio
     ```
   - Size: ~150 MiB compressed, ~400 MiB uncompressed

5. **Add guest agent**
   - Copy the `fireagent-guest-agent` binary into `/usr/bin`
   - Set `+x` permission
   - Create init script in `/etc/init.d/S99fireagent` to start on boot

6. **Sign image**
   - Use `gpg --clearsign` to sign the image
   - Store signature in `rootfs.ext4.asc`

7. **Generate SBOM**
   - Use `syft` to generate a Software Bill of Materials:
     ```bash
     syft rootfs.ext4 -o spdx-json > sbom.json
     ```

8. **Scan for vulnerabilities**
   - Run `trivy` scan:
     ```bash
     trivy image --exit-code 1 --severity HIGH,CRITICAL rootfs.ext4
     ```

9. **Build digest**
   - Compute SHA256 digest:
     ```bash
     sha256sum rootfs.ext4
     ```

10. **Store in artifact repository**
    - Upload to local SSD at `/artifacts/images/ubuntu:24.04`
    - Record in `images` table with digest, build date, SBOM URL, scan report URL

## Image versioning

Images are versioned as `distro:version` (e.g., `ubuntu:24.04`).

- `ubuntu:24.04` → Initial release
- `ubuntu:24.04-rc1` → Pre-release with new packages
- `ubuntu:24.04-rc2` → Patched security fix

New versions are promoted only after:
- Successful build
- Passes vulnerability scan
- Verified by GPG signature
- Tested in single-host prototype

## Image lifecycle

| Status | Action |
|--------|--------|
| `draft` | Image built, not yet signed or scanned |
| `pending` | Signed and scanned, awaiting review |
| `approved` | Ready for host use |
| `deprecated` | New version available, old version no longer allowed |
| `removed` | Purged from artifact storage |

## Boot-to-ready time

Measured with a test script:

```bash
#!/bin/bash
# test-boot.sh
set -e

start=$(date -u +%s.%N)

# Launch Firecracker with image
firecracker --api-sock /tmp/firecracker.sock --no-api --kernel /path/to/kernel --rootfs /path/to/rootfs.ext4

# Wait for guest agent to report healthy
while ! curl --silent --fail http://localhost:8080/health; do
  sleep 0.1
  if [[ $(($(date -u +%s.%N) - $start)) -gt 5.0 ]]; then
    echo "Boot timeout after 5 seconds"
    exit 1
  fi
done

end=$(date -u +%s.%N)

echo "Boot-to-ready: $(echo "$end - $start" | bc -l) seconds"
```

**Target**: < 150 ms for idle guest with minimal init.

## Security hardening

- **No root password** – No default login or credentials.
- **No SSH server** – Only `openssh-client` is installed.
- **No network services** – Only `systemd-networkd` (minimal) is enabled.
- **Minimal kernel** – Only virtio, KVM, and Firecracker device drivers.
- **No debug services** – `kmod`, `dmesg`, `strace` not installed.
- **No shell history** – `/root/.bash_history` is wiped at boot.
- **No swap** – Disabled to reduce attack surface.

## Comparison: image size vs. functionality

| Image | Size | Packages | Use case |
|-------|------|----------|----------|
| `minimal:0.1` | 75 MiB | 12 | Barebones CLI, basic tools |
| `ubuntu:24.04` | 400 MiB | 110 | Agent workloads, code evaluation |
| `ubuntu:24.04-tf` | 700 MiB | 180 | TensorFlow, PyTorch, ML models |

We chose `ubuntu:24.04` as the default because it balances size, functionality, and workload compatibility.

## Next steps

- [ ] Add CI/CD pipelines to automate build, scan, and promote
- [ ] Integrate with artifact storage (S3, local SSD)
- [ ] Add `vulnerability_scan_passed` field to `images` table
- [ ] Implement image rollback on scan failure
- [ ] Document `fireagent-guest-agent` protocol