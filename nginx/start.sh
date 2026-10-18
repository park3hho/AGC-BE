#!/bin/sh
# nginx 시작 — 인증서가 있으면 https 설정, 없으면 발급용 http 설정.
# 1시간마다 설정을 다시 만들고 reload → 첫 발급·자동 갱신된 인증서를 재시작 없이 반영한다.
set -e

# 도메인을 아직 안 정했으면 아무 이름이나 받는 "_" 로 (http 설정만 쓰인다)
export DOMAIN="${DOMAIN:-_}"

render() {
    if [ -n "$DOMAIN" ] && [ -f /etc/letsencrypt/live/agc/fullchain.pem ]; then
        tpl=https
    else
        tpl=http
    fi
    envsubst '${DOMAIN}' < "/etc/nginx/agc/$tpl.conf.template" > /etc/nginx/conf.d/default.conf
    echo "nginx 설정: $tpl (DOMAIN=$DOMAIN)"
}

render
(
    while :; do
        sleep 3600
        render && nginx -s reload
    done
) &

exec nginx -g 'daemon off;'
