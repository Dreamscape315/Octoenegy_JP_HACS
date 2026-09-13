#!/bin/bash
# 仅在公司电脑（有 Zscaler/公司代理做 SSL 检查）上跑 docker-compose 本地测试时需要。
#
# 现象：docker-compose 起的 Home Assistant 容器访问任何 HTTPS 接口
# （包括 Octopus 的 GraphQL 接口、HA 官方的 alerts 接口）都会报
#   SSLCertVerificationError: unable to get local issuer certificate
# 原因：公司网络对所有出站 HTTPS 做了 SSL 检查（Zscaler），Mac 系统信任了
# 公司自己签发的根证书，但容器里的证书库不认识它。
# Home Assistant 的 homeassistant/util/ssl.py 里写死了默认走 certifi 的证书包，
# 但支持用 REQUESTS_CA_BUNDLE 环境变量覆盖，所以这里把 certifi 官方证书包
# 和公司证书链拼在一起，生成一个 docker-compose.yml 里引用的 combined-ca-bundle.pem。
#
# 用法：
#   ./scripts/setup_docker_ca.sh
# 跑完之后 docker-ca/combined-ca-bundle.pem 就生成好了，
# docker compose up -d 会自动挂载它并设置 REQUESTS_CA_BUNDLE。
#
# 如果你的公司用的不是 Rakuten 的证书链，把下面三个 -c 参数改成
# 在「钥匙串访问」App 里搜到的、System 钥匙串下你司的根证书/中间证书名字即可。

set -euo pipefail
cd "$(dirname "$0")/.."

OUT_DIR="docker-ca"
mkdir -p "$OUT_DIR"

CONTAINER_NAME="${1:-octopus_jp_dev}"

echo "1/3 从 macOS 系统钥匙串导出公司证书链..."
security find-certificate -c "Rakuten Corporate IT Root CA" -p /Library/Keychains/System.keychain > "$OUT_DIR/rakuten-root.pem"
security find-certificate -c "Rakuten Corporate IT Sites Intermediate CA" -p /Library/Keychains/System.keychain > "$OUT_DIR/rakuten-intermediate.pem"
security find-certificate -c "Rakuten Corporate IT Sites CA Tokyo" -p /Library/Keychains/System.keychain > "$OUT_DIR/rakuten-tokyo.pem"

echo "2/3 从容器里取出 certifi 官方证书包..."
if ! docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  echo "容器 $CONTAINER_NAME 还没起来，先跑一次 docker compose up -d（没有 combined-ca-bundle.pem 也能先起来，只是访问外部接口会报证书错误）"
  exit 1
fi
docker cp "$CONTAINER_NAME":/usr/local/lib/python3.14/site-packages/certifi/cacert.pem "$OUT_DIR/certifi-cacert.pem"

echo "3/3 拼接成最终 bundle..."
cat "$OUT_DIR/certifi-cacert.pem" \
    "$OUT_DIR/rakuten-root.pem" \
    "$OUT_DIR/rakuten-intermediate.pem" \
    "$OUT_DIR/rakuten-tokyo.pem" \
    > "$OUT_DIR/combined-ca-bundle.pem"

echo "完成：$OUT_DIR/combined-ca-bundle.pem"
echo "接下来跑: docker compose up -d --force-recreate"

