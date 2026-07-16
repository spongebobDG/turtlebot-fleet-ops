#!/usr/bin/env bash

set -euo pipefail

version="${ZENOH_VERSION:-1.9.0}"
machine="$(uname -m)"

case "${machine}" in
  x86_64)
    target="x86_64-unknown-linux-gnu"
    expected_sha256="91aa0d569fffd57e7ebb1a591b97789891c543b1ff0a1658413ce6cbbba34a9e"
    ;;
  aarch64|arm64)
    target="aarch64-unknown-linux-gnu"
    expected_sha256="e3eb1fd4459e4b877653419b1c25eaf92418d70fe53ee767eca005f1a19443dc"
    ;;
  *)
    echo "Unsupported architecture: ${machine}" >&2
    exit 1
    ;;
esac

if [[ "${version}" != "1.9.0" ]]; then
  echo "No pinned checksum is registered for Zenoh ${version}." >&2
  exit 1
fi

asset="zenoh-plugin-ros2dds-${version}-${target}-standalone.zip"
url="https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds/releases/download/${version}/${asset}"
install_dir="${HOME}/.local/opt/zenoh-bridge-ros2dds-${version}"
bin_dir="${HOME}/.local/bin"
work_dir="$(mktemp -d)"

cleanup() {
  rm -rf "${work_dir}"
}
trap cleanup EXIT

echo "Downloading ${url}"
curl --fail --location --retry 3 --output "${work_dir}/${asset}" "${url}"

actual_sha256="$(sha256sum "${work_dir}/${asset}" | awk '{print $1}')"
if [[ "${actual_sha256}" != "${expected_sha256}" ]]; then
  echo "Checksum mismatch for ${asset}" >&2
  echo "expected=${expected_sha256}" >&2
  echo "actual=${actual_sha256}" >&2
  exit 1
fi

python3 -m zipfile -e "${work_dir}/${asset}" "${work_dir}/extracted"
bridge_path="$(find "${work_dir}/extracted" -type f -name zenoh-bridge-ros2dds -print -quit)"

if [[ -z "${bridge_path}" ]]; then
  echo "zenoh-bridge-ros2dds was not found in ${asset}" >&2
  exit 1
fi

mkdir -p "${install_dir}" "${bin_dir}"
install -m 0755 "${bridge_path}" "${install_dir}/zenoh-bridge-ros2dds"
ln -sfn "${install_dir}/zenoh-bridge-ros2dds" "${bin_dir}/zenoh-bridge-ros2dds"

"${bin_dir}/zenoh-bridge-ros2dds" --version
echo "Installed ${bin_dir}/zenoh-bridge-ros2dds"
