#!/usr/bin/env bash

set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  printf 'Run this deployment script as root.\n' >&2
  exit 2
fi

image_tag=${1:-}
if [[ ! ${image_tag} =~ ^[0-9a-f]{40}$ ]]; then
  printf 'Usage: %s <40-character-git-sha>\n' "${0}" >&2
  exit 2
fi

traceosce_root=${TRACEOSCE_ROOT:-/opt/traceosce}
release_dir=$(readlink -f "${traceosce_root}/current")
shared_dir=${traceosce_root}/shared
runtime_dir=${shared_dir}/runtime
base_env=${shared_dir}/.env
image_env=${shared_dir}/image-tag.env
compose_override=${release_dir}/docker-compose.production.yml
backup_root=${traceosce_root}/backups
deployment_stamp=$(date -u +%Y%m%d-%H%M%S)
backup_dir=${backup_root}/pre-image-${image_tag:0:12}-${deployment_stamp}
rollback_tag=rollback-${deployment_stamp}

for required_path in \
  "${release_dir}/docker-compose.yml" \
  "${compose_override}" \
  "${base_env}" \
  "${runtime_dir}"; do
  if [[ ! -e ${required_path} ]]; then
    printf 'Missing deployment dependency: %s\n' "${required_path}" >&2
    exit 1
  fi
done

compose() {
  TRACEOSCE_IMAGE_TAG=${TRACEOSCE_IMAGE_TAG:-${image_tag}} \
    docker compose \
      --env-file "${base_env}" \
      -f "${release_dir}/docker-compose.yml" \
      -f "${compose_override}" \
      "$@"
}

for container in \
  clinical-osce-agent-api-1 \
  clinical-osce-agent-web-1 \
  clinical-osce-agent-admin-1; do
  if [[ $(docker inspect -f '{{.State.Health.Status}}' "${container}") != healthy ]]; then
    printf 'Refusing to deploy because %s is not healthy.\n' "${container}" >&2
    exit 1
  fi
done

mkdir -p "${backup_dir}/sqlite"
printf '%s\n' "${release_dir}" > "${backup_dir}/CURRENT_RELEASE"
compose ps --format json > "${backup_dir}/compose-before.jsonl"

docker image tag \
  "$(docker inspect -f '{{.Image}}' clinical-osce-agent-api-1)" \
  "ghcr.io/xvvln/clinical-osce-agent-api:${rollback_tag}"
docker image tag \
  "$(docker inspect -f '{{.Image}}' clinical-osce-agent-web-1)" \
  "ghcr.io/xvvln/clinical-osce-agent-web:${rollback_tag}"
docker image tag \
  "$(docker inspect -f '{{.Image}}' clinical-osce-agent-admin-1)" \
  "ghcr.io/xvvln/clinical-osce-agent-admin:${rollback_tag}"

rollback() {
  local exit_code=$?
  trap - ERR
  printf 'Deployment failed; restoring the previous images.\n' >&2
  TRACEOSCE_IMAGE_TAG=${rollback_tag} compose up -d --no-build --wait --wait-timeout 240 || true
  exit "${exit_code}"
}
trap rollback ERR

compose pull api web admin
compose stop api

(
  cd "${runtime_dir}"
  find . -type f \
    \( -name '*.sqlite3*' -o -name '*.sqlite*' -o -name '*.db*' \) \
    -print0 \
    | tar --null -T - -cpf "${backup_dir}/sqlite/runtime-sqlite.tar"
)

sqlite_file_count=$(tar -tf "${backup_dir}/sqlite/runtime-sqlite.tar" | wc -l | tr -d ' ')
if [[ ${sqlite_file_count} -lt 1 ]]; then
  printf 'Database snapshot is empty; refusing to switch images.\n' >&2
  false
fi

compose up -d --no-build --wait --wait-timeout 240

for endpoint in \
  http://127.0.0.1:8000/ready \
  http://127.0.0.1:3000/ \
  http://127.0.0.1:3001/; do
  curl --fail --silent --show-error "${endpoint}" >/dev/null
done

image_env_tmp=$(mktemp "${shared_dir}/.image-tag.XXXXXX")
chmod 600 "${image_env_tmp}"
printf 'TRACEOSCE_IMAGE_TAG=%s\n' "${image_tag}" > "${image_env_tmp}"
mv "${image_env_tmp}" "${image_env}"
printf '%s\n' "${image_tag}" > "${shared_dir}/DEPLOYED_IMAGE_TAG"

trap - ERR
printf 'DEPLOYED_IMAGE_TAG=%s\n' "${image_tag}"
printf 'DATABASE_BACKUP=%s\n' "${backup_dir}"
