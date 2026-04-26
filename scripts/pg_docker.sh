#!/usr/bin/env bash
# Обёртка над «docker» / «sudo docker» для pg_backup.sh и pg_restore.sh.
# shellcheck disable=SC2034
_DOCKER=()

pg_docker_init() {
  if [[ "${PG_DOCKER_FORCE_SUDO:-}" == "1" ]]; then
    if ! sudo docker info >/dev/null 2>&1; then
      echo "pg_docker: sudo docker недоступен" >&2
      return 1
    fi
    _DOCKER=(sudo docker)
    return 0
  fi
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    _DOCKER=(docker)
    return 0
  fi
  if sudo docker info >/dev/null 2>&1; then
    _DOCKER=(sudo docker)
    return 0
  fi
  echo "pg_docker: нет доступа к Docker. Установите docker или: sudo usermod -aG docker \"\$USER\"" >&2
  return 1
}

pg_docker() {
  "${_DOCKER[@]}" "$@"
}
